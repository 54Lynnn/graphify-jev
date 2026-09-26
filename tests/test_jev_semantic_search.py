import os
import unittest
from unittest.mock import patch, MagicMock
import networkx as nx

from graphify.jev_bridge import is_available, pick_seeds_with_jev, _call_jev_choice
from graphify.serve import _query_graph_text


class TestJevBridge(unittest.TestCase):
    def setUp(self):
        self.G = nx.Graph()
        # 构建一个包含两个独立社区的测试图
        # 社区 1: auth
        self.G.add_node("auth_service", label="auth_service.py", file_type="code", source_file="services/auth.py", source_location="L1")
        self.G.add_node("fn_login", label="login()", source_file="services/auth.py", source_location="L10", docstring="用户登录")
        self.G.add_node("fn_token", label="refresh_token()", source_file="services/auth.py", source_location="L20", docstring="刷新Token")
        self.G.add_edge("auth_service", "fn_login", relation="contains")
        self.G.add_edge("auth_service", "fn_token", relation="contains")

        # 社区 2: payment
        self.G.add_node("payment_service", label="payment.py", file_type="code", source_file="services/payment.py", source_location="L1")
        self.G.add_node("fn_pay", label="pay()", source_file="services/payment.py", source_location="L10", docstring="发起支付")
        self.G.add_edge("payment_service", "fn_pay", relation="contains")

    def test_fail_open_when_no_api_key(self):
        """测试在无 API KEY 时，严格 fail-open 返回 None，不抛出异常"""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "", "OPENCODE_API_KEY": ""}, clear=True):
            self.assertFalse(is_available())
            seeds = pick_seeds_with_jev(self.G, "用户登录")
            self.assertIsNone(seeds)

    def test_fail_open_on_network_error(self):
        """测试网络超时或异常时，静默返回 None"""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake_key"}):
            with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
                res = _call_jev_choice("state", "instr", {"opt1": "desc1"})
                self.assertIsNone(res)
                seeds = pick_seeds_with_jev(self.G, "用户登录")
                self.assertIsNone(seeds)

    @patch("graphify.jev_bridge._call_jev_choice")
    def test_successful_two_stage_picking(self, mock_choice):
        """测试在 JEV 正常响应时，成功完成两阶段语义寻种"""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake_key"}):
            # 阶段 1 返回社区 0，阶段 2 返回 fn_token
            mock_choice.side_effect = [
                ("0", 0.95),        # 阶段 1: 社区 0
                ("fn_token", 0.99)  # 阶段 2: 目标节点
            ]
            seeds = pick_seeds_with_jev(self.G, "刷新Token凭证")
            self.assertEqual(seeds, ["fn_token"])

    def test_query_graph_text_integration(self):
        """测试 _query_graph_text 在 JEV 不可用时正常回退到原生分词搜索"""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "", "OPENCODE_API_KEY": ""}, clear=True):
            output = _query_graph_text(self.G, "login", mode="bfs", depth=1)
            self.assertIn("login()", output)
            self.assertIn("Traversal: BFS", output)


if __name__ == "__main__":
    unittest.main()
