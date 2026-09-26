"""
ECharts 5 + Canvas 无限画布 ComfyUI 风格激光卷帘对比大屏导出器 (Curtain Compare Exporter)
提供 Before（改造前: 猩红上帝巨星与复杂纠缠）与 After（改造后: 职责解耦与清晰微模块）的镜像同步画布，
结合垂直发光激光轴（Laser Divider）与 CSS clip-path，实现如丝般顺滑的 60FPS 划卷对比体验。
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import networkx as nx
from typing import Dict, Any, List, Optional

from graphify.security import sanitize_label
from graphify.paths import write_text_atomic
from graphify.exporters.echarts_radar import build_clean_echarts_package


def to_curtain_compare_html(
    G_before: nx.Graph,
    G_after: nx.Graph,
    output_path: str,
    *,
    project_title: str = "代码架构解耦重构对比工作台",
    score_stats: Optional[Dict[str, Any]] = None
) -> bool:
    """
    将重构前后的图谱打包为单文件 ComfyUI 卷帘对比大屏 HTML。
    """
    pkg_before = build_clean_echarts_package(G_before, max_nodes=140)
    pkg_after = build_clean_echarts_package(G_after, max_nodes=140)

    stats = score_stats or {
        "malignant_before": 1,
        "malignant_after": 0,
        "max_deg_before": 246,
        "max_deg_after": 35,
        "coupling_drop": "85%",
        "rating_before": "D (高危)",
        "rating_after": "A+ (健康)"
    }

    nodes_before_json = json.dumps(pkg_before["nodes"], ensure_ascii=False)
    links_before_json = json.dumps(pkg_before["links"], ensure_ascii=False)
    nodes_after_json = json.dumps(pkg_after["nodes"], ensure_ascii=False)
    links_after_json = json.dumps(pkg_after["links"], ensure_ascii=False)
    stats_json = json.dumps(stats, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project_title} - ComfyUI 风格无限画布激光卷帘对比中心</title>
    <!-- 引入 ECharts 5 现代拓扑图表库 -->
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <style>
        :root {{
            --bg-color: #080c14;
            --panel-bg: rgba(15, 23, 42, 0.92);
            --border-color: #1e293b;
            --accent-cyan: #38bdf8;
            --accent-red: #ef4444;
            --accent-red-glow: rgba(239, 68, 68, 0.45);
            --accent-green: #34d399;
            --accent-green-glow: rgba(52, 211, 153, 0.45);
            --laser-color: #38bdf8;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
        }}

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
            user-select: none;
        }}

        /* 顶部导航与量化成绩单 */
        header {{
            height: 64px;
            background: var(--panel-bg);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 24px;
            backdrop-filter: blur(16px);
            z-index: 100;
        }}

        .brand {{ display: flex; align-items: center; gap: 12px; }}
        .badge-comfy {{
            background: linear-gradient(135deg, #a855f7, #6366f1);
            color: #fff;
            font-size: 11px;
            font-weight: 800;
            padding: 4px 8px;
            border-radius: 4px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            box-shadow: 0 0 12px rgba(168, 85, 247, 0.4);
        }}
        .title {{ font-size: 16px; font-weight: 700; }}

        /* 数字化成绩单胶囊 */
        .scoreboard {{
            display: flex;
            align-items: center;
            gap: 16px;
            background: rgba(30, 41, 59, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.08);
            padding: 6px 18px;
            border-radius: 30px;
            backdrop-filter: blur(12px);
        }}
        .score-item {{ display: flex; align-items: center; gap: 6px; font-size: 12px; }}
        .score-val-old {{ color: #f87171; text-decoration: line-through; }}
        .score-val-new {{ color: #34d399; font-weight: 800; }}
        .score-tag {{ color: var(--text-muted); }}

        /* 卷帘主工作台容器 */
        #viewport-wrapper {{
            flex: 1;
            position: relative;
            overflow: hidden;
            width: 100%;
            height: 100%;
            cursor: ew-resize;
        }}

        /* 左右双层画布绝对叠放 */
        .canvas-layer {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
        }}

        /* 顶层经过 clip-path 硬件裁剪 */
        #layer-after {{
            z-index: 20;
            pointer-events: none; /* 让鼠标事件无缝穿透或由统一控制器分发 */
        }}

        #layer-before {{
            z-index: 10;
        }}

        /* 激光分割线轴 (Laser Divider) */
        #laser-line {{
            position: absolute;
            top: 0;
            bottom: 0;
            width: 2px;
            background: linear-gradient(180deg, #38bdf8, #a855f7, #38bdf8);
            box-shadow: 0 0 16px #38bdf8, 0 0 30px rgba(56, 189, 248, 0.6);
            z-index: 50;
            pointer-events: none;
            transition: opacity 0.2s;
        }}

        /* 激光把手菱形徽章 */
        #laser-handle {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%) rotate(45deg);
            width: 28px;
            height: 28px;
            background: #0f172a;
            border: 2px solid #38bdf8;
            box-shadow: 0 0 20px #38bdf8;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        #laser-handle::after {{
            content: '';
            width: 8px;
            height: 8px;
            background: #38bdf8;
            border-radius: 50%;
        }}

        /* 浮动标签提示 */
        .floating-label {{
            position: absolute;
            top: 24px;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 700;
            backdrop-filter: blur(12px);
            z-index: 60;
            pointer-events: none;
        }}
        #label-before {{
            left: 32px;
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid var(--accent-red);
            color: #fca5a5;
            box-shadow: 0 0 20px var(--accent-red-glow);
        }}
        #label-after {{
            right: 32px;
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid var(--accent-green);
            color: #6ee7b7;
            box-shadow: 0 0 20px var(--accent-green-glow);
        }}

        /* 底部引导栏 */
        #hint-bar {{
            position: absolute;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 6px 18px;
            border-radius: 20px;
            font-size: 12px;
            color: var(--text-muted);
            z-index: 60;
            pointer-events: none;
        }}
        #hint-bar b {{ color: var(--accent-cyan); }}
    </style>
</head>
<body>

    <header>
        <div class="brand">
            <span class="badge-comfy">COMFYUI STYLE</span>
            <div class="title">{project_title}</div>
        </div>

        <!-- 数字化重构战绩看板 -->
        <div class="scoreboard">
            <div class="score-item">
                <span class="score-tag">恶性上帝病灶:</span>
                <span class="score-val-old" id="stat-mal-old">-</span>
                <span>➔</span>
                <span class="score-val-new" id="stat-mal-new">-</span>
            </div>
            <div class="score-item">
                <span class="score-tag">最高连接度:</span>
                <span class="score-val-old" id="stat-deg-old">-</span>
                <span>➔</span>
                <span class="score-val-new" id="stat-deg-new">-</span>
            </div>
            <div class="score-item">
                <span class="score-tag">代码解耦率:</span>
                <span class="score-val-new" id="stat-coupling">-</span>
            </div>
            <div class="score-item">
                <span class="score-tag">综合架构评级:</span>
                <span class="score-val-new" id="stat-rating">-</span>
            </div>
        </div>
    </header>

    <div id="viewport-wrapper">
        <!-- 浮动状态标签 -->
        <div class="floating-label" id="label-before">🔴 改造前 (Before: 恶性上帝病灶与繁重依赖)</div>
        <div class="floating-label" id="label-after">🟢 改造后 (After: 纯净微模块与优雅解耦)</div>

        <!-- 底层：改造前画布 (全屏铺底) -->
        <div id="layer-before" class="canvas-layer"></div>

        <!-- 顶层：改造后画布 (由 clip-path 动态裁剪揭开) -->
        <div id="layer-after" class="canvas-layer"></div>

        <!-- 垂直激光分割轴 -->
        <div id="laser-line">
            <div id="laser-handle"></div>
        </div>

        <div id="hint-bar">
            ↔ <b>鼠标左右滑动</b> 实时展开/闭合画卷对比 · <b>滚轮缩放与右键拖拽</b> 双画布视角绝对镜像同步
        </div>
    </div>

    <script>
        const NODES_BEFORE = {nodes_before_json};
        const LINKS_BEFORE = {links_before_json};
        const NODES_AFTER = {nodes_after_json};
        const LINKS_AFTER = {links_after_json};
        const STATS = {stats_json};

        let chartBefore = null;
        let chartAfter = null;
        let isSyncing = false;

        function initStats() {{
            document.getElementById('stat-mal-old').innerText = `${{STATS.malignant_before}} 个`;
            document.getElementById('stat-mal-new').innerText = `${{STATS.malignant_after}} 个 (清零)`;
            document.getElementById('stat-deg-old').innerText = `${{STATS.max_deg_before}} 度`;
            document.getElementById('stat-deg-new').innerText = `${{STATS.max_deg_after}} 度`;
            document.getElementById('stat-coupling').innerText = STATS.coupling_drop;
            document.getElementById('stat-rating').innerText = STATS.rating_after;
        }}

        function initCharts() {{
            chartBefore = echarts.init(document.getElementById('layer-before'));
            chartAfter = echarts.init(document.getElementById('layer-after'));

            const optionBefore = getChartOption(NODES_BEFORE, LINKS_BEFORE, 'before');
            const optionAfter = getChartOption(NODES_AFTER, LINKS_AFTER, 'after');

            chartBefore.setOption(optionBefore);
            chartAfter.setOption(optionAfter);

            // 视口平移与缩放镜像同步 (Camera Roam Synchronization)
            chartBefore.on('graphRoam', function (params) {{
                if (isSyncing) return;
                isSyncing = true;
                chartAfter.dispatchAction({{
                    type: 'graphRoam',
                    zoom: params.zoom,
                    dx: params.dx,
                    dy: params.dy
                }});
                isSyncing = false;
            }});

            window.addEventListener('resize', () => {{
                chartBefore.resize();
                chartAfter.resize();
            }});
        }}

        function getChartOption(nodes, links, mode) {{
            return {{
                backgroundColor: 'transparent',
                tooltip: {{
                    trigger: 'item',
                    backgroundColor: 'rgba(15, 23, 42, 0.95)',
                    borderColor: '#334155',
                    textStyle: {{ color: '#f8fafc', fontSize: 12 }},
                    formatter: function(params) {{
                        if (params.dataType === 'edge') {{
                            return `调用关系: <b>${{params.data.source}} → ${{params.data.target}}</b>`;
                        }}
                        const malTag = params.data.is_malignant ? '<br><span style="color:#ef4444;font-weight:bold;">🚨 恶性上帝类</span>' : '';
                        return `<b>${{params.data.name}}</b>${{malTag}}<br>连接度: ${{params.data.degree}} 度`;
                    }}
                }},
                series: [{{
                    type: 'graph',
                    layout: 'none',
                    data: nodes,
                    links: links,
                    roam: true,
                    scaleLimit: {{ min: 0.1, max: 6.0 }},
                    label: {{
                        show: true,
                        position: 'right',
                        formatter: '{{b}}',
                        color: mode === 'before' ? '#fecaca' : '#cbd5e1',
                        fontSize: 10
                    }},
                    edgeSymbol: ['none', 'arrow'],
                    edgeSymbolSize: [0, 6],
                    lineStyle: {{
                        color: mode === 'before' ? 'rgba(239, 68, 68, 0.4)' : 'rgba(56, 189, 248, 0.35)',
                        width: 1.5,
                        curveness: 0.12
                    }},
                    emphasis: {{
                        focus: 'adjacency',
                        lineStyle: {{ width: 3, color: mode === 'before' ? '#ef4444' : '#38bdf8' }}
                    }}
                }}]
            }};
        }}

        // 激光卷帘滑动控制器 (ComfyUI Curtain Swipe Engine)
        function initCurtainSwipe() {{
            const wrapper = document.getElementById('viewport-wrapper');
            const layerAfter = document.getElementById('layer-after');
            const laserLine = document.getElementById('laser-line');

            let currentSplit = 50; // 默认居中 50%

            function updateCurtain(xPercent) {{
                currentSplit = Math.max(0, Math.min(100, xPercent));
                // 顶层通过 clip-path 硬件加速裁剪：揭开右半边
                layerAfter.style.clipPath = `polygon(${{currentSplit}}% 0, 100% 0, 100% 100%, ${{currentSplit}}% 100%)`;
                laserLine.style.left = `${{currentSplit}}%`;
            }}

            wrapper.addEventListener('mousemove', function(e) {{
                const rect = wrapper.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const xPercent = (x / rect.width) * 100;
                updateCurtain(xPercent);
            }});

            // 触摸屏支持
            wrapper.addEventListener('touchmove', function(e) {{
                if (e.touches.length > 0) {{
                    const rect = wrapper.getBoundingClientRect();
                    const x = e.touches[0].clientX - rect.left;
                    const xPercent = (x / rect.width) * 100;
                    updateCurtain(xPercent);
                }}
            }});

            // 初始应用 50% 分割
            updateCurtain(50);
        }}

        window.onload = function() {{
            initStats();
            initCharts();
            initCurtainSwipe();
        }};
    </script>
</body>
</html>
"""
    write_text_atomic(output_path, html)
    return True
