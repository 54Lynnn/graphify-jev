"""
单元测试：构建流水线解耦模块 (Build Pipeline Tests)
验证 Preflight、GhostNodeResolver 与 GraphAssembler 的行为稳定性。
"""
import pytest
import networkx as nx

from graphify.build_pipeline import (
    preflight_extraction,
    resolve_ghost_nodes,
    assemble_graph_topology,
)


def test_preflight_extraction_links_and_aliases():
    raw = {
        "nodes": [
            {"id": "n1", "name": "Node1", "path": "src/node1.py"},
            {"id": "n2", "name": "Node2", "source": "src/node2.py"},
        ],
        "links": [
            {"source": "n1", "target": "n2", "type": "calls"}
        ]
    }
    cleaned, root = preflight_extraction(raw)
    assert "edges" in cleaned
    assert len(cleaned["edges"]) == 1
    # 验证 name -> label, path -> source_file
    assert cleaned["nodes"][0]["label"] == "Node1"
    assert cleaned["nodes"][0]["source_file"] == "src/node1.py"
    # 验证 source -> source_file
    assert cleaned["nodes"][1]["source_file"] == "src/node2.py"
    # 验证 type -> relation
    assert cleaned["edges"][0]["relation"] == "calls"


def test_resolve_ghost_nodes_ast_precedence():
    G = nx.DiGraph()
    # AST 胜者
    G.add_node("ast_1", label="foo", source_file="src/a.py", _origin="ast", source_location="L10")
    # LLM 幽灵
    G.add_node("llm_1", label="foo", source_file="src/a.py", _origin="llm", source_location="L10")
    G.add_node("other", label="bar", source_file="src/b.py", _origin="ast")

    G_resolved, ghost_remap, node_set = resolve_ghost_nodes(G)
    assert "llm_1" in ghost_remap
    assert ghost_remap["llm_1"] == "ast_1"
    assert "llm_1" not in G_resolved
    assert "ast_1" in G_resolved
