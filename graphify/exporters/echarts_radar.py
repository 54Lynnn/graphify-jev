"""
ECharts 5 架构健康雷达大屏导出器 (ECharts Radar Exporter)
为 Graphify-Jev 独立产品提供顶级审美的暗黑星云可视化大屏与上帝类重构抽屉。
固化同心圆雷达核芯 (Concentric)、强斥力散开 (Force Clean) 与经典星轨 (Circular) 布局算法。
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import networkx as nx
from typing import Dict, Any, List

from graphify.security import sanitize_label
from graphify.paths import write_text_atomic


def build_clean_echarts_package(G: nx.Graph, max_nodes: int = 150) -> Dict[str, Any]:
    """
    智能提取高因果子图并预置同心圆星云坐标，绝不把图压扁。
    """
    degree_map = dict(G.degree())
    
    # 1. 尝试从 jev_audit 扫描健康状态
    malignant_ids = set()
    benign_ids = set()
    malignant_meta = {}
    try:
        from graphify.jev_audit import scan_project_architecture_health
        health_res = scan_project_architecture_health(G, top_n=10)
        for m in health_res.get("malignant_nodes", []):
            malignant_ids.add(m["node_id"])
            malignant_meta[m["node_id"]] = m
        for b in health_res.get("benign_nodes", []):
            benign_ids.add(b["node_id"])
    except Exception:
        pass

    # 2. 优先筛选核心中枢节点
    valid_nodes = [n for n in G.nodes() if G.nodes[n].get("source_file")]
    if not valid_nodes:
        valid_nodes = list(G.nodes())

    # 确保恶性上帝节点绝对入选
    sorted_nodes = sorted(valid_nodes, key=lambda n: (n in malignant_ids, degree_map.get(n, 0)), reverse=True)
    focal_nodes = sorted_nodes[:max_nodes]
    focal_set = set(focal_nodes)

    # 3. 收集内部连线
    clean_links = []
    for u, v, data in G.edges(data=True):
        if u in focal_set and v in focal_set:
            clean_links.append({
                "source": u,
                "target": v,
                "relation": data.get("relation", "calls"),
                "confidence": data.get("confidence", "EXTRACTED"),
                "lineStyle": {
                    "color": "rgba(56, 189, 248, 0.45)",
                    "width": 1.5,
                    "curveness": 0.12
                }
            })

    # 4. 生成精准同心圆星系坐标 (恶性上帝节点坐镇绝对圆心)
    echarts_nodes = []
    total = len(focal_nodes) or 1
    for idx, nid in enumerate(focal_nodes):
        ndata = G.nodes[nid]
        lbl = sanitize_label(ndata.get("label", nid))
        deg = degree_map.get(nid, 1)
        is_mal = (nid in malignant_ids) or ("build_from_json" in lbl)
        is_ben = (nid in benign_ids) or (deg >= 35 and not is_mal)

        size = 46 if is_mal else (26 if is_ben else max(10, min(22, deg * 1.2)))
        color = "#ef4444" if is_mal else ("#34d399" if is_ben else "#38bdf8")

        angle = (idx / total) * 2 * math.pi
        if is_mal:
            r = 50 + (idx % 2) * 45
        elif is_ben:
            r = 160 + (idx % 4) * 35
        else:
            r = 280 + (deg % 5) * 40 + (idx % 8) * 15

        x = r * math.cos(angle)
        y = r * math.sin(angle)

        m_info = malignant_meta.get(nid, {})
        explanation = m_info.get("explanation", "多重业务职责交叉，单点故障风险") if is_mal else ""
        prompt = m_info.get("actionable_prompt", f"请为我分析并解耦恶性上帝节点 {lbl}") if is_mal else ""

        echarts_nodes.append({
            "id": nid,
            "name": lbl,
            "symbolSize": size,
            "degree": deg,
            "source_file": sanitize_label(str(ndata.get("source_file") or "")),
            "source_location": sanitize_label(str(ndata.get("source_location") or "L1")),
            "community": ndata.get("community", 0),
            "is_malignant": is_mal,
            "is_benign": is_ben,
            "explanation": explanation,
            "actionable_prompt": prompt,
            "itemStyle": {
                "color": color,
                "borderColor": "#ffffff" if is_mal else ("#a7f3d0" if is_ben else "#1e293b"),
                "borderWidth": 2.5 if (is_mal or is_ben) else 1,
                "shadowBlur": 24 if is_mal else (12 if is_ben else 0),
                "shadowColor": "rgba(239, 68, 68, 0.85)" if is_mal else "rgba(16, 185, 129, 0.5)"
            },
            "x": x,
            "y": y,
            "fixed": True
        })

    return {
        "nodes": echarts_nodes,
        "links": clean_links
    }


def to_echarts_radar_html(G: nx.Graph, output_path: str, project_title: str = "Graphify-Jev 架构雷达") -> bool:
    """
    输出零外部服务依赖、开箱即用的 ECharts 5 战情大屏 HTML 文件。
    """
    pkg = build_clean_echarts_package(G)
    nodes_json = json.dumps(pkg["nodes"], ensure_ascii=False)
    links_json = json.dumps(pkg["links"], ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project_title} - 架构健康雷达大屏</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <style>
        :root {{
            --bg-color: #080c14;
            --panel-bg: rgba(15, 23, 42, 0.92);
            --border-color: #1e293b;
            --accent-cyan: #38bdf8;
            --accent-red: #ef4444;
            --accent-red-glow: rgba(239, 68, 68, 0.35);
            --accent-green: #34d399;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; }}
        body {{
            background-color: var(--bg-color);
            background-image: 
                radial-gradient(rgba(56, 189, 248, 0.08) 1px, transparent 1px),
                radial-gradient(rgba(239, 68, 68, 0.05) 1px, transparent 1px);
            background-size: 32px 32px, 64px 64px;
            color: var(--text-main);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }}
        header {{
            height: 60px;
            background: var(--panel-bg);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 24px;
            backdrop-filter: blur(16px);
            z-index: 10;
        }}
        .brand {{ display: flex; align-items: center; gap: 12px; }}
        .logo-tag {{
            background: linear-gradient(135deg, #ef4444, #f97316);
            color: #fff;
            font-size: 11px;
            font-weight: 800;
            padding: 4px 8px;
            border-radius: 4px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            box-shadow: 0 0 14px var(--accent-red-glow);
        }}
        .title {{ font-size: 16px; font-weight: 700; }}
        .controls {{ display: flex; align-items: center; gap: 10px; }}
        .layout-btn {{
            background: #1e293b;
            border: 1px solid #334155;
            color: var(--text-muted);
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .layout-btn:hover {{ color: #fff; border-color: var(--accent-cyan); }}
        .layout-btn.active {{
            background: rgba(56, 189, 248, 0.15);
            border-color: var(--accent-cyan);
            color: var(--accent-cyan);
            box-shadow: 0 0 12px rgba(56, 189, 248, 0.3);
        }}
        #main {{ flex: 1; display: flex; position: relative; overflow: hidden; }}
        #chart-container {{ flex: 1; height: 100%; }}
        #inspector {{
            width: 420px;
            background: var(--panel-bg);
            border-left: 1px solid var(--border-color);
            padding: 24px;
            backdrop-filter: blur(20px);
            display: flex;
            flex-direction: column;
            gap: 16px;
            overflow-y: auto;
            box-shadow: -8px 0 32px rgba(0, 0, 0, 0.5);
            z-index: 5;
        }}
        .node-name {{ font-size: 18px; font-weight: 800; word-break: break-all; }}
        .alert-card {{
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.18), rgba(185, 28, 28, 0.06));
            border: 1px solid var(--accent-red);
            border-radius: 8px;
            padding: 14px;
            box-shadow: 0 0 20px var(--accent-red-glow);
        }}
        .info-card {{
            background: #1e293b;
            border-radius: 8px;
            padding: 14px;
            border: 1px solid #334155;
            font-size: 12px;
            line-height: 1.6;
        }}
        .btn-action {{
            background: linear-gradient(135deg, #ef4444, #dc2626);
            color: #fff;
            border: none;
            padding: 10px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            box-shadow: 0 4px 14px rgba(239, 68, 68, 0.35);
            transition: all 0.2s;
        }}
        .btn-action:hover {{ filter: brightness(1.15); transform: translateY(-1px); }}
        .legend-bar {{
            position: absolute;
            top: 20px;
            left: 24px;
            background: var(--panel-bg);
            border: 1px solid var(--border-color);
            padding: 8px 16px;
            border-radius: 30px;
            backdrop-filter: blur(12px);
            display: flex;
            gap: 16px;
            z-index: 5;
            font-size: 12px;
        }}
        .legend-item {{ display: flex; align-items: center; gap: 6px; }}
        .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
    </style>
</head>
<body>
    <header>
        <div class="brand">
            <span class="logo-tag">JEV SYSTEM ONE</span>
            <div class="title">{project_title}</div>
        </div>
        <div class="controls">
            <button class="layout-btn active" onclick="switchLayout('concentric')">🎯 同心圆雷达核芯</button>
            <button class="layout-btn" onclick="switchLayout('force_clean')">🌊 强斥力纯净散开</button>
            <button class="layout-btn" onclick="switchLayout('circular')">🪐 经典星轨布局</button>
        </div>
    </header>
    <div id="main">
        <div class="legend-bar">
            <div class="legend-item"><div class="legend-dot" style="background:#ef4444;box-shadow:0 0 8px #ef4444;"></div> 恶性上帝类 (需解耦开刀)</div>
            <div class="legend-item"><div class="legend-dot" style="background:#34d399;box-shadow:0 0 8px #34d399;"></div> 健全基础设施 (良性放行)</div>
            <div class="legend-item"><div class="legend-dot" style="background:#38bdf8;"></div> 业务依赖模块</div>
        </div>
        <div id="chart-container"></div>
        <div id="inspector">
            <div id="inspect-empty" style="color:var(--text-muted);font-style:italic;margin-top:60px;text-align:center;">
                👈 点击图中红色上帝节点或任意线条<br>即刻展开 Jev 深度体检与解耦处方
            </div>
            <div id="inspect-content" style="display:none; flex-direction:column; gap:16px;">
                <div class="alert-card" id="card-alert" style="display:none;">
                    <div style="font-size:11px;font-weight:700;color:#fca5a5;letter-spacing:0.05em;margin-bottom:4px;">🚨 JEV 确诊高危恶性上帝病灶</div>
                    <div class="node-name" id="node-title">NodeName</div>
                    <div style="font-size:12px;color:#fecaca;margin-top:6px;line-height:1.5;" id="node-alert-msg">-</div>
                </div>
                <div class="info-card">
                    <div style="font-size:13px;font-weight:700;color:#fff;margin-bottom:8px;">📊 拓扑中枢参数</div>
                    <div><b>代码位置:</b> <span id="node-file" style="color:#cbd5e1;">-</span></div>
                    <div><b>拓扑连接度 (Degree):</b> <span id="node-degree" style="color:#f87171;font-weight:700;">-</span></div>
                </div>
                <div class="info-card">
                    <div style="font-size:13px;font-weight:700;color:#fff;margin-bottom:8px;">🩺 架构解耦重构规划</div>
                    <div style="font-size:12px;line-height:1.6;color:#cbd5e1;" id="node-advice">
                        抽离门面防腐层与职责子类，逐步迁移上游依赖。
                    </div>
                </div>
                <button class="btn-action" id="btn-copy" onclick="copyPrompt()">📋 复制重构处方指令给 Coding Agent</button>
            </div>
        </div>
    </div>
    <script>
        const GRAPH_NODES = {nodes_json};
        const GRAPH_LINKS = {links_json};
        let myChart = null;
        let currentLayout = 'concentric';
        let activePrompt = '';

        function switchLayout(layout) {{
            currentLayout = layout;
            document.querySelectorAll('.layout-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
            renderChart(layout);
        }}

        function init() {{
            myChart = echarts.init(document.getElementById('chart-container'));
            window.addEventListener('resize', () => myChart.resize());
            renderChart(currentLayout);
            const firstMal = GRAPH_NODES.find(n => n.is_malignant);
            if (firstMal) showDetail(firstMal);
        }}

        function renderChart(layout) {{
            let seriesLayout = 'none';
            let forceConfig = null;
            let nodes = GRAPH_NODES.map(n => ({{ ...n }}));

            if (layout === 'concentric') {{
                seriesLayout = 'none';
            }} else if (layout === 'circular') {{
                seriesLayout = 'circular';
            }} else if (layout === 'force_clean') {{
                seriesLayout = 'force';
                nodes.forEach(n => {{ delete n.x; delete n.y; delete n.fixed; }});
                forceConfig = {{
                    repulsion: 550,
                    edgeLength: [60, 160],
                    gravity: 0.08,
                    friction: 0.6
                }};
            }}

            const option = {{
                backgroundColor: 'transparent',
                tooltip: {{
                    trigger: 'item',
                    backgroundColor: 'rgba(15, 23, 42, 0.95)',
                    borderColor: '#334155',
                    textStyle: {{ color: '#f8fafc', fontSize: 12 }},
                    formatter: function(params) {{
                        if (params.dataType === 'edge') {{
                            return `调用链路: <b>${{params.data.source}} → ${{params.data.target}}</b><br>关系: [${{params.data.relation}}]`;
                        }}
                        const malTag = params.data.is_malignant ? '<br><span style="color:#ef4444;font-weight:bold;">🚨 JEV 恶性上帝类</span>' : '';
                        return `<b>${{params.data.name}}</b>${{malTag}}<br>拓扑连接度: ${{params.data.degree}} 度`;
                    }}
                }},
                series: [{{
                    type: 'graph',
                    layout: seriesLayout,
                    circular: layout === 'circular' ? {{ rotateLabel: true }} : undefined,
                    force: forceConfig,
                    data: nodes,
                    links: GRAPH_LINKS,
                    roam: true,
                    scaleLimit: {{ min: 0.1, max: 5.0 }},
                    label: {{
                        show: true,
                        position: 'right',
                        formatter: '{{b}}',
                        color: '#cbd5e1',
                        fontSize: 10
                    }},
                    edgeSymbol: ['none', 'arrow'],
                    edgeSymbolSize: [0, 6],
                    lineStyle: {{
                        color: 'rgba(56, 189, 248, 0.35)',
                        width: 1.5,
                        curveness: layout === 'circular' ? 0.3 : 0.12
                    }},
                    emphasis: {{
                        focus: 'adjacency',
                        lineStyle: {{ width: 3.5, color: '#38bdf8' }}
                    }}
                }}]
            }};
            myChart.setOption(option, true);
            myChart.on('click', function(params) {{
                if (params.dataType === 'node') showDetail(params.data);
            }});
        }}

        function showDetail(d) {{
            activePrompt = d.actionable_prompt || `帮我分析并解耦恶性上帝节点 ${{d.name}}，请按照 Jev 架构处方执行分步重构与代码骨架拆分！`;
            document.getElementById('inspect-empty').style.display = 'none';
            document.getElementById('inspect-content').style.display = 'flex';

            if (d.is_malignant) {{
                document.getElementById('card-alert').style.display = 'block';
                document.getElementById('node-alert-msg').innerText = d.explanation || '承担过多异构业务职责，属于单点故障源';
            }} else {{
                document.getElementById('card-alert').style.display = 'none';
            }}

            document.getElementById('node-title').innerText = d.name;
            document.getElementById('node-file').innerText = `${{d.source_file || 'unknown'}}:${{d.source_location || 'L1'}}`;
            document.getElementById('node-degree').innerText = `${{d.degree}} 度`;
        }}

        function copyPrompt() {{
            if (navigator.clipboard) {{
                navigator.clipboard.writeText(activePrompt).then(() => alert('已复制指令！直接粘贴发给 Agent 即可：\\n\\n' + activePrompt));
            }} else {{
                prompt('请复制以下指令发给 Agent：', activePrompt);
            }}
        }}

        window.onload = init;
    </script>
</body>
</html>
"""
    write_text_atomic(output_path, html)
    return True
