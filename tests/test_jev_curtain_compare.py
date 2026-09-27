"""
单元测试：ComfyUI 风格无限画布激光卷帘对比导出器 (Curtain Compare Exporter Tests)
验证双层图数据打包、clip-path 硬件裁剪注入与战绩看板。
"""
import os
import tempfile
import unittest
import networkx as nx

from graphify.exporters.curtain_compare import to_curtain_compare_html


class TestCurtainCompareExporter(unittest.TestCase):
    def setUp(self):
        # 改造前图谱：包含恶性上帝类
        self.G_before = nx.DiGraph()
        self.G_before.add_node("build_from_json", label="build_from_json()", source_file="graphify/build.py", degree=246)
        self.G_before.add_node("n1", label="caller_1", source_file="cli.py", degree=2)
        self.G_before.add_edge("n1", "build_from_json")

        # 改造后图谱：上帝类消解，转为门面与管道
        self.G_after = nx.DiGraph()
        self.G_after.add_node("build_from_json", label="build_from_json()", source_file="graphify/build.py", degree=35)
        self.G_after.add_node("pipeline", label="ExtractionPreflight", source_file="graphify/build_pipeline.py", degree=10)
        self.G_after.add_edge("build_from_json", "pipeline")

    def test_to_curtain_compare_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "curtain_compare.html")
            ok = to_curtain_compare_html(
                self.G_before,
                self.G_after,
                out_file,
                project_title="测试卷帘对比大屏",
                score_stats={"malignant_before": 1, "malignant_after": 0, "max_deg_before": 246, "max_deg_after": 35, "coupling_drop": "85%", "rating_before": "D", "rating_after": "A+"}
            )
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(out_file))

            with open(out_file, "r", encoding="utf-8") as f:
                content = f.read()

            # 验证关键元素注入
            self.assertIn("badge-comfy", content)
            self.assertIn("main-canvas", content)
            self.assertIn("drawLaser", content)
            self.assertIn("NODES_BEFORE", content)
            self.assertIn("NODES_AFTER", content)
            self.assertIn("build_from_json()", content)
            self.assertIn("ExtractionPreflight", content)


if __name__ == "__main__":
    unittest.main()
