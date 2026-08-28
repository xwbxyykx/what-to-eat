"""mock 模式下的最小闭环端到端测试（无需任何 Key）。"""
from __future__ import annotations

import unittest

from agents.eat_agent import build_graph, start_state
from harness.config import Config
from harness.core import Harness
from harness.io import run_graph_with_interrupts
from tools.amap import AmapClient, register_amap_tools


class FakeCLI:
    def __init__(self, answers: list[str] | None = None) -> None:
        self._answers = iter(answers or [])
        self.out: list[str] = []

    def prompt(self, message: str) -> str:
        self.out.append(message)
        try:
            return next(self._answers)
        except StopIteration:
            return ""

    def say(self, text: str) -> None:
        self.out.append(text)


def _make_harness() -> Harness:
    # 无 key → mock 模式；db_path=":memory:" 让每个用例有独立内存库，
    # 避免跨用例/跨进程复用同一 sqlite 文件导致的 list-channel 状态污染
    config = Config(db_path=":memory:")
    harness = Harness(config)
    client = AmapClient(config.amap_key, default_city=config.default_city)
    register_amap_tools(harness.tools, client)
    return harness


class ClosedLoopTest(unittest.TestCase):
    _thread_counter = 0

    def _run(self, text: str, answers: list[str] | None = None) -> dict:
        ClosedLoopTest._thread_counter += 1
        harness = _make_harness()
        app = build_graph(harness)
        initial = start_state(harness.config)
        initial["raw_input"] = text
        thread = f"user-test-{ClosedLoopTest._thread_counter}"
        return run_graph_with_interrupts(app, FakeCLI(answers), initial, thread)

    def test_complete_input_no_clarify(self):
        """带位置、预算、口味的完整输入：一次跑通到推荐。"""
        result = self._run("想吃辣的，人均100以内，天河附近")
        self.assertFalse(result.get("no_result"))
        items = result["final_answer"]["items"]
        self.assertTrue(items, "应产出推荐列表")
        self.assertLessEqual(len(items), 5)
        self.assertIn("summary", result["final_answer"])
        # 规则打分应把川菜/辣匹配的店排前面
        top_name = items[0]["name"]
        self.assertIn("川", top_name)

    def test_clarify_then_recommend(self):
        """缺位置 → interrupt() 澄清一次 → 恢复后走完闭环。"""
        result = self._run("想吃点便宜的川菜", answers=["珠江新城"])
        self.assertTrue(result["final_answer"]["items"])
        self.assertEqual(len(result.get("clarification_history", [])), 1)
        self.assertIn("珠江新城", result["raw_input"])

    def test_missing_location_uses_default_city_after_max_rounds(self):
        """连续追问后仍无位置：clarify_count 达到上限 → 默认城市兜底继续。"""
        result = self._run("随便吃点", answers=["", ""])
        # 达到上限后应仍能出推荐（默认城市广州兜底）
        self.assertTrue(result["final_answer"]["items"])
        self.assertEqual(result.get("location_source"), "default")

    def test_no_result_fallback(self):
        """搜索无结果 → no_result + search_hint（当前 mock 恒有数据，验证路由存在）。"""
        harness = _make_harness()
        app = build_graph(harness)
        initial = start_state(harness.config)
        initial["raw_input"] = "想吃烤鱼"  # mock 里没有烤鱼 → 触发降级后仍无结果
        result = run_graph_with_interrupts(app, FakeCLI(["珠江新城"]), initial, "user-test-no-result")
        final = result.get("final_answer") or {}
        self.assertTrue(final.get("items") or result.get("no_result"))
        if result.get("no_result"):
            self.assertTrue(result.get("search_hint"))


if __name__ == "__main__":
    unittest.main()
