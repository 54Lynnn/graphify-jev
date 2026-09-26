"""
Jev 增强型架构异味诊断器与代码影响面分析器 (Jev Architectural Auditor & Blast Radius Analyzer)

实现两大核心进化：
1. 【智能代码异味诊断（进化 3）】：Jev 充当心电图仪器（毫秒级筛查出高频耦合节点与 God Nodes），
   智能评估其耦合破坏风险；若确诊高危，结构化提供给 Gemini 3.8 Flash 等大模型进行外科重构！
2. 【改动影响面分析（进化 2）】：针对开发者提问的函数或符号，在 Graphify 拓扑图谱中进行反向有向边追踪（Predecessors），
   直观列出所有直接与间接波及的上游调用方（Callers/Imports）。
"""
from __future__ import annotations
import os
import networkx as nx
from typing import Dict, List, Any, Optional

from graphify.jev_bridge import _call_jev_choice, is_available


def audit_god_node_health(G: nx.Graph, node_id: str) -> Dict[str, Any]:
    """
    进化 3 实现：使用 Jev 对高连接度节点（God Node）进行健康度与异味诊断。
    区分是“健全的基础设施（良性心肌）”还是“高危耦合上帝类（恶性病灶）”。
    """
    if node_id not in G:
        return {"status": "error", "message": f"节点 {node_id} 不存在"}

    ndata = G.nodes[node_id]
    label = ndata.get("label", node_id)
    degree = G.degree(node_id)
    source_file = ndata.get("source_file", "")
    doc = ndata.get("docstring") or label

    # 提取它的直接依赖者与被依赖者
    callers = [G.nodes[p].get("label", p) for p in G.predecessors(node_id)] if G.is_directed() else []
    callees = [G.nodes[s].get("label", s) for s in G.successors(node_id)] if G.is_directed() else []

    state_desc = f"""
代码符号：{label} (位于 {source_file})
拓扑连接度 (Degree): {degree}
上游调用者数量: {len(callers)} (包含: {', '.join(callers[:4])})
下游依赖数量: {len(callees)} (包含: {', '.join(callees[:4])})
文档与职责说明：{doc}
"""

    if not is_available():
        # 无 JEV 时返回基础图论指标
        return {
            "node": label,
            "degree": degree,
            "diagnosis": "BENIGN_HUB" if degree < 15 else "NEEDS_REVIEW",
            "reason": "未配置 JEV API Key，仅基于度数阈值粗略判断",
            "refactor_advice": "建议人工审查该高连接度节点的职责边界"
        }

    # 呼叫 Jev 诊断分类
    instructions = "作为软件架构专家，评估该高频被依赖的节点属于良性基础设施还是恶性上帝类？"
    criteria = {
        "BENIGN_INFRA": "良性基础设施/工具：职责单一、纯工具/会话/类型定义（如 get_db, Settings），高频调用属于正常现象，无需重构开刀",
        "MALIGNANT_GOD_CLASS": "恶性上帝类/过度耦合：一个类或函数承担过多异构业务（既管认证又管订单或写库），属于单点脆弱故障源，必须进行重构拆分"
    }

    res = _call_jev_choice(state_desc, instructions, criteria)
    if not res:
        return {
            "node": label,
            "degree": degree,
            "diagnosis": "UNKNOWN",
            "reason": "Jev 决策服务暂时未响应"
        }

    choice, conf, probs = res
    is_malignant = (choice == "MALIGNANT_GOD_CLASS")

    return {
        "node": label,
        "location": source_file,
        "degree": degree,
        "diagnosis": choice,
        "confidence": conf,
        "is_malignant": is_malignant,
        "explanation": "检测到多重业务职责交叉，修改该节点容易引起全库级连带雪崩！" if is_malignant else "该节点属于健全的单例基础设施或数据映射，职责纯粹，安全放行无需手术！",
        "refactor_advice": "建议唤醒 Gemini 3.8 Flash 等大模型将其拆分为独立的领域服务" if is_malignant else "保持现状即可"
    }


def analyze_blast_radius(G: nx.Graph, symbol_query: str, max_depth: int = 2) -> Dict[str, Any]:
    """
    进化 2 实现：全自动变更影响面分析（Blast Radius）。
    逆向有向边追踪（Predecessors），毫秒级列出所有会受影响的上游调用者。
    """
    from graphify.jev_bridge import pick_seeds_with_jev

    # 1. 尝试找到目标起点符号
    matched_nid = None
    for nid in G.nodes():
        lbl = G.nodes[nid].get("label", "")
        if symbol_query.lower() in lbl.lower():
            matched_nid = nid
            break

    if not matched_nid and is_available():
        # 用 Jev 寻找目标符号
        seeds = pick_seeds_with_jev(G, symbol_query, max_seeds=1)
        if seeds:
            matched_nid = seeds[0]

    if not matched_nid or matched_nid not in G:
        return {"error": f"在图谱中未找到与【{symbol_query}】匹配的代码符号"}

    target_data = G.nodes[matched_nid]
    target_label = target_data.get("label", matched_nid)
    target_file = target_data.get("source_file", "")

    # 2. 逆向有向边追踪（Predecessors 逆向 BFS）
    affected_nodes: Dict[int, list[str]] = {}
    visited = {matched_nid}
    current_layer = [matched_nid]

    for d in range(1, max_depth + 1):
        next_layer = []
        for n in current_layer:
            callers = list(G.predecessors(n)) if G.is_directed() else list(G.neighbors(n))
            for c in callers:
                if c not in visited:
                    visited.add(c)
                    next_layer.append(c)
                    affected_nodes.setdefault(d, []).append(c)
        current_layer = next_layer
        if not current_layer:
            break

    total_affected = sum(len(v) for v in affected_nodes.values())

    formatted_chains = []
    for depth_lvl, nids in affected_nodes.items():
        layer_items = []
        for nid in nids:
            nd = G.nodes[nid]
            lbl = nd.get("label", nid)
            sfile = os.path.basename(nd.get("source_file", ""))
            layer_items.append(f"{lbl} ({sfile})")
        formatted_chains.append({
            "depth": depth_lvl,
            "layer_name": "直接上游调用者 (1跳)" if depth_lvl == 1 else f"间接连锁波及者 ({depth_lvl}跳)",
            "affected": layer_items
        })

    return {
        "target_symbol": target_label,
        "target_file": target_file,
        "blast_radius_score": total_affected,
        "severity": "HIGH_RISK" if total_affected >= 5 else ("MODERATE_RISK" if total_affected >= 2 else "LOW_RISK"),
        "chains": formatted_chains
    }
