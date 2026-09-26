"""
单元测试：可视化雷达红绿灯与重构抽屉 (Visual Health Radar & Refactoring Drawer)
验证导出的 graph.html 中是否包含恶性红圈节点元数据、警报高亮样式与复制指令 DOM。
"""
import os
import tempfile
import unittest
from unittest.mock import patch
import networkx as nx

from graphify.exporters.html import to_html


class TestJevVisualRadar(unittest.TestCase):
    def setUp(self):
        self.G = nx.DiGraph()
        # 1. 恶性上帝类节点
        self.G.add_node("node_god", label="GodManager", source_file="server/god.py", community=1, docstring="承担全套异构业务")
        # 2. 良性基础设施节点
        self.G.add_node("node_infra", label="db_pool", source_file="server/db.py", community=2, docstring="纯连接池基础设施")
        # 3. 普通节点
        self.G.add_node("node_user", label="user_service", source_file="server/user.py", community=1)
        self.G.add_edge("node_god", "node_infra")
        self.G.add_edge("node_user", "node_god")
        self.communities = {1: ["node_god", "node_user"], 2: ["node_infra"]}

    @patch("graphify.jev_audit.is_available", return_value=True)
    @patch("graphify.jev_audit._call_jev_choice")
    def test_export_html_injects_health_radar(self, mock_choice, mock_avail):
        def side_effect(state_desc, instructions, criteria):
            if "代码符号：GodManager" in state_desc:
                return ("MALIGNANT_GOD_CLASS", 0.96, {"MALIGNANT_GOD_CLASS": 0.96, "BENIGN_INFRA": 0.04})
            return ("BENIGN_INFRA", 0.91, {"BENIGN_INFRA": 0.91, "MALIGNANT_GOD_CLASS": 0.09})
        mock_choice.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "graph.html")
            success = to_html(self.G, communities=self.communities, output_path=out_file)
            self.assertTrue(success)
            self.assertTrue(os.path.exists(out_file))

            content = open(out_file, encoding="utf-8").read()
            # 1. 验证节点数据中注入了 _is_malignant 与 _actionable_prompt
            self.assertIn("_is_malignant", content)
            self.assertIn("_actionable_prompt", content)
            # 2. 验证包含恶性发光样式
            self.assertIn("malignant-alert", content)
            # 3. 验证包含复制指令按钮与逻辑
            self.assertIn("copy-refactor-btn", content)


if __name__ == "__main__":
    unittest.main()
