"""LLM-backed community naming for standalone CLI runs (issue #1097).

When graphify runs inside an orchestrating agent (Claude Code / Gemini CLI), the
agent names communities itself per skill.md Step 5 - it reads the analysis file
and writes 2-5 word names with its own reasoning, no API call. When graphify is
run as a bare CLI (``python -m graphify extract . --backend X``), there is no
agent to do that step, so community labels stay ``Community 0/1/2...``.

This module fills that gap: given the graph and its communities, it asks the
configured backend to name them in ONE batched call, then returns a complete
``{cid: name}`` map (placeholders for anything the backend didn't name).
"""
from __future__ import annotations

import json
import re
import sys

import networkx as nx

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_MAX_COMMUNITIES = 200   # cap LLM-named communities; tail stays placeholder
_TOP_K = 12              # node labels sampled per community for the prompt
_LABEL_MAXLEN = 60       # truncate individual labels to keep the prompt small


def _placeholder_labels(communities) -> dict[int, str]:
    return {int(cid): f"Community {cid}" for cid in communities}


def _community_label_lines(
    G: nx.Graph, communities: dict, gods, max_communities: int, top_k: int
) -> tuple[list[str], list[int]]:
    """Build one prompt line per community (largest first), sampling up to
    ``top_k`` representative node labels (god nodes first). Returns the lines and
    the list of cids that actually got a line (skips empty communities)."""
    # gods may be node-id strings or god_nodes() dicts ({"id": ..., "label": ...}).
    god_set = {g["id"] if isinstance(g, dict) else g for g in (gods or [])}
    ordered = sorted(communities.items(), key=lambda kv: -len(kv[1]))
    lines: list[str] = []
    labeled_cids: list[int] = []
    for cid, members in ordered[:max_communities]:
        ranked = [m for m in members if m in god_set] + [m for m in members if m not in god_set]
        names: list[str] = []
        seen: set[str] = set()
        for nid in ranked:
            label = str(G.nodes[nid].get("label", nid)) if nid in G.nodes else str(nid)
            label = label.strip().strip("()")[:_LABEL_MAXLEN]
            if label and label.lower() not in seen:
                seen.add(label.lower())
                names.append(label)
            if len(names) >= top_k:
                break
        if names:
            lines.append(f"Community {cid}: {', '.join(names)}")
            labeled_cids.append(int(cid))
    return lines, labeled_cids


def _parse_label_response(text: str, labeled_cids: list[int]) -> dict[int, str]:
    """Parse the backend's JSON ``{cid: name}`` reply. Raises on non-JSON or a
    non-object payload; silently ignores cids it didn't name (caller fills those
    with placeholders)."""
    cleaned = _FENCE_RE.sub("", text.strip())
    # If the model wrapped the object in prose, grab the outermost {...}.
    if not cleaned.startswith("{"):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start:end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("label response is not a JSON object")
    out: dict[int, str] = {}
    for cid in labeled_cids:
        name = data.get(str(cid))
        if name is None:
            name = data.get(cid)
        if isinstance(name, str) and name.strip():
            out[cid] = name.strip()
    return out


def label_communities(
    G: nx.Graph,
    communities: dict,
    *,
    backend: str,
    gods=None,
    max_communities: int = _MAX_COMMUNITIES,
    top_k: int = _TOP_K,
) -> dict[int, str]:
    """Return a complete ``{cid: name}`` map using ``backend`` for naming.

    Placeholders (``Community N``) are used for any community the backend did not
    name (empty community, beyond ``max_communities``, or absent from the reply).
    Raises on backend/parse failure - callers that want graceful degradation
    should use :func:`generate_community_labels`.
    """
    labels = _placeholder_labels(communities)
    lines, labeled_cids = _community_label_lines(G, communities, gods, max_communities, top_k)
    if not lines:
        return labels

    prompt = (
        "You are naming clusters in a knowledge graph. For each community below, "
        "return a concise 2-5 word plain-language name describing what it is about "
        "(e.g. \"Order Management\", \"Payment Flow\", \"Auth Middleware\"). "
        "Respond ONLY with a JSON object mapping the community id (as a string) to "
        "its name - no prose, no markdown fences.\n\n" + "\n".join(lines)
    )

    from graphify.llm import _call_llm

    max_tokens = min(40 + 16 * len(labeled_cids), 4096)
    text = _call_llm(prompt, backend=backend, max_tokens=max_tokens)
    labels.update(_parse_label_response(text, labeled_cids))
    return labels


def generate_community_labels(
    G: nx.Graph,
    communities: dict,
    *,
    backend: str | None = None,
    gods=None,
    quiet: bool = False,
) -> tuple[dict[int, str], str]:
    """CLI entry point: resolve a backend, name communities, and degrade to
    ``Community N`` placeholders on any failure (no backend, API error, malformed
    reply). Returns ``(labels, source)`` where source is ``"llm"`` or
    ``"placeholder"``. Never raises."""
    if backend is None:
        try:
            from graphify.llm import detect_backend
            backend = detect_backend()
        except Exception:
            backend = None
    if not backend:
        if not quiet:
            print(
                "[graphify label] no LLM backend configured; keeping Community N "
                "placeholders. Set an API key (e.g. GOOGLE_API_KEY) or pass --backend.",
                file=sys.stderr,
            )
        return _placeholder_labels(communities), "placeholder"
    try:
        labels = label_communities(G, communities, backend=backend, gods=gods)
        return labels, "llm"
    except Exception as exc:
        if not quiet:
            print(
                f"[graphify label] warning: community labeling failed ({exc}); "
                "using Community N placeholders.",
                file=sys.stderr,
            )
        return _placeholder_labels(communities), "placeholder"
