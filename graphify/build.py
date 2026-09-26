# assemble node+edge dicts into a NetworkX graph, preserving edge direction
#
# Node deduplication — three layers:
#
# 1. Within a file (AST): each extractor tracks a `seen_ids` set. A node ID is
#    emitted at most once per file, so duplicate class/function definitions in
#    the same source file are collapsed to the first occurrence.
#
# 2. Between files (build): NetworkX G.add_node() is idempotent — calling it
#    twice with the same ID overwrites the attributes with the second call's
#    values. Nodes are added in extraction order (AST first, then semantic),
#    so if the same entity is extracted by both passes the semantic node
#    silently overwrites the AST node. This is intentional: semantic nodes
#    carry richer labels and cross-file context, while AST nodes have precise
#    source_location. If you need to change the priority, reorder extractions
#    passed to build().
#
# 3. Semantic merge (skill): before calling build(), the skill merges cached
#    and new semantic results using an explicit `seen` set keyed on node["id"],
#    so duplicates across cache hits and new extractions are resolved there
#    before any graph construction happens.
#
from __future__ import annotations
import json
import math
import os
import re
import sys
import unicodedata
from collections.abc import Iterable
from pathlib import Path
import networkx as nx
from .ids import make_id, normalize_id as _normalize_id
from .paths import default_graph_json as _default_graph_json
from .paths import is_absolute_any_platform as _is_abs
from .validate import validate_extraction


# Deterministic (AST) extractors emit source_location "L<line>"; the semantic
# extraction spec emits null. Used by _is_ast_tier as a shape fallback for
# legacy items that predate the _origin marker (#2334).
_AST_LOC_RE = re.compile(r"^L\d")


def _is_ast_tier(item: dict) -> bool:
    """AST vs semantic tier. _origin wins when present; unstamped legacy items
    (pre-0.9.16) fall back to shape: deterministic extractors emit
    source_location 'L<line>', the semantic spec emits null (#2334)."""
    o = item.get("_origin")
    if o is not None:
        return o == "ast"
    loc = item.get("source_location")
    return isinstance(loc, str) and bool(_AST_LOC_RE.match(loc))


# Relations that say only "these two symbols appear together", with no claim about
# HOW. An extractor that finds a specific fact for a pair — a call, an import, an
# inheritance — routinely emits one of these for the same pair as well, so when the
# simple graph collapses the pair to one edge, the generic one must never be the
# survivor. Deliberately a small denylist rather than a full precedence order over
# every relation: ranking `contains` against `calls` would be inventing a
# cross-axis judgement, whereas "specific beats generic" is the only comparison
# this collapse actually needs.
_GENERIC_RELATIONS: frozenset[str] = frozenset({"references", "uses", "mentions"})
_CONFIDENCE_RANK: dict[str, int] = {"EXTRACTED": 3, "INFERRED": 2, "AMBIGUOUS": 1}

# Import-family relations whose target may legitimately be a module OUTSIDE the
# graph (stdlib, a third-party dependency, another repo). Historically the edge
# to such a target was dropped, which left the in-memory graph clean but let the
# on-disk graph.json (written by the incremental update path) keep the edge with
# no matching node — an undeclared endpoint every loader materialises as an
# attribute-less phantom (#2873). For these relations we instead mint a typed
# external stub node so every edge endpoint resolves. Deliberately NOT `calls`:
# a sourceless external call target is suppressed on purpose (#3156) to avoid a
# phantom god-node, and that policy is unchanged here.
_EXTERNAL_STUB_RELATIONS: frozenset[str] = frozenset(
    {"imports", "imports_from", "re_exports"}
)


def _mint_external_stub(G: "nx.Graph", node_set: set, nid: str) -> None:
    """Add a leaf node for an external import target so the edge is not dangling.

    The node is tagged ``external`` (and ``file_type='concept'`` so the schema
    validator and community/report code treat it as a non-source concept rather
    than warning on a missing ``file_type``). ``merge-graphs`` reads the
    ``external`` flag to keep these ids global instead of namespacing them per
    repo, so the same stdlib/dependency module unifies across repos (#2873).
    """
    if nid in node_set:
        return
    G.add_node(
        nid,
        label=nid,
        file_type="concept",
        type="external",
        external=True,
        source_file="",
    )
    node_set.add(nid)


def mint_external_stubs_in_data(data: dict) -> None:
    """Mint external stub nodes for import-family links with an undeclared target.

    The ``--no-cluster`` / incremental write path serializes the raw merged
    extraction directly rather than going through :func:`build_from_json`, so it
    needs the same stubbing to keep the on-disk graph.json free of undeclared
    edge endpoints (#2873). Idempotent: a graph already carrying its stubs (from
    a prior run or the clustered path) is left unchanged.
    """
    nodes = data.get("nodes")
    links = data.get("links")
    if not isinstance(links, list):
        links = data.get("edges")
    if not isinstance(nodes, list) or not isinstance(links, list):
        return
    declared = {n.get("id") for n in nodes if isinstance(n, dict)}
    minted: set[str] = set()
    for e in links:
        if not isinstance(e, dict) or e.get("relation") not in _EXTERNAL_STUB_RELATIONS:
            continue
        src, tgt = e.get("source"), e.get("target")
        if (
            src in declared
            and isinstance(tgt, str)
            and tgt not in declared
            and tgt not in minted
        ):
            nodes.append({
                "id": tgt,
                "label": tgt,
                "file_type": "concept",
                "type": "external",
                "external": True,
                "source_file": "",
            })
            minted.add(tgt)

# Language interop families, keyed by extension, for the cross-language phantom-edge
# guard in the edge loop below. Families group by REAL interop (JS/TS share a module
# graph; C/C++/ObjC share a compilation unit via headers; JVM langs share bytecode),
# so a legitimate TS->JS import or C impl->header call survives, while a Python
# `import time` binding to a `time.ts` (#1749) or a cross-language INFERRED `calls`
# edge (#1547/#1556) is dropped. Kept local to build.py (not imported from extract.py,
# which imports build.py — a cycle) and deliberately mirrors extract._LANG_FAMILY_BY_EXT.
_EDGE_LANG_FAMILY: dict[str, str] = {
    ".py": "py", ".pyi": "py",
    ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js",
    ".ts": "js", ".tsx": "js", ".mts": "js", ".cts": "js",
    ".go": "go", ".rs": "rs",
    ".java": "jvm", ".kt": "jvm", ".scala": "jvm", ".groovy": "jvm",
    ".c": "c", ".h": "c", ".cc": "c", ".cpp": "c", ".hpp": "c",
    ".cxx": "c", ".hh": "c", ".hxx": "c",
    ".cu": "c", ".cuh": "c", ".metal": "c", ".m": "c", ".mm": "c",
    ".rb": "rb", ".rake": "rb", ".php": "php", ".cs": "cs", ".swift": "swift", ".lua": "lua",
}


# Synonym mapper for known invalid file_type values that LLM subagents commonly
# emit. Keeps semantic intent close (markdown→document, tool→code) and falls
# back to "concept" for any other invalid value (see #840).
_FILE_TYPE_SYNONYMS = {
    "markdown": "document",
    "text": "document",
    "tool": "code",
    "library": "code",
    "pattern": "concept",
    "principle": "concept",
    "constraint": "concept",
    "tech": "concept",
    "technology": "concept",
    "data-source": "concept",
    "data_source": "concept",
    "gotcha": "concept",
    "framework": "concept",
}


# Hyperedge member lists are canonically keyed `nodes` (see graphify/llm.py
# extraction spec), but LLM/subagent drift and externally-supplied graph.json
# sometimes emit `members` or `node_ids`. _normalize_hyperedge_members folds
# those aliases into `nodes` at ingest so every downstream consumer reads one
# canonical key — mirroring the `from`/`to` edge-endpoint tolerance below.
_HE_MEMBER_ALIASES = ("members", "node_ids")


def _coerce_hyperedge_member_refs(he: dict, members: list) -> list:
    """Coerce a hyperedge member list to hashable scalar ids, deduped in order.

    LLM/subagent drift sometimes emits a member as an object (``{"id": "a_ts"}``)
    instead of a bare id string. Left uncoerced, the dict member is unhashable,
    so the semantic-rekey pass's ``_rekey.get(n, n)`` raised ``TypeError`` and
    aborted the whole merge — destroying a completed extraction (#2486). Object
    members collapse to their non-empty ``id`` (numeric ids str-coerced via
    ``_coerce_id``, matching #2326); members with no usable id are dropped with
    a stderr WARNING naming the hyperedge, never a crash. Hashable scalar refs
    pass through unchanged. A hyperedge that loses every member this way falls
    to the existing no-valid-members drop-with-warning in ``build_from_json``.
    """
    seen: set = set()
    coerced: list = []
    for ref in members:
        if isinstance(ref, dict):
            inner = _coerce_id(ref.get("id"))
            if inner in (None, "") or not _hashable(inner):
                print(
                    f"[graphify] WARNING: hyperedge "
                    f"'{he.get('id', '?')}' has a member object with no usable "
                    f"'id' ({ref!r}); dropping that member.",
                    file=sys.stderr,
                )
                continue
            ref = inner
        elif not _hashable(ref):
            print(
                f"[graphify] WARNING: hyperedge "
                f"'{he.get('id', '?')}' has an unusable member reference "
                f"{ref!r}; dropping that member.",
                file=sys.stderr,
            )
            continue
        if ref in seen:
            continue
        seen.add(ref)
        coerced.append(ref)
    return coerced


def _normalize_hyperedge_members(he: object) -> None:
    """Canonicalize a hyperedge's member list onto the `nodes` key, in place.

    If `nodes` is already a list it wins (canonical), and only stray alias keys
    are dropped. Otherwise the first alias (`members`, then `node_ids`) that is a
    list is moved to `nodes`, with a single stderr WARNING naming the hyperedge
    id and alias used. Leftover alias keys are always removed so downstream code
    never re-reads them. Whichever branch supplied the list, member VALUES are
    coerced to hashable scalar ids and deduped preserving order (#2486) — see
    ``_coerce_hyperedge_member_refs``.
    """
    if not isinstance(he, dict):
        return
    if isinstance(he.get("nodes"), list):
        he["nodes"] = _coerce_hyperedge_member_refs(he, he["nodes"])
    else:
        for alias in _HE_MEMBER_ALIASES:
            val = he.get(alias)
            if isinstance(val, list):
                he["nodes"] = _coerce_hyperedge_member_refs(he, val)
                print(
                    f"[graphify] WARNING: hyperedge "
                    f"'{he.get('id', '?')}' uses field '{alias}' instead of "
                    f"'nodes'; normalizing.",
                    file=sys.stderr,
                )
                break
    # Drop any leftover alias keys regardless of which branch ran above.
    for alias in _HE_MEMBER_ALIASES:
        he.pop(alias, None)


def _fold_node_aliases(node: dict) -> None:
    """Fold legacy node field aliases onto canonical keys, in place (#2194).

    ``name`` -> ``label`` and ``path`` -> ``source_file``. Uses an empty-check
    (not mere key presence) so a node carrying ``label: ""``/``None`` next to a
    real ``name`` is healed too. When the canonical field already holds a value
    it wins and the alias key is left untouched. Without this fold an alias-only
    node enters the graph with no label/source_file: it fails validation, gets
    ``norm_label == ""`` (invisible to query/explain), and is excluded from every
    label-keyed merge/dedup — a permanent ghost that ``graphify update``
    re-feeds through build_from_json forever.
    """
    if not node.get("label") and isinstance(node.get("name"), str) and node["name"]:
        node["label"] = node.pop("name")
    if not node.get("source_file") and isinstance(node.get("path"), str) and node["path"]:
        node["source_file"] = node.pop("path")


def _fold_edge_aliases(edge: dict) -> None:
    """Fold legacy edge field aliases onto canonical keys, in place (#2194).

    ``type`` -> ``relation``. A ``confidence_score`` float with no ``confidence``
    enum backfills ``confidence: "INFERRED"`` — never EXTRACTED (alias recovery
    is not provenance) and never a threshold mapping of the float. The
    ``confidence_score`` key itself is NOT popped: it is a legitimate companion
    field that the edge loop sanitizes and to_json round-trips.

    A NUMERIC ``confidence`` (pre-enum graphs stored the LLM pass's float —
    1.0/0.95/0.9/0.85 — directly in the field) normalizes to ``INFERRED``:
    numeric confidences only ever came from the LLM semantic pass, and
    LLM-derived edges are INFERRED by definition. The original float moves to
    ``confidence_score`` unless an explicit one is already present (the
    companion field is the authority). Without this fold, every reload of a
    pre-enum graph re-warns once per legacy edge, forever. ``bool`` is
    excluded despite subclassing ``int``: ``True`` is not a score.
    """
    if not edge.get("relation") and isinstance(edge.get("type"), str) and edge["type"]:
        edge["relation"] = edge.pop("type")
    _conf = edge.get("confidence")
    if isinstance(_conf, (int, float)) and not isinstance(_conf, bool):
        if edge.get("confidence_score") is None:
            edge["confidence_score"] = float(_conf)
        edge["confidence"] = "INFERRED"
    if not edge.get("confidence") and edge.get("confidence_score") is not None:
        edge["confidence"] = "INFERRED"


def _coerce_id(value: object) -> object:
    """Return a str for a numeric id, else the value unchanged.

    ``bool`` is excluded despite subclassing ``int``: an id of ``True`` is not a
    number the model meant to name a node, and ``"True"`` would invent a label.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return str(value)


def _hashable(value: object) -> bool:
    """True when value can be a dict key / set member (same probe as the
    inline ``try: hash(m)`` in build_from_json's hyperedge revalidation)."""
    try:
        hash(value)
    except TypeError:
        return False
    return True


def _coerce_non_string_ids(extraction: dict) -> None:
    """Coerce numeric node ids and edge/hyperedge references to str, in place (#2326).

    A backend can emit ``{"id": 10}`` where the schema says ``{"id": "10"}``.
    Every id consumer downstream assumes ``str``, so one int id aborted the build
    in three places: ``_pick_winner``'s ``_CHUNK_SUFFIX.search(n["id"])`` raised
    ``TypeError: expected string or bytes-like object``, and ``build_from_json``'s
    ``sorted(node_set)`` raised ``'<' not supported between instances of 'str'
    and 'int'`` — the latter for a lone node with nothing to dedup at all.
    Coercing keeps the node and its edges rather than dropping either, which is
    the same tolerate-and-heal treatment loose backend output already gets at the
    parse chokepoint (#1631) and in the alias folds (#2194).

    Endpoints and hyperedge members are coerced with the nodes, not after: a
    node-only coercion would renumber ``10`` to ``"10"`` and leave every edge
    pointing at the vanished ``10``, trading a loud crash for a silently
    disconnected graph. The legacy ``from``/``to`` endpoint aliases are included
    because dedup reads them directly (#803).

    Runs in BOTH ``build`` (before dedup, which keys on id) and
    ``build_from_json`` (the direct entry that reloads a persisted graph), for
    the same two-site reason as the ``_fold_node_aliases`` fold (#2194). It is
    idempotent, so the nested call on the ``build`` path is a no-op.

    Non-numeric non-str ids (``None``, lists, dicts) are left alone for
    ``validate_extraction`` to report: ``str(None) == "None"`` would fabricate a
    node id that no edge references.
    """
    for node in extraction.get("nodes") or ():
        if isinstance(node, dict) and "id" in node:
            node["id"] = _coerce_id(node["id"])
    for edge in extraction.get("edges") or ():
        if not isinstance(edge, dict):
            continue
        for key in ("source", "target", "from", "to"):
            if key in edge:
                edge[key] = _coerce_id(edge[key])
    for he in extraction.get("hyperedges") or ():
        if not isinstance(he, dict):
            continue
        members = he.get("nodes")
        if isinstance(members, list):
            he["nodes"] = [_coerce_id(ref) for ref in members]


def _norm_source_file(p: str | None, root: str | None = None) -> str | None:
    """Normalize path separators and relativize absolute paths.

    Converts backslashes to forward slashes (Windows compatibility) and, when
    root is provided, strips the absolute prefix from paths produced by semantic
    subagents so source_file is always repo-relative (fixes #932).
    """
    if not p:
        return p
    p = p.replace("\\", "/")
    if root and _is_abs(p):
        try:
            p = Path(p).relative_to(root).as_posix()
        except ValueError:
            # Lexical relative_to failed. Retry with both sides fully resolved:
            # a symlinked scan root (macOS /var -> /private/var, or a symlinked
            # home/worktree) makes the raw prefixes differ even though they point
            # at the same dir, which otherwise silently defeats prune/replace
            # matching. Only the slow path resolves, so the common lexical match
            # stays filesystem-free.
            try:
                p = Path(p).resolve().relative_to(Path(root).resolve()).as_posix()
            except (ValueError, OSError):
                pass
    return p


def _abs_identity(p: str | None, root: str | None = None) -> str | None:
    """Return a form-insensitive absolute identity for a source_file.

    prune/replace matching in build_merge otherwise compares raw strings against
    ``_norm_source_file`` output, so a node whose source_file survived in a THIRD
    form — absolute where prune_sources is relative, or vice versa, or a symlinked
    root — slips past every equality check and its nodes/edges are never pruned
    (silent survival of a deleted file's graph, #2012). Anchoring relative paths
    at ``root`` and resolving both sides to a canonical absolute posix path gives
    a fallback that matches regardless of which form each side happens to hold.
    """
    if not p:
        return None
    q = p.replace("\\", "/")
    pp = Path(q)
    if not _is_abs(q) and root:
        pp = Path(root) / q
    try:
        return pp.resolve().as_posix()
    except OSError:
        return pp.as_posix()


def _is_file_node_label(label: "str | None", source_file: "str | None") -> bool:
    """Whether *label* is a file node's label for *source_file* — the bare
    basename, OR a directory-qualified suffix produced by the disambiguation pass
    below (#2032). Used both to recognize file nodes when relabeling and by the
    downstream file-node predicates (analyze/tree/serve)."""
    if not label or not source_file:
        return False
    sf = str(source_file).replace("\\", "/")
    lbl = str(label)
    if lbl == sf.rsplit("/", 1)[-1]:
        return True
    return "/" in lbl and (sf == lbl or sf.endswith("/" + lbl))


def _shortest_unique_suffix(sf: str, all_sfs: "set[str]") -> str:
    """Shortest trailing path suffix (basename + k parent dirs) of *sf* that is
    unique among *all_sfs*. `a/b/index.ts` vs `c/b/index.ts` -> `a/b/index.ts`;
    `x/index.ts` vs `y/index.ts` -> `x/index.ts`. Derived from the path (never the
    current label) so relabeling is idempotent across incremental rebuilds."""
    parts = [p for p in sf.replace("\\", "/").split("/") if p]
    others = [
        [p for p in o.replace("\\", "/").split("/") if p]
        for o in all_sfs if o != sf
    ]
    for k in range(1, len(parts) + 1):
        suffix = parts[-k:]
        if all(o[-k:] != suffix for o in others):
            return "/".join(suffix)
    return "/".join(parts)


def _file_label_reassignments(items: "list[tuple]") -> dict:
    """Given (key, label, source_file) triples, return {key: new_label} for file
    nodes whose basename collides with another's — the shortest unique
    directory-qualified suffix (#2032). Keys of non-colliding/basename-unique file
    nodes are omitted (their label stays bare)."""
    from collections import defaultdict
    groups: dict[str, list[tuple]] = defaultdict(list)
    for key, label, sf in items:
        if sf and label and _is_file_node_label(str(label), str(sf)):
            basename = str(sf).replace("\\", "/").rsplit("/", 1)[-1]
            groups[basename].append((key, str(sf)))
    out: dict = {}
    for members in groups.values():
        distinct = {sf for _, sf in members}
        if len(distinct) < 2:
            continue  # no collision — leave the bare basename label
        for key, sf in members:
            out[key] = _shortest_unique_suffix(sf, distinct)
    return out


def _disambiguate_file_node_labels(G: "nx.Graph") -> None:
    """Relabel colliding-basename file nodes on a graph (#2032). Ids/edges are
    never changed — only display labels. Idempotent (labels derive from
    source_file, not the current possibly-qualified label)."""
    items = [(nid, a.get("label"), a.get("source_file")) for nid, a in G.nodes(data=True)]
    for nid, new_label in _file_label_reassignments(items).items():
        G.nodes[nid]["label"] = new_label


def disambiguate_file_labels_in_nodes(nodes: "list") -> None:
    """Relabel colliding-basename file nodes on a raw node-dict list, in place
    (#2032). Used by the extract --no-cluster path, which writes the merged
    extraction directly without going through build_from_json."""
    items = [
        (i, n.get("label"), n.get("source_file"))
        for i, n in enumerate(nodes) if isinstance(n, dict)
    ]
    for i, new_label in _file_label_reassignments(items).items():
        nodes[i]["label"] = new_label


def _infer_merge_root(graph_path: Path) -> str | None:
    """Best-effort scan root for relativizing paths in build_merge when the caller
    passes no ``root`` (#1571).

    Prefers the committed ``graphify-out/.graphify_root`` marker — the authoritative
    scan root graphify records at build/watch time (#686/#1423) — then falls back to
    the directory that contains the output dir (``graph.json``'s grandparent, i.e.
    ``<root>/graphify-out/graph.json`` -> ``<root>``). The grandparent heuristic is
    applied only when ``graph.json``'s own directory actually looks like a graphify
    out-dir (named like one, or holding the marker/manifest); for arbitrary layouts
    (``<root>/graph.json``, #2446) the grandparent is NOT the scan root, and guessing
    it made absolute prune_sources silently no-op. Returns None if neither resolves,
    in which case normalization is a no-op (prior behavior) and prune matching can
    still recover via :func:`_derive_prune_root`.
    """
    parent = graph_path.parent
    try:
        marker = parent / ".graphify_root"
        if marker.exists():
            recorded = marker.read_text(encoding="utf-8-sig").strip()
            recorded_path = Path(recorded)
            if recorded and recorded_path.is_dir():
                return str(recorded_path.resolve())
    except OSError:
        pass
    from .paths import GRAPHIFY_OUT
    try:
        if (
            parent.name == Path(GRAPHIFY_OUT).name
            or (parent / ".graphify_root").exists()
            or (parent / "manifest.json").exists()
        ):
            return str(parent.parent.resolve())
    except Exception:
        pass
    return None


def _build_prune_sets(
    prune_sources: "list[str] | None",
    eff_root: "str | None",
    new_sources: "set[str]",
) -> "tuple[dict[str, str], dict[str, str]]":
    """Prune match sets for build_merge / merge_raw_extraction.

    Returns ``(prune_set, prune_abs)`` mapping every match form of each prune
    entry — the raw string, the :func:`_norm_source_file` relative form, and the
    :func:`_abs_identity` absolute form — back to the ORIGINAL entry, so callers
    can report which entries actually matched something (#2446). Membership
    tests read like the old set-based code (``sf in prune_set``).

    "Replace" wins over a contradictory "delete" of the same source (#1796), in
    both string and absolute-identity space (#2012): every form belonging to a
    source re-extracted this run is removed.
    """
    prune_set: dict[str, str] = {}
    prune_abs: dict[str, str] = {}
    for p in (prune_sources or []):
        if not p:
            continue
        prune_set.setdefault(p, p)
        norm = _norm_source_file(p, eff_root)
        if norm:
            prune_set.setdefault(norm, p)
        a = _abs_identity(p, eff_root)
        if a:
            prune_abs.setdefault(a, p)
    for s in new_sources:
        prune_set.pop(s, None)
        a = _abs_identity(s, eff_root)
        if a:
            prune_abs.pop(a, None)
    return prune_set, prune_abs


def _derive_prune_root(prune_sources: "list[str]", stored_sfs: "set[str]") -> "str | None":
    """Derive the scan root from absolute prune paths that matched nothing (#2446).

    When build_merge/merge_raw_extraction receive absolute prune_sources but no
    ``root``, :func:`_infer_merge_root`'s guess can be wrong for non-standard
    layouts (``graph.json`` not under ``<root>/graphify-out/``), so every prune
    entry silently no-ops. Each absolute prune path ``P`` that ends with a
    stored RELATIVE source_file ``S`` implies the candidate root
    ``P[:-len(S)-1]``. Within one graph all relative source_files share a single
    scan root, so the candidate is accepted only when it is unique and
    consistent across every suffix-matched entry; on ambiguity (or no suffix
    match at all) returns None and the caller falls through to the zero-match
    warning.
    """
    rel_sfs = [
        sf.replace("\\", "/")
        for sf in stored_sfs
        if sf and isinstance(sf, str) and not _is_abs(sf.replace("\\", "/"))
    ]
    if not rel_sfs:
        return None
    roots: set[str] = set()
    for p in prune_sources:
        if not p or not isinstance(p, str):
            continue
        q = p.replace("\\", "/")
        if not _is_abs(q):
            continue
        hits = {q[: -len(s) - 1] for s in rel_sfs if q.endswith("/" + s)}
        if len(hits) > 1:
            return None  # one entry implies two different roots — ambiguous
        roots |= hits
    if len(roots) == 1:
        return next(iter(roots))
    return None


def edge_data(G: nx.Graph, u: str, v: str) -> dict:
    """Return one edge attribute dict for (u, v), tolerating MultiGraph.

    For MultiGraph/MultiDiGraph there can be multiple parallel edges;
    this returns the first one (sufficient for callers that only need
    relation/confidence for rendering). Fixes #796.
    """
    raw = G[u][v]
    if isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)):
        return next(iter(raw.values()), {})
    return raw


def edge_datas(G: nx.Graph, u: str, v: str) -> list[dict]:
    """Return every edge attribute dict for (u, v); always a list."""
    raw = G[u][v]
    if isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)):
        return list(raw.values())
    return [raw]


def dedupe_nodes(nodes: list[dict]) -> list[dict]:
    """Collapse nodes sharing an ``id``, last-writer-wins on attributes.

    Mirrors what ``build_from_json``'s ``G.add_node`` does implicitly (idempotent;
    a later node overwrites an earlier one's attributes). The ``--no-cluster``
    write path dumps the raw node list without building a graph, so same-id nodes
    — e.g. a Swift ``type=module`` anchor emitted once per importing file (#1327)
    — would otherwise appear as duplicates. Insertion order follows each id's
    first appearance; the retained dict is the last one seen.
    """
    by_id: dict = {}
    for n in nodes:
        nid = n.get("id")
        if nid is None:
            continue
        by_id[nid] = n
    return list(by_id.values())


def dedupe_edges(edges: list[dict]) -> list[dict]:
    """Collapse exact parallel edges by ``(source, target, relation)``, keeping the
    first occurrence.

    The clustered build path runs edges through a NetworkX ``DiGraph``, which
    collapses parallel edges automatically. The ``--no-cluster`` and incremental
    ``update`` write paths bypass NetworkX and concatenate edge lists raw, so
    duplicates accumulate and edge counts become non-deterministic across build
    modes / repeated updates (#1317). Deduping on the connectivity identity is
    zero-signal-loss and restores idempotency. Callers that intentionally keep
    parallel edges (multigraph output) must not use this.
    """
    seen: set[tuple] = set()
    out: list[dict] = []
    for e in edges:
        key = (e.get("source"), e.get("target"), e.get("relation"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _old_file_stems(rel: Path) -> list[str]:
    """Pre-migration stem forms a semantic fragment may have used for ``rel``.

    Ordered longest-first so prefix stripping is greedy and unambiguous:
      - one-parent form: ``parent.stem``  (the old _file_stem rule, #550-era)
      - zero-parent form: ``stem``        (the old llm.py prompt rule, #1509)
    """
    forms: list[str] = []
    parent = rel.parent.name
    if parent and parent not in (".", ""):
        forms.append(make_id(f"{parent}.{rel.stem}"))
    forms.append(make_id(rel.stem))
    # Dedupe while preserving order (top-level files collapse both forms).
    seen: set[str] = set()
    return [f for f in forms if f and not (f in seen or seen.add(f))]


def _semantic_id_remap(nodes: list, root: str | None) -> dict:
    """Re-derive non-AST node ids from ``source_file`` using the canonical
    full-path stem, so a cached/LLM fragment carrying a pre-migration short id
    reconciles with the AST node instead of spawning a ghost (#1504/#1509).

    Drift-proof by construction: the new id is computed from ``source_file`` in
    code, never trusted from the fragment's own ``id`` string. AST-origin nodes
    are skipped (they are already canonical via the extract() post-pass)."""
    from graphify.extractors.base import _file_stem  # local: avoid import cost at module load

    remap: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if _is_ast_tier(node):
            continue
        nid = node.get("id")
        sf = node.get("source_file")
        if not nid or not isinstance(nid, str) or not sf:
            continue
        sf_norm = _norm_source_file(str(sf), root) or str(sf)
        rel = Path(sf_norm)
        if _is_abs(sf_norm):
            # Can't relativize (no/failed root) — leave the id untouched rather
            # than bake an on-disk path into it. Tested for BOTH platforms: a
            # graph built on Linux/CI carries POSIX-absolute source_files that
            # WindowsPath.is_absolute() calls relative, which leaked the whole
            # build directory into node IDs when updated on Windows (#2618).
            continue
        if not rel.name:
            # source_file equals the scan root, so _norm_source_file relativized it
            # to Path('.') — a project-level node with no per-file identity to remap.
            # Leave its id untouched (and avoid _file_stem's empty-name crash, #1618).
            continue
        new_stem = make_id(_file_stem(rel))
        if not new_stem:
            continue
        norm_nid = _normalize_id(nid)
        # Idempotency guard (#1917): an id already carrying its canonical stem is
        # done — do not re-run the legacy branch on it. When the canonical stem
        # contains a shorter legacy stem as a prefix (parent dir name == file
        # stem, e.g. `.claude/CLAUDE.md` -> `claude_claude` over legacy `claude`),
        # an already-migrated id like `claude_claude_x` still matches the legacy
        # `claude_` prefix below and would gain another stem segment on every
        # build, defeating the same_topology/no_change short-circuits. Mirrors the
        # canonical check in graph_has_legacy_ids.
        if norm_nid == new_stem or norm_nid.startswith(new_stem + "_"):
            continue
        new_id: str | None = None
        old_forms = _old_file_stems(rel)
        # #2197: on Windows, detect() can emit an ABSOLUTE source_file, and a
        # semantic fragment's id derived from that absolute path (e.g.
        # d_projects_myrepo_docs_dataflow) matches neither the canonical
        # relative stem nor the legacy short forms above — so while source_file
        # itself is healed by _norm_source_file, the id would ghost against the
        # existing graph's docs_dataflow. When the raw path was absolute and
        # relativized under root, treat the raw-absolute stem as one more
        # old-stem form — the semantic-side twin of extract.py's absolute-form
        # id registration. It is the longest form, so it goes first (greedy
        # prefix stripping, same ordering rule as _old_file_stems).
        sf_raw = str(sf).replace("\\", "/")
        if sf_raw != sf_norm and _is_abs(sf_raw):
            abs_stem = make_id(_file_stem(Path(sf_raw)))
            if abs_stem and abs_stem != new_stem and abs_stem not in old_forms:
                old_forms.insert(0, abs_stem)
        for old_stem in old_forms:
            if old_stem == new_stem:
                continue  # already canonical for this form
            if norm_nid == old_stem:
                new_id = new_stem  # the file node itself
                break
            prefix = old_stem + "_"
            if norm_nid.startswith(prefix):
                entity = norm_nid[len(prefix):]
                new_id = make_id(new_stem, entity)
                break
        if new_id and new_id != nid:
            remap[nid] = new_id
    return remap


# MCP node kinds whose ID is GLOBAL by design — deliberately shared across every
# config file that mentions them (`mcp_command_npx`, `mcp_package_...`,
# `env_var_...`), so it is not derived from ``source_file`` at all (#2408). The
# file-scoped kinds (`mcp_config_file`, `mcp_server`) ARE stem-derived and stay
# subject to legacy detection.
_MCP_GLOBAL_ID_KINDS = frozenset({"mcp_command", "mcp_package", "env_var"})


def _has_global_id(node: dict) -> bool:
    """Whether ``node``'s ID is global by construction rather than file-derived."""
    meta = node.get("metadata")
    if not isinstance(meta, dict):
        return False
    return meta.get("mcp_kind") in _MCP_GLOBAL_ID_KINDS


def graph_has_legacy_ids(nodes: list, root: str | Path | None = None, sample: int = 300) -> bool:
    """Whether a loaded graph still uses pre-#1504 node IDs (parent-dir / filename
    stem) rather than the full repo-relative path. Read-only consumers (query,
    serve) use this to nudge the user to rebuild, since they don't re-extract.

    Heuristic and cheap: only **file-level** nodes (source_location ``L1``) are
    inspected, because their ID is unambiguously the file stem. Symbol nodes are
    skipped — some extractors scope a symbol by package/directory (Go's
    ``_make_id(pkg_dir, name)`` → ``sub_thing``), which can coincide with an old
    file-stem form and would otherwise false-positive. Nodes whose ID is global by
    construction (see ``_MCP_GLOBAL_ID_KINDS``) are skipped for the same reason.
    Returns True as soon as one file node's ID matches an OLD stem form but not the
    canonical full-path form."""
    from graphify.extractors.base import _file_stem
    _r = str(root) if root is not None else None
    checked = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if str(node.get("source_location") or "") != "L1":
            continue  # only file-level nodes carry an unambiguous file-stem ID
        if _has_global_id(node):
            # #2408: MCP ingest stamps every node it emits with line 1 (JSON has no
            # line info), so globally-scoped nodes slip past the L1 proxy for
            # "file-level". For `sub/.mcp.json` the old bare stem is `mcp` while the
            # canonical stem is `sub_mcp`, so a perfectly valid `mcp_command_npx`
            # reads as a legacy `mcp_`-prefixed id and warns on every fresh build.
            # (A root-level `.mcp.json` never tripped it: there `mcp` IS canonical.)
            continue
        nid = node.get("id")
        sf = node.get("source_file")
        if not nid or not isinstance(nid, str) or not sf:
            continue
        sf_norm = _norm_source_file(str(sf), _r) or str(sf)
        rel = Path(sf_norm)
        if _is_abs(sf_norm):
            continue
        if not rel.name:
            continue  # source_file == scan root -> Path('.'), no file stem (#1618)
        new_stem = make_id(_file_stem(rel))
        if not new_stem:
            continue
        norm = _normalize_id(nid)
        if norm == new_stem or norm.startswith(new_stem + "_"):
            checked += 1
        else:
            for old in _old_file_stems(rel):
                if old != new_stem and (norm == old or norm.startswith(old + "_")):
                    return True
            checked += 1
        if checked >= sample:
            break
    return False


def _doc_twin_remap(nodes: list) -> dict[str, str]:
    """Map a markdown quick-scan's bare doc node ``<slug>`` to the semantic
    ``<slug>_doc`` node for the SAME file (#1799).

    The markdown quick-scan (``extract_markdown``) mints a file node with the
    bare id ``_make_id(path)`` while the semantic pass mints ``<slug>_doc`` for
    the same document. A ``graphify update`` after a semantic build leaves both,
    splitting the file's edges across two disconnected nodes. Canonicalize to the
    semantic ``_doc`` node (it carries the richer references/hyperedges). Gated to
    ``file_type == "document"`` on BOTH twins with an identical ``source_file``,
    so an unrelated code symbol ``foo`` and ``foo_doc`` never merge.
    """
    by_id: dict[str, dict] = {}
    for n in nodes:
        if isinstance(n, dict) and n.get("id"):
            by_id[str(n["id"])] = n
    remap: dict[str, str] = {}
    for nid, node in by_id.items():
        if not nid.endswith("_doc"):
            continue
        bare = by_id.get(nid[:-4])
        if bare is None:
            continue
        sf = node.get("source_file")
        if not sf or bare.get("source_file") != sf:
            continue
        if node.get("file_type") != "document" or bare.get("file_type") != "document":
            continue
        remap[nid[:-4]] = nid
    return remap


def build_from_json(extraction: dict, *, directed: bool = False, root: str | Path | None = None) -> nx.Graph:
    """Build a NetworkX graph from an extraction dict.

    directed=True produces a DiGraph that preserves edge direction (source→target).
    directed=False (default) produces an undirected Graph for backward compatibility.
    root: if given, absolute source_file paths from semantic subagents are made
        relative to root so all nodes share a consistent path key (#932).
    """
    from graphify.build_pipeline import (
        preflight_extraction,
        resolve_ghost_nodes,
        assemble_graph_topology,
    )
    import sys

    # 1. 输入防御与模式规整 (Preflight)
    cleaned_extraction, _root = preflight_extraction(extraction, root=root)

    # 2. 初始图骨架填充
    G: nx.Graph = nx.DiGraph() if directed else nx.Graph()
    for node in cleaned_extraction.get("nodes", []):
        if isinstance(node, dict):
            if "id" not in node:
                continue
            try:
                hash(node["id"])
            except TypeError:
                print(
                    f"[graphify] WARNING: skipping node with non-hashable id {node['id']!r} (must be a string).",
                    file=sys.stderr,
                )
                continue
            if "source_file" in node:
                node["source_file"] = _norm_source_file(node["source_file"], _root)
            if "definition_file" in node:
                node["definition_file"] = _norm_source_file(node["definition_file"], _root)
        G.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})

    # 3. 幽灵节点消解 (Ghost Resolver)
    G, ghost_remap, node_set = resolve_ghost_nodes(G)

    # 4. 图拓扑与边关系装配 (Topology Assembler)
    G = assemble_graph_topology(G, cleaned_extraction, ghost_remap, node_set, root=_root)
    return G


def build(
    extractions: list[dict],
    *,
    directed: bool = False,
    dedup: bool = True,
    dedup_llm_backend: str | None = None,
    root: str | Path | None = None,
    protected_ids: "set[str] | None" = None,
) -> nx.Graph:
    """Merge multiple extraction results into one graph.

    directed=True produces a DiGraph that preserves edge direction (source→target).
    directed=False (default) produces an undirected Graph for backward compatibility.
    dedup=True (default) runs entity deduplication before building the graph.
    dedup_llm_backend: if set (e.g. "gemini", "claude", or "kimi"), uses LLM to resolve
        ambiguous pairs in the 75–92 Jaro-Winkler score zone.
    root: if given, absolute source_file paths are made relative to root (#932).
    protected_ids: optional set of node IDs to protect from being collapsed with
        other protected nodes during incremental merge (#3477).

    With dedup disabled, extractions are merged in order and the last node's
    attributes win (NetworkX add_node overwrites). With dedup enabled, nodes
    sharing an ID use a deterministic survivor and retain missing attributes
    from duplicate records of the same source entity. Genuine cross-file ID
    collisions remain isolated and are reported.
    """
    from graphify.dedup import deduplicate_entities
    combined: dict = {"nodes": [], "edges": [], "hyperedges": [], "input_tokens": 0, "output_tokens": 0}
    for ext in extractions:
        combined["nodes"].extend(ext.get("nodes", []))
        combined["edges"].extend(ext.get("edges", []))
        combined["hyperedges"].extend(ext.get("hyperedges", []))
        combined["input_tokens"] += ext.get("input_tokens", 0)
        combined["output_tokens"] += ext.get("output_tokens", 0)
    _root = str(Path(root).resolve()) if root else None
    if dedup and combined["nodes"]:
        # Numeric ids must be str before dedup, which keys on them and would
        # raise TypeError in _pick_winner's regex search (#2326). build_from_json
        # coerces too, but that runs after dedup — too late for this path.
        _coerce_non_string_ids(combined)
        # Fold legacy node field aliases before dedup (#2194): dedup runs BEFORE
        # build_from_json and keys on `label`, so a `name`/`path` alias node
        # would be invisible to it and only label-dedup one build later, after
        # build_from_json's own fold has healed the persisted graph.json.
        for n in combined["nodes"]:
            if isinstance(n, dict):
                _fold_node_aliases(n)
                # Normalize source_file and definition_file to the build root before
                # deduplication (#3472), so exact-ID collision checks and same-file
                # attribute merging operate on canonical repo-relative paths rather
                # than false-flagging absolute paths from semantic subagents as
                # different files.
                if "source_file" in n:
                    n["source_file"] = _norm_source_file(n["source_file"], _root)
                if "definition_file" in n:
                    n["definition_file"] = _norm_source_file(n["definition_file"], _root)
        combined["nodes"], combined["edges"] = deduplicate_entities(
            combined["nodes"], combined["edges"], communities={},
            dedup_llm_backend=dedup_llm_backend, root=_root,
            # Hyperedge members reference node ids too, so they need the same
            # survivor rewiring the edges get (#2805).
            hyperedges=combined.get("hyperedges"),
            protected_ids=protected_ids,
        )
    return build_from_json(combined, directed=directed, root=_root)


def _norm_label(label: str | None) -> str:
    """Canonical dedup key — Unicode-aware, preserves CJK/word characters."""
    if not isinstance(label, str):
        label = "" if label is None else str(label)
    label = unicodedata.normalize("NFKC", label)
    return re.sub(r"[\W_ ]+", " ", label.casefold(), flags=re.UNICODE).strip()


def deduplicate_by_label(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict]]:
    """Merge nodes that share a normalised label, rewriting edge references.

    Prefers IDs without chunk suffixes (_c\\d+) and shorter IDs when tied.
    Drops self-loops created by the merge.

    Dormant: this is NOT wired into ``build()`` — the active dedup path is
    ``deduplicate_entities`` (imported and called in ``build``), which supersedes
    it. The previous "Called in build() automatically" note was never true. It
    also merges by label alone with no ``file_type`` guard, so it must not be
    enabled for code nodes: same-label symbols from different files/packages
    (e.g. two ``Account`` types) would collapse into one — the cross-file
    conflation ``deduplicate_entities`` deliberately avoids for code (#1205).
    """
    _CHUNK_SUFFIX = re.compile(r"_c\d+$")
    canonical: dict[str, dict] = {}  # norm_label -> surviving node
    remap: dict[str, str] = {}       # old_id -> surviving_id

    for node in nodes:
        key = _norm_label(node.get("label", node.get("id", "")))
        if not key:
            continue
        existing = canonical.get(key)
        if existing is None:
            canonical[key] = node
        else:
            has_suffix = bool(_CHUNK_SUFFIX.search(node["id"]))
            existing_has_suffix = bool(_CHUNK_SUFFIX.search(existing["id"]))
            if has_suffix and not existing_has_suffix:
                remap[node["id"]] = existing["id"]
            elif existing_has_suffix and not has_suffix:
                remap[existing["id"]] = node["id"]
                canonical[key] = node
            elif len(node["id"]) < len(existing["id"]):
                remap[existing["id"]] = node["id"]
                canonical[key] = node
            else:
                remap[node["id"]] = existing["id"]

    if not remap:
        return nodes, edges

    print(f"[graphify] Deduplicated {len(remap)} duplicate node(s) by label.", file=sys.stderr)
    deduped_nodes = list(canonical.values())
    deduped_edges = []
    for edge in edges:
        e = dict(edge)
        e["source"] = remap.get(e["source"], e["source"])
        e["target"] = remap.get(e["target"], e["target"])
        if e["source"] != e["target"]:
            deduped_edges.append(e)
    return deduped_nodes, deduped_edges


def _load_existing_graph(graph_path: Path) -> "tuple[list, list, list, bool] | None":
    """Load (nodes, edges, hyperedges, directed) from an existing graph.json for
    an incremental merge, accepting both the ``links`` and ``edges`` spellings.

    Reads the JSON directly instead of going through node_link_graph().
    The latter rebuilds an undirected nx.Graph and then enumerating
    edges() yields endpoints based on node insertion order, which
    silently flips directional edges (e.g. `calls`) when the callee
    was inserted before the caller. The _src/_tgt direction-preserving
    attrs are popped before saving in export.py, so going through the
    NetworkX round-trip loses direction permanently (#760).

    Returns None when the file does not exist. Raises RuntimeError when it
    exists but cannot be parsed — callers must refuse to overwrite rather
    than silently replace a possibly-recoverable graph.
    """
    if not graph_path.exists():
        return None
    from graphify.security import check_graph_file_size_cap
    check_graph_file_size_cap(graph_path)
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(
            f"Cannot read {graph_path} for incremental merge: {exc}. "
            "Delete the file and run a full rebuild."
        ) from exc
    links_key = "links" if "links" in data else "edges"
    nodes = list(data.get("nodes", []))
    edges = list(data.get(links_key, []))
    # Backfill tier provenance on legacy items (#2334): _origin is stamped at
    # extraction time only (extract.py for AST, and the semantic path never
    # stamps), so pre-0.9.16 graphs and externally-merged fragments carry
    # unstamped items. Stamp them via the _is_ast_tier shape fallback so the
    # graph self-heals on the next write and every downstream tier decision
    # (build_merge replace, watch reconcile) reads an explicit marker.
    for item in nodes:
        if isinstance(item, dict):
            item.setdefault("_origin", "ast" if _is_ast_tier(item) else "semantic")
    for item in edges:
        if isinstance(item, dict):
            item.setdefault("_origin", "ast" if _is_ast_tier(item) else "semantic")
    return (
        nodes,
        edges,
        list(data.get("hyperedges", [])),
        bool(data.get("directed", False)),
    )


def _tier_replacement_sources(
    chunks: "Iterable[dict]",
    root: "str | Path | None" = None,
    ast_sources: "Iterable[str | Path] | None" = None,
) -> tuple[set[str], set[str]]:
    """Compute (new_ast_sources, new_sem_sources) for tier-scoped replacement.

    #3411: AST replacement ownership is derived from explicit extraction
    provenance (ast_sources or chunk-level "extracted_sources"), so cross-file
    stub nodes emitted by extractors (e.g. .sln project stubs or ProjectReference
    stubs) do not pollute the replacement set and wipe the target project's
    nodes/edges. Falls back to AST node source_file only when no provenance is
    provided.
    """
    explicit_ast_sources: set[str] = set()
    if ast_sources is not None:
        for s in ast_sources:
            if s:
                explicit_ast_sources.add(str(s))
    for ch in chunks:
        if isinstance(ch, dict):
            for s in (ch.get("extracted_sources") or []):
                if s:
                    explicit_ast_sources.add(str(s))

    new_ast_sources: set[str] = set()
    new_sem_sources: set[str] = set()

    if explicit_ast_sources:
        for sf in explicit_ast_sources:
            new_ast_sources.add(sf)
            norm = _norm_source_file(sf, root)
            if norm:
                new_ast_sources.add(norm)
    else:
        for ch in chunks:
            if not isinstance(ch, dict):
                continue
            for n in ch.get("nodes", []):
                if not isinstance(n, dict):
                    continue
                sf = n.get("source_file")
                if not sf or not _is_ast_tier(n):
                    continue
                new_ast_sources.add(sf)
                norm = _norm_source_file(sf, root)
                if norm:
                    new_ast_sources.add(norm)

    for ch in chunks:
        if not isinstance(ch, dict):
            continue
        for n in ch.get("nodes", []):
            if not isinstance(n, dict):
                continue
            sf = n.get("source_file")
            if not sf or _is_ast_tier(n):
                continue
            new_sem_sources.add(sf)
            norm = _norm_source_file(sf, root)
            if norm:
                new_sem_sources.add(norm)

    return new_ast_sources, new_sem_sources


def merge_raw_extraction(
    new: dict,
    graph_path: str | Path,
    prune_sources: "list[str] | None" = None,
    root: "str | Path | None" = None,
    *,
    ast_sources: "Iterable[str | Path] | None" = None,
) -> dict:
    """Merge the existing raw graph.json forward into a fresh raw extraction
    (the ``extract --no-cluster`` incremental path, #2169).

    Replace/prune semantics mirror :func:`build_merge` exactly, so the raw and
    clustered incremental paths can't drift:

    - sources re-extracted this run REPLACE their prior contribution PER TIER
      (#2333/#2336, #3411): existing nodes/edges/hyperedges owned by them are dropped
      only when the new extraction contains the same tier (AST vs semantic,
      per :func:`_is_ast_tier`) for that source, matched in both raw and
      :func:`_norm_source_file` form (#1007). AST replacement ownership is derived
      from explicit extraction provenance (``ast_sources`` or chunk-level
      ``extracted_sources``), falling back to AST node source_file only when no
      provenance is provided (#3411);
    - ``prune_sources`` (deleted / excluded / graph-stale files) are dropped,
      with the ``_abs_identity`` third-form fallback (#2012), and "replace" wins
      over a contradictory "delete" of a re-extracted source (#1796);
    - everything else — nodes/edges/hyperedges owned by unchanged files — is
      carried forward unchanged.

    Survivors are PREPENDED to ``new``'s lists (existing-first), so the caller's
    ``dedupe_nodes`` last-writer-wins keeps fresh attributes for re-extracted
    nodes while ``dedupe_edges`` first-wins never resurrects a replaced edge
    (replaced sources' edges were already dropped above). Token counters and
    every other key of ``new`` are left untouched. Returns ``new``, mutated in
    place. Raises RuntimeError (via :func:`_load_existing_graph`) when the
    existing graph is present but unparseable — the caller must refuse to
    overwrite it. No-op when ``graph_path`` does not exist.
    """
    graph_path = Path(graph_path)
    loaded = _load_existing_graph(graph_path)
    if loaded is None:
        return new
    existing_nodes, existing_edges, existing_hyperedges, _ = loaded

    _eff_root = (
        str(Path(root).resolve()) if root is not None
        else _infer_merge_root(graph_path)
    )

    # Tier-scoped replace, mirroring build_merge (#2333/#2336, COEXIST, #3411): a
    # source re-extracted this run replaces only the tier(s) actually present
    # in the new extraction, so an AST-only re-extract keeps the file's
    # semantic layer and vice versa. AST replacement ownership is derived from
    # explicit extraction provenance (ast_sources or "extracted_sources"),
    # falling back to AST node source_files only when no provenance is provided.
    new_ast_sources, new_sem_sources = _tier_replacement_sources(
        [new], root=_eff_root, ast_sources=ast_sources
    )
    new_sources: set[str] = new_ast_sources | new_sem_sources

    # "Replace" wins over a contradictory "delete" of the same source (#1796),
    # in both string and absolute-identity space (#2012) — as in build_merge.
    prune_set, prune_abs = _build_prune_sets(prune_sources, _eff_root, new_sources)
    _prune_root = _eff_root

    def _prune_hit(sf: "str | None") -> bool:
        if not sf:
            return False
        if sf in prune_set:
            return True
        norm = _norm_source_file(sf, _prune_root)
        if norm and norm in prune_set:
            return True
        a = _abs_identity(sf, _prune_root)
        return bool(a) and a in prune_abs

    # #2446: when NONE of the prune entries match anything stored, the guessed
    # _eff_root is usually wrong (non-standard layout, no marker) and every
    # prune silently no-ops. Derive the root by suffix-matching the absolute
    # prune paths against the stored relative source_files and retry — same
    # fallback as build_merge.
    if prune_set or prune_abs:
        _stored_sfs = {
            item.get("source_file")
            for seq in (existing_nodes, existing_edges, existing_hyperedges)
            for item in seq if isinstance(item, dict)
        }
        _stored_sfs.discard(None)
        if not any(_prune_hit(sf) for sf in _stored_sfs):
            _derived = _derive_prune_root(prune_sources or [], _stored_sfs)
            if _derived is not None and _derived != _prune_root:
                _prune_root = _derived
                prune_set, prune_abs = _build_prune_sets(
                    prune_sources, _prune_root, new_sources
                )

    def _dropped(item: dict) -> bool:
        if not isinstance(item, dict):
            return True
        sf = item.get("source_file")
        # Tier-scoped replace: an item is superseded only when ITS OWN tier
        # re-extracted its source. Hyperedges are semantic-tier (no _origin,
        # null source_location), so an AST-only re-extract carries them.
        # Deletion pruning below stays tier-blind.
        own = new_ast_sources if _is_ast_tier(item) else new_sem_sources
        if sf in own or _norm_source_file(sf, _eff_root) in own:
            return True  # re-extracted this run — replaced by the new chunk
        if not sf:
            return False  # unowned — carry forward
        return _prune_hit(sf)

    # #3203: Check for unverified semantic shrink on re-extracted sources.
    unverified_semantic_shrink: dict[str, tuple[int, int]] = {}
    if new_sem_sources:
        prior_sem_counts: dict[str, int] = {}
        for n in existing_nodes:
            if isinstance(n, dict) and not _is_ast_tier(n):
                sf = n.get("source_file")
                if sf:
                    canon = _norm_source_file(sf, _eff_root) or sf
                    prior_sem_counts[canon] = prior_sem_counts.get(canon, 0) + 1

        fresh_sem_counts: dict[str, int] = {}
        for n in new.get("nodes", []):
            if isinstance(n, dict) and not _is_ast_tier(n):
                sf = n.get("source_file")
                if sf:
                    canon = _norm_source_file(sf, _eff_root) or sf
                    fresh_sem_counts[canon] = fresh_sem_counts.get(canon, 0) + 1

        for canon_sf, fresh_count in fresh_sem_counts.items():
            prior_count = prior_sem_counts.get(canon_sf, 0)
            if prior_count > 1 and fresh_count < prior_count:
                unverified_semantic_shrink[canon_sf] = (prior_count, fresh_count)

    new["nodes"] = [n for n in existing_nodes if not _dropped(n)] + list(new.get("nodes", []))
    new["edges"] = [e for e in existing_edges if not _dropped(e)] + list(new.get("edges", []))
    carried_hyper = [he for he in existing_hyperedges if not _dropped(he)]
    if carried_hyper or new.get("hyperedges"):
        new["hyperedges"] = carried_hyper + list(new.get("hyperedges", []))
    if unverified_semantic_shrink:
        new["_unverified_semantic_shrink"] = unverified_semantic_shrink
    return new


def build_merge(
    new_chunks: list[dict],
    graph_path: str | Path | None = None,
    prune_sources: list[str] | None = None,
    *,
    directed: bool | None = None,
    dedup: bool = True,
    dedup_llm_backend: str | None = None,
    root: str | Path | None = None,
    ast_sources: "Iterable[str | Path] | None" = None,
) -> nx.Graph:
    """Load existing graph.json and return it merged with ``new_chunks``.

    Does NOT write to disk — the caller persists the result, e.g. via
    ``export.to_json(G, communities, graph_path, force=True)`` after
    clustering. ``graph_path`` is read-only here.

    Re-extracted files REPLACE their prior contribution per tier (#2333/#2336, #3411):
    a source_file present in new_chunks has its existing nodes/edges dropped
    for each tier (AST vs semantic, per :func:`_is_ast_tier`) the new chunks
    actually contain, so a changed file's stale nodes/edges don't accumulate
    while a one-tier re-extract keeps the other tier's layer intact. AST replacement
    ownership is derived from explicit extraction provenance (``ast_sources`` or
    chunk-level ``extracted_sources``), falling back to AST node source_file only
    when no provenance is provided (#3411). Files absent from new_chunks are
    preserved unchanged; deleted files are removed via prune_sources (tier-blind).
    Safe to call repeatedly.
    root: if given, absolute source_file paths in new_chunks are made relative (#932).
    directed: if None (default), honor the on-disk graph's own ``directed`` flag
    when one exists, so an incremental merge can't silently flip a directed
    graph undirected (#2342). Falls back to False when there is no existing
    graph to inherit from. An explicit True/False always overrides the on-disk
    flag.
    """
    # Iterated more than once below (source sets, the hyperedge carry, the
    # build itself), so a one-shot iterator must be materialised first.
    new_chunks = list(new_chunks)
    graph_path = Path(graph_path if graph_path is not None else _default_graph_json())
    _loaded = _load_existing_graph(graph_path)
    if _loaded is not None:
        existing_nodes, existing_edges, existing_hyperedges, existing_directed = _loaded
        had_graph = True
    else:
        existing_nodes = []
        existing_edges = []
        existing_hyperedges = []
        existing_directed = False
        had_graph = False
    if directed is None:
        directed = existing_directed if had_graph else False

    # Effective root for relativizing absolute source_file / prune paths back to the
    # stored relative source_file keys. When the caller passes root we use it;
    # otherwise fall back to the graph's recorded scan root, so absolute
    # prune_sources and new-chunk paths still match even when a caller omits root
    # (#1571 — the skill's --update runbook calls build_merge without root, so
    # absolute deleted-file paths never matched the relative node keys and their
    # nodes survived as ghosts).
    _eff_root = (
        str(Path(root).resolve()) if root is not None
        else _infer_merge_root(graph_path)
    )

    # Re-extracted files REPLACE their prior contribution. Every source_file
    # present in new_chunks is dropped from the loaded base before merging, so a
    # CHANGED file's stale nodes/edges don't accumulate across incremental
    # updates. Without this, build() merges old+new for the same file and only
    # exact-duplicate edges collapse — edges/nodes that disappeared from the new
    # version survive forever. Brand-new files aren't in base, so this is a no-op
    # for them; genuinely deleted files are still handled via prune_sources.
    # Matched in both raw and _norm_source_file form because new_chunks may carry
    # absolute win32 paths while the stored graph keeps relative posix (#1007).
    # Replacement is tier-scoped (#2333/#2336, COEXIST): each file has two
    # producers — the deterministic AST pass and the semantic/LLM pass — whose
    # node sets coexist in the graph. A re-extract of one tier must replace
    # only that tier's prior contribution, never the other's (a semantic-only
    # chunk used to delete the file's AST headings). Which tier a NEW chunk
    # item belongs to is read via _is_ast_tier (existing items were stamped by
    # _load_existing_graph above).
    #
    # #3411: AST replacement ownership is derived from explicit extraction
    # provenance (ast_sources or chunk-level "extracted_sources"), so cross-file
    # stub nodes emitted by extractors (e.g. .sln project stubs or ProjectReference
    # stubs) do not pollute the replacement set and wipe the target project's
    # nodes/edges. Falls back to AST node source_file only when no provenance is
    # provided.
    _replace_root = _eff_root
    new_ast_sources, new_sem_sources = _tier_replacement_sources(
        new_chunks, root=_replace_root, ast_sources=ast_sources
    )
    new_sources: set[str] = new_ast_sources | new_sem_sources
    # True on-disk baseline for the #479 shrink accounting at the end (#2497):
    # the rebind below removes the re-extracted sources' old nodes from
    # existing_nodes, so any later size comparison against the rebound list can
    # never see the loss it is meant to catch.
    _disk_nodes = existing_nodes
    _disk_n = len(existing_nodes)

    # #3203: Check for unverified semantic shrink on re-extracted sources.
    # An existing source with prior semantic nodes (> 1) that produces strictly
    # fewer semantic nodes in this extraction is flagged on G.graph so the CLI
    # can arm the shrink guard and leave the source unstamped in the manifest.
    unverified_semantic_shrink: dict[str, tuple[int, int]] = {}
    if had_graph and new_sem_sources:
        prior_sem_counts: dict[str, int] = {}
        for n in _disk_nodes:
            if isinstance(n, dict) and not _is_ast_tier(n):
                sf = n.get("source_file")
                if sf:
                    canon = _norm_source_file(sf, _replace_root) or sf
                    prior_sem_counts[canon] = prior_sem_counts.get(canon, 0) + 1

        fresh_sem_counts: dict[str, int] = {}
        for ch in new_chunks:
            for n in ch.get("nodes", []):
                if isinstance(n, dict) and not _is_ast_tier(n):
                    sf = n.get("source_file")
                    if sf:
                        canon = _norm_source_file(sf, _replace_root) or sf
                        fresh_sem_counts[canon] = fresh_sem_counts.get(canon, 0) + 1

        for canon_sf, fresh_count in fresh_sem_counts.items():
            prior_count = prior_sem_counts.get(canon_sf, 0)
            if prior_count > 1 and fresh_count < prior_count:
                unverified_semantic_shrink[canon_sf] = (prior_count, fresh_count)

    if new_sources:
        def _kept(item: dict) -> bool:
            sf = item.get("source_file")
            own = new_ast_sources if _is_ast_tier(item) else new_sem_sources
            return sf not in own and _norm_source_file(sf, _replace_root) not in own
        existing_nodes = [n for n in existing_nodes if _kept(n)]
        existing_edges = [e for e in existing_edges if _kept(e)]
        replaced_n = _disk_n - len(existing_nodes)
        if replaced_n:
            print(
                f"[graphify] Replaced {replaced_n} node(s) from re-extracted "
                f"source file(s).",
                file=sys.stderr,
            )

    # Prune set for deleted source files — both the raw form (matches nodes that
    # kept absolute source_file) and the normalised relative form (matches nodes
    # relativised by _norm_source_file at build time). .resolve() (via _eff_root)
    # handles symlinked roots and ".." / "./" segments so Path.relative_to()
    # succeeds even when the scan root is a symlink. (#1007, #1571)
    #
    # A file that was just re-extracted (present in new_chunks) is being REPLACED,
    # never deleted — so never prune it, even if the caller also lists it in
    # prune_sources. Otherwise its fresh, just-built nodes are silently removed
    # (data loss): common when an edit keeps a node's label and the caller follows
    # the old edit-workflow of passing the changed file in prune_sources (#1796).
    # "replace" wins over a contradictory "delete" of the same source. Applied in
    # both string and absolute-identity space so the third-form fallback below
    # can't resurrect the delete for a re-extracted file (#2012).
    _prune_root = _eff_root
    prune_set, prune_abs = _build_prune_sets(prune_sources, _prune_root, new_sources)
    _matched_prune_entries: set[str] = set()

    def _prune_match(sf: "str | None") -> bool:
        # Match a node/edge/hyperedge source_file against the prune set in a
        # form-insensitive way: exact string, normalised-relative, then the
        # absolute-identity fallback for the third-form case (#2012). Records
        # WHICH prune entry matched, so the prune report can count only the
        # entries that actually hit something (#2446).
        if not sf:
            return False
        hit = prune_set.get(sf)
        if hit is None:
            norm = _norm_source_file(sf, _prune_root)
            if norm:
                hit = prune_set.get(norm)
        if hit is None:
            a = _abs_identity(sf, _prune_root)
            if a:
                hit = prune_abs.get(a)
        if hit is None:
            return False
        _matched_prune_entries.add(hit)
        return True

    # #2446: when NONE of the prune entries match anything stored, the guessed
    # _eff_root is usually wrong (non-standard layout, no marker) and every
    # prune would silently no-op. Derive the root by suffix-matching the
    # absolute prune paths against the stored relative source_files and redo
    # the prune sets with it; on ambiguity fall through to the zero-match
    # warning below. Runs before the hyperedge carry so hyperedge pruning
    # benefits too.
    if prune_set or prune_abs:
        _stored_sfs = {
            item.get("source_file")
            for seq in (_disk_nodes, existing_edges, existing_hyperedges)
            for item in seq if isinstance(item, dict)
        }
        _stored_sfs.discard(None)
        if not any(_prune_match(sf) for sf in _stored_sfs):
            _derived = _derive_prune_root(prune_sources or [], _stored_sfs)
            if _derived is not None and _derived != _prune_root:
                _prune_root = _derived
                prune_set, prune_abs = _build_prune_sets(
                    prune_sources, _prune_root, new_sources
                )

    # Carry forward hyperedges from files that were neither re-extracted nor
    # deleted (#1574). build() only sees the new chunks' hyperedges, so without
    # this every --update collapses the graph's hyperedge set down to just the
    # changed files'. Re-extracted files' prior hyperedges are dropped (their new
    # version is already in the new chunks — replace-per-source, like
    # nodes/edges); deleted files' are dropped via prune_set; id-dedup so a
    # carried hyperedge never duplicates one the new chunks re-emitted. Mirrors
    # watch.py, which already preserves existing hyperedges across a rebuild.
    #
    # The carried set rides INTO build() on the base chunk rather than being
    # attached to G afterwards (#3102): entity dedup rewires every edge endpoint
    # and every hyperedge member it sees onto the survivor (#2805), but a
    # hyperedge attached after the fact kept naming the merged-away node — a
    # dangling member with no backing node in the written graph.
    carried_hyperedges: list[dict] = []
    if existing_hyperedges:
        carried = carried_hyperedges
        _new_hyperedge_ids = {
            he.get("id")
            for chunk in new_chunks
            for he in (chunk.get("hyperedges") or [])
            if isinstance(he, dict) and he.get("id")
        }
        for he in existing_hyperedges:
            if not isinstance(he, dict):
                continue
            sf = he.get("source_file")
            norm = _norm_source_file(sf, _eff_root)
            # Hyperedges are semantic-tier: only a SEMANTIC re-extract of the
            # source replaces them. An AST-only re-extract cannot regenerate
            # hyperedges, so dropping them there would be data loss (#2336).
            if sf in new_sem_sources or norm in new_sem_sources:
                continue  # semantically re-extracted — replaced by the new chunk's version
            if _prune_match(sf):
                continue  # deleted — pruned
            if he.get("id") and he.get("id") in _new_hyperedge_ids:
                continue  # the new chunks re-emitted it — theirs wins
            carried.append(he)

    # Remove replaced deleted-source records before entity dedup can choose their stale
    # provenance over a freshly emitted node with the same ID. A Terraform
    # directory anchor, for example, survives deletion of its first .tf file
    # with a new source_file; pruning only AFTER build would delete the live
    # anchor too if dedup selected the old record.
    if prune_sources:
        fresh_ids = {n.get("id") for chunk in new_chunks for n in chunk.get("nodes", [])}
        existing_nodes = [
            n for n in existing_nodes
            if not (n.get("id") in fresh_ids and _prune_match(n.get("source_file")))
        ]
        # Other deleted records and edges stay until the normal prune below:
        # it needs their connectivity to identify newly orphaned import stubs.

    base = (
        [{"nodes": existing_nodes, "edges": existing_edges, "hyperedges": carried_hyperedges}]
        if had_graph else []
    )

    # Untouched existing nodes must not be collapsed with each other during dedup (#3477).
    _protected_ids = {
        n["id"] for n in existing_nodes
        if isinstance(n, dict) and n.get("id")
    } if had_graph else None

    all_chunks = base + list(new_chunks)
    G = build(
        all_chunks,
        directed=directed,
        dedup=dedup,
        dedup_llm_backend=dedup_llm_backend,
        root=_eff_root,
        protected_ids=_protected_ids,
    )

    # Prune nodes and edges from deleted source files
    if prune_sources:
        # Source-less nodes that are ALREADY isolated before this prune. They are
        # not this prune's doing, so they must survive it — the sweep below is
        # scoped to the ones it orphans itself.
        _isolated_before = {
            n for n, d in G.nodes(data=True)
            if not d.get("source_file") and G.degree(n) == 0
        }
        to_remove = [
            n for n, d in G.nodes(data=True)
            if _prune_match(d.get("source_file"))
        ]
        G.remove_nodes_from(to_remove)
        n_nodes = len(to_remove)

        edges_to_remove = [
            (u, v) for u, v, d in G.edges(data=True)
            if _prune_match(d.get("source_file"))
        ]
        if edges_to_remove:
            G.remove_edges_from(edges_to_remove)

        # Extractors create a per-file node for each IMPORTED EXTERNAL symbol
        # (`Path` from pathlib, `Counter` from collections), and those carry no
        # source_file because they are defined outside the corpus. Every edge
        # they have points at symbols in the one file they were created for, so
        # pruning that file leaves them at degree 0 — named after a file the
        # corpus no longer contains, counted in every total that reads the graph,
        # exported as a note of their own, and unreachable by any future prune
        # since there is no source_file to match on. Nothing else can collect
        # them: deletions go through deleted_files, exclusions through
        # excluded_files (#1908) and _stale_graph_sources (#1909), and all three
        # match on source_file. A node with neither a source_file nor an edge
        # names nothing and connects nothing, so dropping it loses no
        # information (#2807).
        #
        # A single pass suffices: external-import stubs are only ever edge
        # TARGETS (extractors mint them as the target of an imports_from/
        # references/inherits edge, never as a source), so removing one can
        # never drop another to degree 0. A future extractor emitting a
        # stub->stub edge would require iterating this to a fixpoint.
        orphaned = [
            n for n, d in G.nodes(data=True)
            if not d.get("source_file")
            and G.degree(n) == 0
            and n not in _isolated_before
        ]
        if orphaned:
            G.remove_nodes_from(orphaned)
            n_nodes += len(orphaned)

        # Report only the prune entries that ACTUALLY matched something — not
        # len(prune_sources), which counted every entry as pruned-from even
        # when a root mismatch made most of them no-ops (#2446).
        n_files = len(_matched_prune_entries)
        if n_nodes:
            print(
                f"[graphify] Pruned {n_nodes} node(s) from {n_files} deleted or "
                f"excluded source file(s).",
                file=sys.stderr,
            )
        if edges_to_remove:
            print(
                f"[graphify] Pruned {len(edges_to_remove)} edge(s) from deleted or "
                f"excluded source file(s).",
                file=sys.stderr,
            )

        if not n_nodes and not edges_to_remove:
            if (prune_set or prune_abs) and not _matched_prune_entries:
                # Live prune entries that matched NOTHING usually mean the
                # effective root is wrong (and the derived-root fallback above
                # found no consistent candidate) — warn instead of claiming the
                # graph is "already clean" (#2446).
                _p0 = next((p for p in prune_sources if p), None)
                sample_prune = _norm_source_file(_p0, _prune_root) or _p0
                sample_sf = next(
                    iter(sorted(
                        str(d.get("source_file"))
                        for _, d in G.nodes(data=True) if d.get("source_file")
                    )),
                    None,
                )
                print(
                    f"[graphify] WARNING: {len(prune_sources)} prune source(s) "
                    f"matched no nodes or edges — nothing was removed. Prune "
                    f"entry {sample_prune!r} does not correspond to any stored "
                    f"source_file (e.g. {sample_sf!r}). If these files should "
                    f"have been pruned, pass root= to build_merge so absolute "
                    f"paths relativize to the graph's source_file keys. (#2446)",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[graphify] {len(prune_sources)} source file(s) deleted or "
                    f"excluded since last run — no matching nodes or edges in "
                    f"graph, already clean.",
                    file=sys.stderr,
                )

    # Safety check: refuse to SILENTLY drop nodes (#479, reworked in #2497).
    # The old count comparison ran against the post-replace `existing_nodes`,
    # which had already lost the re-extracted sources' old nodes — so it could
    # never fire when it mattered, and was skipped outright whenever
    # prune_sources was passed. Mirror watch._check_shrink instead: diff the
    # on-disk baseline by node identity and excuse only losses explained by
    # this run's own re-extraction (same tier) or an explicit prune. Skipped
    # under dedup, where fuzzy merging collapses ids legitimately.
    #
    # Residual tradeoff (accepted): a partial re-extraction that under-produces
    # for ITS OWN file (>= 1 node still present in new_chunks) is excused here —
    # that failure mode is owned by the extraction layer's incomplete-build
    # guard (#1951), and refusing it here would reintroduce the #1116
    # false-refuse for legitimate edits that remove symbols from a file.
    if had_graph and not dedup:
        def _in_new_graph(n: dict) -> bool:
            nid = n.get("id")
            if nid is None or not _hashable(nid):
                return True  # untrackable identity — never count as lost
            if nid in G:
                return True
            # Doc-twin heal (#1799): build_from_json merges a markdown
            # quick-scan's bare doc node into its semantic `<id>_doc` twin for
            # the same file — a legitimate collapse, not a loss.
            return (
                isinstance(nid, str)
                and not nid.endswith("_doc")
                and n.get("file_type") == "document"
                and f"{nid}_doc" in G
                and G.nodes[f"{nid}_doc"].get("source_file") == n.get("source_file")
            )

        lost = [
            n for n in _disk_nodes
            if isinstance(n, dict) and not _in_new_graph(n)
        ]

        def _explained(n: dict) -> bool:
            sf = n.get("source_file")
            if not sf:
                return True
            own = new_ast_sources if _is_ast_tier(n) else new_sem_sources
            if sf in own or _norm_source_file(sf, _replace_root) in own:
                return True  # replaced by this run's re-extract (same tier)
            return _prune_match(sf)  # deliberately pruned this run

        unexplained = [n for n in lost if not _explained(n)]
        if unexplained:
            raise ValueError(
                f"graphify: build_merge would drop {len(unexplained)} node(s) "
                f"from sources that were neither re-extracted nor pruned this "
                f"run (e.g. {unexplained[0].get('id')!r}); graph would go "
                f"{_disk_n} → {G.number_of_nodes()} nodes. "
                f"Pass prune_sources explicitly if you intend to remove them. (#479)"
            )

    if unverified_semantic_shrink:
        G.graph["_unverified_semantic_shrink"] = unverified_semantic_shrink

    return G


def prefix_graph_for_global(
    G: nx.Graph, repo_tag: str, community_offset: int = 0
) -> nx.Graph:
    """Return a copy of G with all node IDs prefixed with repo_tag::.

    Labels are preserved unchanged (for display). A 'local_id' attribute
    is added to each node so the original ID can be recovered. Edges and
    their directional attributes (_src/_tgt) are rewritten to match the new
    prefixed IDs. The 'repo' attribute is set on every node.

    community_offset shifts each node's integer 'community' id into a shared
    id space and records the original in 'local_community': every input graph
    numbers its communities from 0, so ids carried across a merge unchanged
    collide and the aggregated community view fuses unrelated communities
    into one meta-node (#3014). 0 (the default) leaves communities untouched.
    """
    # External stubs (stdlib / third-party modules, #2873) are GLOBAL
    # identifiers, not repo-local: leaving their id unprefixed lets the same
    # module unify into one node across repos instead of fragmenting into
    # repoA::typing / repoB::typing, which is exactly the "which repos depend on
    # X" question a cross-repo merge exists to answer.
    relabel = {
        n: f"{repo_tag}::{n}"
        for n, d in G.nodes(data=True)
        if not d.get("external")
    }
    H = nx.relabel_nodes(G, relabel, copy=True)
    for node, data in H.nodes(data=True):
        if data.get("external"):
            continue  # global id, belongs to no single repo — no repo/local_id tag
        data["repo"] = repo_tag
        data.setdefault("local_id", node.split("::", 1)[1])
        cid = data.get("community")
        if community_offset and isinstance(cid, int):
            data["local_community"] = cid
            data["community"] = cid + community_offset
    for u, v, data in H.edges(data=True):
        if "_src" in data and data["_src"] in relabel:
            data["_src"] = relabel[data["_src"]]
        if "_tgt" in data and data["_tgt"] in relabel:
            data["_tgt"] = relabel[data["_tgt"]]
    # Out-of-band hyperedges must be relabeled with the nodes (#2484, after
    # @oleksii-tumanov's diagnosis in PR #1691): relabel_nodes copies graph
    # attrs by reference, so member ids kept their pre-prefix form and dangled
    # after a cross-repo merge. Rebuild the list (fresh dicts — the input
    # graph's list is shared with H) with member ids mapped through the same
    # relabel table, and prefix the hyperedge id itself so same-named
    # hyperedges from different repos cannot collide when merged.
    hyperedges = H.graph.get("hyperedges")
    if isinstance(hyperedges, list):
        rewritten = []
        for he in hyperedges:
            if isinstance(he, dict):
                he = dict(he)
                if isinstance(he.get("nodes"), list):
                    he["nodes"] = [
                        relabel.get(m, m) if _hashable(m) else m
                        for m in he["nodes"]
                    ]
                if he.get("id"):
                    he["id"] = f"{repo_tag}::{he['id']}"
            rewritten.append(he)
        H.graph["hyperedges"] = rewritten
    return H


def distinct_repo_tags(graph_paths: "list[Path]") -> "list[str]":
    """Return a unique, human-meaningful repo tag per input graph for merge-graphs.

    The naive tag (the ``graphify-out`` parent dir name) is NOT unique across
    inputs: ``src/graphify-out`` and ``frontend/src/graphify-out`` both yield
    ``src``. Prefixing both node sets with ``src::`` then makes same-stem nodes
    (a backend ``src/app.js`` and a frontend ``App.jsx``, both bare ``app``)
    collide, so ``nx.compose`` silently merges two unrelated entities and invents
    cross-runtime edges (#1729). Colliding tags are widened with their own parent
    dir (``frontend_src``), then an index suffix guarantees uniqueness so no two
    graphs ever share a prefix.
    """
    repo_dirs = [p.parent.parent for p in graph_paths]  # graphify-out/.. → repo dir
    tags = [d.name or "repo" for d in repo_dirs]
    if len(set(tags)) != len(tags):
        widened: list[str] = []
        for d in repo_dirs:
            parent = d.parent.name
            widened.append(f"{parent}_{d.name}" if parent and d.name else (d.name or "repo"))
        tags = widened
    seen: dict[str, int] = {}
    unique: list[str] = []
    for t in tags:
        seen[t] = seen.get(t, 0) + 1
        unique.append(t if seen[t] == 1 else f"{t}-{seen[t]}")
    return unique


def prune_repo_from_graph(G: nx.Graph, repo_tag: str) -> int:
    """Remove all nodes tagged with repo_tag from G in-place. Returns count removed."""
    to_remove = [n for n, d in G.nodes(data=True) if d.get("repo") == repo_tag]
    G.remove_nodes_from(to_remove)
    return len(to_remove)
