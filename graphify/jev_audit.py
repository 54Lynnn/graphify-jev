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


def analyze_blast_radius(G: nx.Graph, symbol_query: str, max_depth: int = 2, active_graph_path: str | None = None) -> Dict[str, Any]:
    """
    进化 2 实现：全自动变更影响面分析（Blast Radius）。
    逆向有向边追踪（Predecessors），毫秒级列出所有会受影响的上游调用者。
    支持 project_path 作用域感知与 multi-project 隔离。
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
        seeds = pick_seeds_with_jev(G, symbol_query, max_seeds=1, graph_path=active_graph_path)
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


def scan_project_architecture_health(G: nx.Graph, top_n: int = 10) -> Dict[str, Any]:
    """
    全库核心中枢健康雷达扫描：
    按度数提取全库 Top-N 枢纽节点，由 Jev 连续决策引擎快速进行良恶性体检。
    支持 Fail-safe 离线启发式降级。
    """
    if len(G) == 0:
        return {
            "mode": "empty_graph",
            "total_scanned": 0,
            "malignant_nodes": [],
            "benign_nodes": [],
            "summary": "图谱为空"
        }

    # 1. 筛选候选枢纽节点：优先保留有明确源码归属的节点
    valid_nodes = [n for n in G.nodes() if G.nodes[n].get("source_file")]
    if not valid_nodes:
        valid_nodes = list(G.nodes())

    # 按度数降序排序
    sorted_nodes = sorted(valid_nodes, key=lambda n: G.degree(n), reverse=True)
    candidate_nodes = sorted_nodes[:top_n]

    # 2. 检查 Jev 是否可用，不可用时启用 Fail-safe 启发式降级
    if not is_available():
        malignant_list = []
        benign_list = []
        for nid in candidate_nodes:
            ndata = G.nodes[nid]
            deg = G.degree(nid)
            lbl = ndata.get("label", nid)
            sfile = ndata.get("source_file", "")
            in_deg = G.in_degree(nid) if G.is_directed() else deg
            out_deg = G.out_degree(nid) if G.is_directed() else deg
            
            # 纯拓扑启发式：入度高且出度高（既当数据又当分发中心）倾向于高危
            is_mal = (deg >= 5 and in_deg >= 2 and out_deg >= 2)
            item = {
                "node_id": nid,
                "label": lbl,
                "source_file": sfile,
                "degree": deg,
                "in_degree": in_deg,
                "out_degree": out_deg,
                "is_malignant": is_mal,
                "diagnosis": "HEURISTIC_NEEDS_REVIEW" if is_mal else "HEURISTIC_BENIGN",
                "explanation": "拓扑出入度均较高，可能承担过多样务职责" if is_mal else "度数处于合理范围或以单向依赖为主",
                "actionable_prompt": f"分析并解耦节点 {lbl}"
            }
            if is_mal:
                malignant_list.append(item)
            else:
                benign_list.append(item)

        return {
            "mode": "failsafe_heuristic",
            "total_scanned": len(candidate_nodes),
            "failsafe_note": "未配置 JEV API Key，已切换为拓扑启发式分析",
            "malignant_nodes": malignant_list,
            "benign_nodes": benign_list,
            "summary": f"体检完成（启发式）：共扫描 {len(candidate_nodes)} 个中枢节点，发现 {len(malignant_list)} 个疑似耦合病灶"
        }

    # 3. Jev 决策可用时，逐个进行精确定性体检
    malignant_list = []
    benign_list = []

    for nid in candidate_nodes:
        diag = audit_god_node_health(G, nid)
        ndata = G.nodes[nid]
        lbl = diag.get("node", ndata.get("label", nid))
        sfile = diag.get("location", ndata.get("source_file", ""))
        deg = diag.get("degree", G.degree(nid))
        in_deg = G.in_degree(nid) if G.is_directed() else deg
        out_deg = G.out_degree(nid) if G.is_directed() else deg
        is_mal = diag.get("is_malignant", False)

        item = {
            "node_id": nid,
            "label": lbl,
            "source_file": sfile,
            "degree": deg,
            "in_degree": in_deg,
            "out_degree": out_deg,
            "is_malignant": is_mal,
            "diagnosis": diag.get("diagnosis", "UNKNOWN"),
            "confidence": diag.get("confidence", 0.0),
            "explanation": diag.get("explanation", ""),
            "actionable_prompt": f"请为我生成 {lbl} 的重构解耦方案"
        }
        if is_mal:
            malignant_list.append(item)
        else:
            benign_list.append(item)

    return {
        "mode": "jev_system_one",
        "total_scanned": len(candidate_nodes),
        "malignant_nodes": malignant_list,
        "benign_nodes": benign_list,
        "summary": f"体检完成（Jev 深度诊断）：共扫描 {len(candidate_nodes)} 个中枢节点，确诊 {len(malignant_list)} 个恶性上帝病灶，放行 {len(benign_list)} 个良性基础设施"
    }


def get_refactor_context(G: nx.Graph, symbol_query: str) -> Dict[str, Any]:
    """
    为上层 Agent 提取指定病灶节点的精准拓扑依赖切片，
    供 Agent 直接生成架构解耦与重构处方。
    """
    matched_nid = None
    # 优先全字精确匹配，再进行不区分大小写匹配
    for nid in G.nodes():
        lbl = G.nodes[nid].get("label", "")
        if symbol_query == lbl or symbol_query == nid:
            matched_nid = nid
            break

    if not matched_nid:
        for nid in G.nodes():
            lbl = G.nodes[nid].get("label", "")
            if symbol_query.lower() in lbl.lower():
                matched_nid = nid
                break

    if not matched_nid or matched_nid not in G:
        return {"error": f"在图谱中未找到与【{symbol_query}】匹配的代码符号"}

    ndata = G.nodes[matched_nid]
    target_label = ndata.get("label", matched_nid)
    target_file = ndata.get("source_file", "")
    docstring = ndata.get("docstring", "")
    community = ndata.get("community", 0)

    # 提取上游调用方 (Callers / Predecessors)
    callers = []
    if G.is_directed():
        for p in G.predecessors(matched_nid):
            callers.append({
                "node_id": p,
                "label": G.nodes[p].get("label", p),
                "source_file": G.nodes[p].get("source_file", ""),
                "community": G.nodes[p].get("community", 0)
            })
    else:
        for n in G.neighbors(matched_nid):
            callers.append({
                "node_id": n,
                "label": G.nodes[n].get("label", n),
                "source_file": G.nodes[n].get("source_file", ""),
                "community": G.nodes[n].get("community", 0)
            })

    # 提取下游依赖方 (Callees / Successors)
    callees = []
    if G.is_directed():
        for s in G.successors(matched_nid):
            callees.append({
                "node_id": s,
                "label": G.nodes[s].get("label", s),
                "source_file": G.nodes[s].get("source_file", ""),
                "community": G.nodes[s].get("community", 0)
            })

    # 统计涉及跨越的模块与文件跨度
    related_files = set()
    if target_file:
        related_files.add(target_file)
    for c in callers:
        if c.get("source_file"):
            related_files.add(c["source_file"])
    for c in callees:
        if c.get("source_file"):
            related_files.add(c["source_file"])

    return {
        "target_node_id": matched_nid,
        "target_label": target_label,
        "target_file": target_file,
        "docstring": docstring,
        "community": community,
        "degree": G.degree(matched_nid),
        "callers_count": len(callers),
        "callees_count": len(callees),
        "callers": callers,
        "callees": callees,
        "spanning_files_count": len(related_files),
        "spanning_files": sorted(list(related_files))
    }

