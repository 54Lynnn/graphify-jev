"""
Graphify-Jev 核心构建管线解耦管道 (Build Pipeline)
将庞杂的 build_from_json 职责拆解为三个职责单一的高内聚组件：
1. ExtractionPreflight: 输入预检、schema规范化与双胞胎文档消解
2. GhostNodeResolver: AST与LLM幽灵孪生节点多轮消解
3. GraphAssembler: 纯净 NetworkX 图拓扑装配与边重定向
"""
from __future__ import annotations
import math
import re
import sys
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple
import networkx as nx

from graphify.validate import validate_extraction
from graphify.ids import make_id
from graphify.build import edge_data


def preflight_extraction(extraction: dict, root: str | Path | None = None) -> tuple[dict, str | None]:
    """
    第一阶段：输入防御、Schema 规整与双胞胎文档合并。
    """
    from graphify.build import (
        _coerce_non_string_ids,
        _fold_node_aliases,
        _FILE_TYPE_SYNONYMS,
        _normalize_hyperedge_members,
        _fold_edge_aliases,
        _semantic_id_remap,
        _hashable,
        _doc_twin_remap,
    )

    _root = str(Path(root).resolve()) if root else None

    # NetworkX <= 3.1 兼容：links -> edges
    if "edges" not in extraction and "links" in extraction:
        extraction = dict(extraction, edges=extraction["links"])

    # Hyperedges 槽位收敛
    if "hyperedges" not in extraction and isinstance(
        (extraction.get("graph") or {}).get("hyperedges"), list
    ):
        extraction = dict(extraction, hyperedges=extraction["graph"]["hyperedges"])

    # 非字符串 ID 转换
    _coerce_non_string_ids(extraction)

    # 规范化节点
    for node in extraction.get("nodes", []):
        if not isinstance(node, dict):
            continue
        if "source" in node and "source_file" not in node:
            node_id = node.get("id", "?")
            affected_edges = sum(
                1 for e in extraction.get("edges", [])
                if e.get("source") == node_id or e.get("target") == node_id
            )
            print(
                f"[graphify] WARNING: node '{node_id}' uses field 'source' instead of 'source_file' — {affected_edges} edge(s) may be misrouted.",
                file=sys.stderr,
            )
            node["source_file"] = node.pop("source")
        _fold_node_aliases(node)
        if node.get("file_type") in (None, ""):
            node["file_type"] = "concept"
        ft = node.get("file_type", "")
        if ft and ft not in {"code", "document", "paper", "image", "rationale", "concept"}:
            node["file_type"] = _FILE_TYPE_SYNONYMS.get(ft, "concept")

    # 规范化 hyperedges
    for he in extraction.get("hyperedges", []) or []:
        _normalize_hyperedge_members(he)

    # 规范化 edges
    for edge in extraction.get("edges", []):
        if isinstance(edge, dict):
            _fold_edge_aliases(edge)

    # 验证
    errors = validate_extraction(extraction)
    real_errors = [e for e in errors if "does not match any node id" not in e]
    if real_errors:
        by_cause: dict[str, list[str]] = {}
        for err in real_errors:
            m = re.search(r"missing required field '[^']*'", err)
            by_cause.setdefault(m.group(0) if m else "other schema issue", []).append(err)
        breakdown = "; ".join(
            f"{len(errs)}x {cause} (e.g. {errs[0]})" for cause, errs in by_cause.items()
        )
        print(f"[graphify] Extraction warning ({len(real_errors)} issues): {breakdown}", file=sys.stderr)

    # 确定性语义重映射
    _rekey = _semantic_id_remap(extraction.get("nodes", []), _root)
    if _rekey:
        for node in extraction.get("nodes", []):
            if isinstance(node, dict) and node.get("id") in _rekey:
                node["id"] = _rekey[node["id"]]
        for edge in extraction.get("edges", []):
            if isinstance(edge, dict):
                if edge.get("source") in _rekey:
                    edge["source"] = _rekey[edge["source"]]
                if edge.get("target") in _rekey:
                    edge["target"] = _rekey[edge["target"]]
        for he in extraction.get("hyperedges", []) or []:
            if isinstance(he, dict) and isinstance(he.get("nodes"), list):
                he["nodes"] = [_rekey.get(n, n) if _hashable(n) else n for n in he["nodes"]]

    # 合并双胞胎文档节点
    _doc_remap = _doc_twin_remap(extraction.get("nodes", []))
    if _doc_remap:
        extraction["nodes"] = [
            n for n in extraction.get("nodes", [])
            if not (isinstance(n, dict) and n.get("id") in _doc_remap)
        ]
        _new_edges = []
        for edge in extraction.get("edges", []):
            if isinstance(edge, dict):
                s0, t0 = edge.get("source"), edge.get("target")
                if s0 in _doc_remap:
                    edge["source"] = _doc_remap[s0]
                if t0 in _doc_remap:
                    edge["target"] = _doc_remap[t0]
                if edge.get("source") == edge.get("target") and (s0 in _doc_remap or t0 in _doc_remap):
                    continue
            _new_edges.append(edge)
        extraction["edges"] = _new_edges
        for he in extraction.get("hyperedges", []) or []:
            if isinstance(he, dict) and isinstance(he.get("nodes"), list):
                he["nodes"] = [_doc_remap.get(n, n) if _hashable(n) else n for n in he["nodes"]]

    return extraction, _root


def resolve_ghost_nodes(G: nx.Graph) -> tuple[nx.Graph, dict[str, str], set[str]]:
    """
    第二阶段：AST 与 LLM 幽灵孪生节点多轮消解 (Pass 1 / Pass 2 / Pass 2b)。
    返回 (处理后的图 G, ghost_remap 字典, node_set 集合)。
    """
    from graphify.build import _is_file_node_label

    node_set = set(G.nodes())
    _loc_nodes: dict[tuple[str, str], str] = {}
    _loc_collisions: set[tuple[str, str]] = set()
    _noloc_nodes: dict[tuple[str, str], str] = {}
    _ast_file_nodes: list[tuple[str, str]] = []
    _ast_method_nodes: dict[tuple[str, str], list[str]] = {}

    # Pass 1: 扫描 AST 规范节点
    for nid in sorted(node_set):
        attrs = G.nodes[nid]
        label = str(attrs.get("label", "")).strip()
        sf = str(attrs.get("source_file", ""))
        if not label or not sf:
            continue
        is_ast = attrs.get("_origin") == "ast"
        if attrs.get("source_location") or is_ast:
            key = (sf, label)
            if is_ast:
                if key in _loc_nodes and G.nodes[_loc_nodes[key]].get("_origin") == "ast":
                    _loc_collisions.add(key)
                _loc_nodes[key] = nid
                if _is_file_node_label(label, sf):
                    _ast_file_nodes.append((nid, sf))
                if label.startswith(".") and label.endswith("()"):
                    m_name = make_id(label.removeprefix(".").removesuffix("()"))
                    _ast_method_nodes.setdefault((sf, m_name), []).append(nid)
            else:
                _loc_nodes.setdefault(key, nid)

    # Pass 2: 发现幽灵节点
    _ghost_remap: dict[str, str] = {}
    for nid in sorted(node_set):
        attrs = G.nodes[nid]
        if attrs.get("_origin") == "ast":
            continue
        label = str(attrs.get("label", "")).strip()
        sf = str(attrs.get("source_file", ""))
        if not label or not sf:
            continue
        key = (sf, label)
        if key in _loc_collisions:
            continue
        if key in _loc_nodes and _loc_nodes[key] != nid:
            _noloc_nodes[key] = nid
        elif key not in _loc_nodes:
            m_name = make_id(label.removeprefix(".").removesuffix("()"))
            m_candidates = _ast_method_nodes.get((sf, m_name), [])
            if len(m_candidates) == 1:
                _ghost_remap[nid] = m_candidates[0]

    for key, sem_id in _noloc_nodes.items():
        ast_id = _loc_nodes.get(key)
        if ast_id is not None:
            _ghost_remap[sem_id] = ast_id

    # Pass 2b: 基于文件名提及消解文档幽灵
    if _ast_file_nodes:
        for nid in sorted(node_set):
            if nid in _ghost_remap:
                continue
            attrs = G.nodes[nid]
            if attrs.get("_origin") == "ast":
                continue
            label = str(attrs.get("label", "")).strip()
            if not label:
                continue
            matches = {
                ast_id for ast_id, ast_sf in _ast_file_nodes
                if _is_file_node_label(label, ast_sf)
            }
            if len(matches) == 1:
                _ghost_remap[nid] = next(iter(matches))

    # 从图中移除幽灵节点
    for ghost_id in _ghost_remap:
        G.remove_node(ghost_id)
        node_set.discard(ghost_id)

    return G, _ghost_remap, node_set


def assemble_graph_topology(
    G: nx.Graph,
    extraction: dict,
    ghost_remap: dict[str, str],
    node_set: set[str],
    root: str | None = None
) -> nx.Graph:
    """
    第三阶段：纯净 NetworkX 图拓扑装配与边重定向。
    """
    from graphify.build import (
        _normalize_id,
        _is_abs,
        _old_file_stems,
        _EXTERNAL_STUB_RELATIONS,
        _mint_external_stub,
        _norm_source_file,
        _EDGE_LANG_FAMILY,
        _GENERIC_RELATIONS,
        _CONFIDENCE_RANK,
        _disambiguate_file_node_labels,
    )
    from graphify.extractors.base import _file_stem as _fs

    # 1. 规范化 ID 映射
    norm_to_id: dict[str, str] = {_normalize_id(nid): nid for nid in node_set}
    for ghost_id, canonical_id in ghost_remap.items():
        norm_to_id[_normalize_id(ghost_id)] = canonical_id
        norm_to_id[ghost_id] = canonical_id

    # 2. 别名候选收集
    _alias_candidates: dict[str, set[str]] = {}
    for nid in node_set:
        attrs = G.nodes[nid]
        sf = attrs.get("source_file")
        if not sf or _is_abs(str(sf)):
            continue
        rel = Path(str(sf))
        new_stem = make_id(_fs(rel))
        suffix = ""
        if str(attrs.get("label", "")) != rel.name and _normalize_id(nid).startswith(new_stem):
            suffix = _normalize_id(nid)[len(new_stem):]
        for old_stem in _old_file_stems(rel):
            if old_stem != new_stem:
                alias = old_stem + suffix
                _alias_candidates.setdefault(_normalize_id(alias), set()).add(nid)
                _alias_candidates.setdefault(alias, set()).add(nid)
        if attrs.get("_origin") == "ast" and str(attrs.get("label", "")).startswith("."):
            m_name = make_id(str(attrs.get("label", "")).strip().removeprefix(".").removesuffix("()"))
            m_alias = f"{new_stem}_{m_name}"
            if _normalize_id(nid) != _normalize_id(m_alias):
                _alias_candidates.setdefault(_normalize_id(m_alias), set()).add(nid)
                _alias_candidates.setdefault(m_alias, set()).add(nid)

    for alias_key, candidates in _alias_candidates.items():
        if len(candidates) == 1:
            norm_to_id.setdefault(alias_key, next(iter(candidates)))

    # 3. 边处理
    for edge in sorted(
        extraction.get("edges", []),
        key=lambda e: (
            str(e.get("source", e.get("from", ""))),
            str(e.get("target", e.get("to", ""))),
            str(e.get("relation", "")),
        ),
    ):
        if "source" not in edge and "from" in edge:
            edge["source"] = edge["from"]
        if "target" not in edge and "to" in edge:
            edge["target"] = edge["to"]
        if "source" not in edge or "target" not in edge:
            continue
        src, tgt = edge["source"], edge["target"]
        try:
            hash(src)
            hash(tgt)
        except TypeError:
            continue

        if src not in node_set:
            src = norm_to_id.get(_normalize_id(src), src)
        if tgt not in node_set:
            tgt = norm_to_id.get(_normalize_id(tgt), tgt)
        if src not in node_set or tgt not in node_set:
            if (
                edge.get("relation") in _EXTERNAL_STUB_RELATIONS
                and src in node_set
                and tgt not in node_set
                and isinstance(tgt, str)
            ):
                _mint_external_stub(G, node_set, tgt)
            else:
                continue

        attrs = {k: v for k, v in edge.items() if k not in ("source", "target", "target_file", "local_alias")}
        for _num_key in ("weight", "confidence_score"):
            if _num_key in attrs:
                try:
                    _num_val = float(attrs[_num_key])
                except (TypeError, ValueError):
                    _num_val = 1.0
                if not math.isfinite(_num_val) or _num_val < 0:
                    _num_val = 1.0
                attrs[_num_key] = _num_val

        if not attrs.get("source_file"):
            attrs["source_file"] = G.nodes[src].get("source_file") or G.nodes[tgt].get("source_file") or ""
        if "source_file" in attrs:
            attrs["source_file"] = _norm_source_file(attrs["source_file"], root)
        if attrs.get("definition_file"):
            attrs["definition_file"] = _norm_source_file(attrs["definition_file"], root)

        _edge_rel = attrs.get("relation")
        if _edge_rel in ("calls", "imports", "imports_from", "references"):
            src_ext = Path(G.nodes[src].get("source_file") or "").suffix.lower()
            tgt_ext = Path(G.nodes[tgt].get("source_file") or "").suffix.lower()
            src_fam = _EDGE_LANG_FAMILY.get(src_ext)
            tgt_fam = _EDGE_LANG_FAMILY.get(tgt_ext)
            if _edge_rel == "calls":
                if attrs.get("confidence") == "INFERRED" and src_ext and tgt_ext and src_fam != tgt_fam:
                    continue
            else:
                if src_fam is not None and tgt_fam is not None and src_fam != tgt_fam:
                    continue

        if src == tgt and _edge_rel in ("imports", "imports_from", "re_exports"):
            continue

        attrs["_src"] = src
        attrs["_tgt"] = tgt

        if not G.is_directed() and G.has_edge(src, tgt):
            existing = edge_data(G, src, tgt)
            if existing.get("relation") == attrs.get("relation") and (
                existing.get("_src") == tgt and existing.get("_tgt") == src
            ):
                continue

        if G.has_edge(src, tgt):
            existing_attrs = edge_data(G, src, tgt)
            existing_rel = existing_attrs.get("relation")
            if attrs.get("relation") in _GENERIC_RELATIONS and existing_rel is not None and existing_rel not in _GENERIC_RELATIONS:
                continue
            if existing_rel == attrs.get("relation"):
                existing_conf = existing_attrs.get("confidence")
                incoming_conf = attrs.get("confidence")
                existing_rank = _CONFIDENCE_RANK.get(existing_conf, 0)
                incoming_rank = _CONFIDENCE_RANK.get(incoming_conf, 0)
                if existing_rank > incoming_rank:
                    continue
                if existing_rank == incoming_rank:
                    if existing_attrs.get("source_location") and not attrs.get("source_location"):
                        continue
                    existing_score = existing_attrs.get("confidence_score")
                    incoming_score = attrs.get("confidence_score")
                    if existing_score is not None and incoming_score is not None and existing_score > incoming_score:
                        continue

        G.add_edge(src, tgt, **attrs)

    # 4. Hyperedges 处理
    hyperedges = extraction.get("hyperedges", [])
    if hyperedges:
        kept_hyperedges = []
        for he in hyperedges:
            if isinstance(he, dict) and he.get("source_file"):
                he["source_file"] = _norm_source_file(he["source_file"], root)
            if isinstance(he, dict) and isinstance(he.get("nodes"), list):
                valid_members = []
                for m in he["nodes"]:
                    try:
                        hash(m)
                    except TypeError:
                        continue
                    if m not in node_set and isinstance(m, str):
                        m = norm_to_id.get(_normalize_id(m), m)
                    if m in node_set:
                        valid_members.append(m)
                if not valid_members:
                    print(
                        f"[graphify] WARNING: dropping hyperedge "
                        f"{he.get('id', '?')!r} — none of its members "
                        f"{he.get('nodes')!r} match built nodes.",
                        file=sys.stderr,
                    )
                    continue
                if valid_members != he["nodes"]:
                    he["nodes"] = valid_members
            kept_hyperedges.append(he)
        if kept_hyperedges:
            G.graph["hyperedges"] = kept_hyperedges
        else:
            G.graph["hyperedges"] = []
            print(
                f"[graphify] WARNING: all {len(hyperedges)} hyperedge(s) were "
                f"dropped by member revalidation; graph.json's hyperedge set "
                f"will be emptied on the next export.",
                file=sys.stderr,
            )

    _disambiguate_file_node_labels(G)
    return G
