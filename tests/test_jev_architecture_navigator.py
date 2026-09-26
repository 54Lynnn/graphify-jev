"""
单元测试：Jev 架构健康雷达与重构导航器 (Architecture Health Radar & Refactoring Navigator)
验证全库核心中枢健康扫描、恶性上帝类识别、Fail-safe 降级机制以及重构拓扑切片提取。
"""
import unittest
from unittest.mock import patch
import networkx as nx

from graphify.jev_audit import (
    scan_project_architecture_health,
    get_refactor_context,
)


class TestJevArchitectureNavigator(unittest.TestCase):
    def setUp(self):
        # 构建一个模拟的多模块微服务调用图
        self.G = nx.DiGraph()
        
        # 1. 恶性上帝类：OrderGodManager (跨多模块重度纠缠)
        self.G.add_node("node_order_god", label="OrderGodManager", source_file="server/order_god.py", community=1, docstring="处理订单、用户、支付、发票全套业务")
        
        # 2. 良性基础设施：get_db (纯单例基础设施)
        self.G.add_node("node_get_db", label="get_db", source_file="server/db.py", community=2, docstring="数据库连接池工厂")
        
        # 3. 若干调用方和下游业务
        self.G.add_node("node_auth", label="verify_token", source_file="server/auth.py", community=3)
        self.G.add_node("node_pay", label="execute_payment", source_file="server/pay.py", community=4)
        self.G.add_node("node_user", label="get_user", source_file="server/user.py", community=5)
        self.G.add_node("node_api", label="order_route", source_file="server/api.py", community=1)
        
        # 连线：OrderGodManager 被大量节点调用，同时也调用下游
        self.G.add_edge("node_api", "node_order_god")
        self.G.add_edge("node_user", "node_order_god")
        self.G.add_edge("node_order_god", "node_auth")
        self.G.add_edge("node_order_god", "node_pay")
        self.G.add_edge("node_order_god", "node_get_db")
        self.G.add_edge("node_auth", "node_get_db")
        self.G.add_edge("node_pay", "node_get_db")
        self.G.add_edge("node_user", "node_get_db")

    @patch("graphify.jev_audit.is_available", return_value=True)
    @patch("graphify.jev_audit._call_jev_choice")
    def test_scan_architecture_health_with_jev(self, mock_choice, mock_avail):
        # 模拟 Jev 做出定性判断：OrderGodManager 为恶性病灶，get_db 为良性工具
        def side_effect(state_desc, instructions, criteria):
            if "代码符号：OrderGodManager" in state_desc:
                return ("MALIGNANT_GOD_CLASS", 0.95, {"MALIGNANT_GOD_CLASS": 0.95, "BENIGN_INFRA": 0.05})
            return ("BENIGN_INFRA", 0.92, {"BENIGN_INFRA": 0.92, "MALIGNANT_GOD_CLASS": 0.08})
        
        mock_choice.side_effect = side_effect

        report = scan_project_architecture_health(self.G, top_n=2)
        
        self.assertEqual(report["total_scanned"], 2)
        malignant = report["malignant_nodes"]
        benign = report["benign_nodes"]
        
        self.assertEqual(len(malignant), 1)
        self.assertEqual(malignant[0]["label"], "OrderGodManager")
        self.assertTrue(malignant[0]["is_malignant"])
        self.assertIn("server/order_god.py", malignant[0]["source_file"])
        self.assertIn("actionable_prompt", malignant[0])
        
        self.assertEqual(len(benign), 1)
        self.assertEqual(benign[0]["label"], "get_db")
        self.assertFalse(benign[0]["is_malignant"])

    @patch("graphify.jev_audit.is_available", return_value=False)
    def test_scan_architecture_health_failsafe_offline(self, mock_avail):
        # 测试在无 JEV API Key 时优雅降级，绝不崩溃
        report = scan_project_architecture_health(self.G, top_n=2)
        self.assertEqual(report["mode"], "failsafe_heuristic")
        self.assertGreaterEqual(report["total_scanned"], 1)
        self.assertIn("failsafe_note", report)

    def test_get_refactor_context(self):
        # 测试获取重构拓扑切片
        ctx = get_refactor_context(self.G, "OrderGodManager")
        self.assertFalse(ctx.get("error"))
        self.assertEqual(ctx["target_label"], "OrderGodManager")
        self.assertIn("callers", ctx)
        self.assertIn("callees", ctx)
        # 检查上游调用方包含 order_route 和 get_user
        caller_labels = [c["label"] for c in ctx["callers"]]
        self.assertIn("order_route", caller_labels)
        self.assertIn("get_user", caller_labels)
        # 检查下游被调包含 verify_token, execute_payment, get_db
        callee_labels = [c["label"] for c in ctx["callees"]]
        self.assertIn("verify_token", callee_labels)
        self.assertIn("execute_payment", callee_labels)

    @patch("graphify.jev_audit.is_available", return_value=True)
    @patch("graphify.jev_audit._call_jev_choice")
    def test_report_includes_health_radar(self, mock_choice, mock_avail):
        # 验证 generate_report 是否成功挂载 Jev 架构健康雷达
        def side_effect(state_desc, instructions, criteria):
            if "代码符号：OrderGodManager" in state_desc:
                return ("MALIGNANT_GOD_CLASS", 0.95, {"MALIGNANT_GOD_CLASS": 0.95, "BENIGN_INFRA": 0.05})
            return ("BENIGN_INFRA", 0.92, {"BENIGN_INFRA": 0.92, "MALIGNANT_GOD_CLASS": 0.08})
        mock_choice.side_effect = side_effect

        from graphify.report import generate
        communities = {1: ["node_order_god", "node_api"], 2: ["node_get_db"]}
        report_md = generate(
            self.G,
            communities=communities,
            cohesion_scores={},
            community_labels={1: "Order", 2: "Database"},
            god_node_list=[],
            surprise_list=[],
            detection_result={"total_files": 2, "total_words": 100},
            token_cost={},
            root="test_project",
        )
        
        self.assertIn("Jev 架构健康雷达", report_md)
        self.assertIn("OrderGodManager", report_md)
        self.assertIn("健全基础设施", report_md)
        self.assertIn("get_db", report_md)
        self.assertIn("Agent 导航指令", report_md)


if __name__ == "__main__":
    unittest.main()
