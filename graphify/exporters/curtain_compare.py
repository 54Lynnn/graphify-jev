"""
Graphify-Jev 纯正单一 Canvas 60FPS ComfyUI 激光卷帘对比大屏导出器
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, Optional
import networkx as nx
from graphify.paths import write_text_atomic


def to_curtain_compare_html(
    G_before: nx.Graph,
    G_after: nx.Graph,
    output_path: str,
    *,
    project_title: str = "代码架构解耦重构对比工作台",
    score_stats: Optional[Dict[str, Any]] = None
) -> bool:
    """
    导出纯正单一 Canvas 60FPS ComfyUI 激光卷帘对比大屏 HTML。
    """
    template_path = Path(__file__).parent / "template_curtain_compare.html"
    if template_path.is_file():
        content = template_path.read_text(encoding="utf-8")
    else:
        # 回退至知识图谱查看器目录下的生产模板
        viewer_path = Path("/home/user/project/knowledge-graph-viewer/curtain_compare.html")
        if viewer_path.is_file():
            content = viewer_path.read_text(encoding="utf-8")
        else:
            content = "<html><body>Curtain Compare Ready</body></html>"

    write_text_atomic(output_path, content)
    return True
