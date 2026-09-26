"""JEV 语义种子决策层 — 基于 TypeSafe System One (JEV) 的两阶段图谱精准导航（std-lib only，fail-open）。

解决传统代码图谱仅靠 Jieba 分词 / 关键词匹配在自然语言大白话提问下容易搜空或噪音节点扩散的痛点。
采用两阶段 Choice 穿透：
1. 阶段 1：在 Louvain 社区间做高维语义粗筛（锁定业务子域并彻底剪枝无关社区）
2. 阶段 2：在目标社区内做符号级精细筛选（挑出最精准的 Seed 种子节点）

纪律与安全保障：
- 严格 Fail-open：未配置 API KEY、网络超时、格式错误等情况下无缝静默回退原生关键词寻种逻辑，绝不阻断服务。
- 出站仅元数据：发送的 criteria 仅包含模块文件路径与符号摘要，严禁发送源码实现细节。
- 零第三方重型依赖：仅使用 Python 标准库 urllib.request 与 json。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Tuple, Any
import networkx as nx

DEFAULT_API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
_TIMEOUT_SECONDS = 4.0


def _api_key() -> str:
    """获取 API Key，优先读取 TYPESAFE_API_KEY，亦兼容 OPENCODE_API_KEY"""
    return os.environ.get("TYPESAFE_API_KEY", "").strip() or os.environ.get("OPENCODE_API_KEY", "").strip()


def _api_url() -> str:
    """获取 API Endpoint，优先读取 TYPESAFE_API_URL，若使用 OpenCode Zen 则自动路由"""
    url = os.environ.get("TYPESAFE_API_URL", "").strip()
    if url:
        return url
    if os.environ.get("OPENCODE_API_KEY", "").strip() and not os.environ.get("TYPESAFE_API_KEY", "").strip():
        return "https://opencode.ai/zen/v1/systemone"
    return DEFAULT_API_URL


def is_available() -> bool:
    """检查 JEV 决策层是否已配置且可用"""
    return bool(_api_key())


def _call_jev_choice(
    state: str, instructions: str, options_map: Dict[str, str], timeout: float = _TIMEOUT_SECONDS
) -> Tuple[str, float] | None:
    """POST 到 System One 执行 Choice 决策，失败时返回 None (fail-open)"""
    key = _api_key()
    if not key or not options_map:
        return None

    model = os.environ.get("TYPESAFE_MODEL", "").strip()
    if not model:
        model = "jev-1.13-free" if "opencode.ai" in _api_url() else DEFAULT_MODEL

    payload = {
        "state": state,
        "model": model,
        "questions": {
            "target": {
                "type": "choice",
                "instructions": instructions,
                "criteria": options_map,
            }
        },
    }

    req = urllib.request.Request(
        _api_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ans = data.get("answers", {}).get("target", {})
            choice = ans.get("choice")
            conf = float(ans.get("confidence", 0.0))
            if choice and choice in options_map:
                return choice, conf
    except Exception:
        # fail-open 保护：任何网络、JSON、状态码异常直接忽略回退
        return None
    return None


def pick_seeds_with_jev(G: nx.Graph, question: str) -> list[str] | None:
    """使用 Jev 在代码图谱中执行两阶段语义穿透寻种。

    成功时返回种子节点列表 [seed_node_id]；
    失败或低置信度时返回 None，提示调用方回退原生关键词寻种逻辑。
    """
    if not is_available() or G.number_of_nodes() == 0:
        return None

    try:
        from graphify.cluster import cluster

        communities = cluster(G)
        if not communities:
            return None

        # 阶段 1：构建社区级语义摘要 (以模块文件与核心符号为主，不包含源码细节)
        community_summaries: Dict[str, str] = {}
        for cid, nids in communities.items():
            labels: list[str] = []
            files: set[str] = set()
            for nid in nids:
                ndata = G.nodes[nid]
                sfile = ndata.get("source_file")
                if sfile:
                    files.add(os.path.basename(sfile))
                lbl = ndata.get("label", nid)
                if not lbl.startswith("rationale_"):
                    labels.append(lbl)
            
            summary = f"Files: [{', '.join(sorted(files)[:5])}] Symbols: [{', '.join(labels[:4])}]"
            community_summaries[str(cid)] = summary

        if len(community_summaries) <= 1:
            # 只有一个社区时直接进入微观选择
            best_cid = "0" if "0" in community_summaries else list(community_summaries.keys())[0]
        else:
            state_c = f"Codebase Query: {question}"
            instr_c = "Which community/module scope directly relates to this developer query?"
            c_res = _call_jev_choice(state_c, instr_c, community_summaries)
            if not c_res:
                return None
            best_cid, c_conf = c_res
            if c_conf < 0.40:  # 置信度过低时放弃，回退原生分词
                return None

        # 阶段 2：在目标社区内做具体节点选择
        target_nids = communities[int(best_cid)]
        node_options: Dict[str, str] = {}
        for nid in target_nids:
            ndata = G.nodes[nid]
            lbl = ndata.get("label", nid)
            if lbl.startswith("rationale_"):
                continue
            loc = ndata.get("source_location", "")
            sfile = os.path.basename(ndata.get("source_file", ""))
            doc = ndata.get("docstring") or lbl
            node_options[nid] = f"[{sfile}:{loc}] {doc}"

        if not node_options:
            return None

        # 若社区节点过多，仅保留前 50 个高优先级候选，防止超过上下文限制
        if len(node_options) > 50:
            node_options = dict(list(node_options.items())[:50])

        state_n = f"Scope: {community_summaries.get(best_cid, '')}\nQuery: {question}"
        instr_n = "Which code entity directly handles or defines the queried functionality?"
        n_res = _call_jev_choice(state_n, instr_n, node_options)
        if not n_res:
            return None

        best_nid, n_conf = n_res
        if best_nid in G:
            return [best_nid]

    except Exception:
        # fail-open 保护
        return None

    return None
