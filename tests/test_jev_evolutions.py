import os
import unittest
from unittest.mock import patch
import networkx as nx

from graphify.jev_audit import audit_god_node_health, analyze_blast_radius
from graphify.jev_pruner import prune_bfs_neighbors_with_jev


class TestJevEvolutions(unittest.TestCase):
    def setUp(self):
        self.G = nx.DiGraph()
        # 构建一个带上下游调用的微服务测试图
        self.G.add_node("db_pool", label="get_db()", source_file="db.py", source_location="L5", docstring="数据库连接池")
        self.G.add_node("svc_user", label="UserService", source_file="user.py", source_location="L10", docstring="用户服务")
        self.G.add_node("api_login", label="login_route()", source_file="api.py", source_location="L20", docstring="登录路由")
        self.G.add_node("util_logger", label="log_info()", source_file="util.py", source_location="L1", docstring="日志打印工具")
        
        # 调用关系：api_login -> svc_user -> db_pool
        # svc_user -> util_logger
        self.G.add_edge("api_login", "svc_user", relation="calls")
        self.G.add_edge("svc_user", "db_pool", relation="calls")
        self.G.add_edge("svc_user", "util_logger", relation="calls")

    @patch("graphify.jev_audit._call_jev_choice")
    def test_evolution_3_god_node_benign_audit(self, mock_choice):
        """测试进化 3：良性基础设施确诊为 BENIGN_INFRA"""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake_key"}):
            mock_choice.return_value = ("BENIGN_INFRA", 0.95, {"BENIGN_INFRA": 0.95})
            res = audit_god_node_health(self.G, "db_pool")
            self.assertEqual(res["diagnosis"], "BENIGN_INFRA")
            self.assertFalse(res["is_malignant"])
            self.assertIn("保持现状", res["refactor_advice"])

    def test_evolution_2_blast_radius_reverse_trace(self):
        """测试进化 2：逆向影响面分析（改动 db_pool 将连锁波及 svc_user 与 api_login）"""
        report = analyze_blast_radius(self.G, "get_db", max_depth=2)
        self.assertEqual(report["target_symbol"], "get_db()")
        self.assertEqual(report["blast_radius_score"], 2)
        # 第 1 跳受影响者必须包含 svc_user
        direct_callers = [item for c in report["chains"] if c["depth"] == 1 for item in c["affected"]]
        self.assertTrue(any("UserService" in s for s in direct_callers))
        # 第 2 跳受影响者必须包含 api_login
        indirect_callers = [item for c in report["chains"] if c["depth"] == 2 for item in c["affected"]]
        self.assertTrue(any("login_route" in s for s in indirect_callers))

    @patch("graphify.jev_pruner._call_jev_choice")
    def test_evolution_1_bfs_smart_pruning(self, mock_choice):
        """测试进化 1：BFS 扩散时智能修枝，过滤掉日志杂草"""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake_key"}):
            mock_choice.return_value = ("db_pool", 0.99, {"db_pool": 0.99})
            raw_neighbors = ["db_pool", "util_logger", "n3", "n4", "n5", "n6"]
            # 添加打杂节点
            for n in ["n3", "n4", "n5", "n6"]:
                self.G.add_node(n, label=n, source_file="util.py", docstring="工具")
                self.G.add_edge("svc_user", n, relation="calls")
                
            kept = prune_bfs_neighbors_with_jev(self.G, "svc_user", raw_neighbors, "数据库存储操作", max_keep=3)
            self.assertIn("db_pool", kept)
            self.assertLessEqual(len(kept), 3)


if __name__ == "__main__":
    unittest.main()
