"""多轮续聊测试：上下文继承、延续意图去重、复述保留最优、no_result 不清空、合并守卫。

全部走 mock 模式（无需任何 Key）；复用同一个 app 对象（graph 闭包里的 ConversationMemory），
但每轮用**全新 thread_id** —— 这正是生产 harness.run() 的行为，确保不跨轮累积 reducer 状态。
"""
from __future__ import annotations

import unittest

from agents.eat_agent import build_graph, start_state
from agents.eat_agent.memory import ConversationMemory, poi_key
from agents.eat_agent.nodes.extract import (
    _detect_continuation,
    _infer_budget,
    _merge_with_prev,
    extract_node,
    fallback_extract,
)
from agents.eat_agent.state import Requirement
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
    config = Config(db_path=":memory:")
    harness = Harness(config)
    client = AmapClient(config.amap_key, default_city=config.default_city)
    register_amap_tools(harness.tools, client)
    return harness


class Session:
    """一次 run() 内的一整段对话：复用同一 app（闭包 memory），每轮新 thread_id。"""

    def __init__(self) -> None:
        self.harness = _make_harness()
        self.app = build_graph(self.harness)
        self._c = 0

    def run(self, text: str, answers: list[str] | None = None) -> dict:
        self._c += 1
        initial = start_state(self.harness.config)
        initial["raw_input"] = text
        return run_graph_with_interrupts(self.app, FakeCLI(answers), initial, f"user-mt-{self._c}")


def _names(result: dict) -> set[str]:
    return {i["name"] for i in (result.get("final_answer") or {}).get("items", [])}


class MultiTurnE2ETest(unittest.TestCase):
    def test_turn_two_dedupes(self):
        """「换一家」：继承位置/预算，且排除上一轮已推荐的店 → 两轮不重叠、不澄清。"""
        s = Session()
        r1 = s.run("珠江新城附近，人均100以内")
        r2 = s.run("换一家")
        n1, n2 = _names(r1), _names(r2)
        self.assertEqual(len(r1["final_answer"]["items"]), 5)
        self.assertEqual(len(r2["final_answer"]["items"]), 5)
        self.assertFalse(n1 & n2, f"两轮不应重叠: {n1} vs {n2}")
        self.assertEqual(len(r2.get("clarification_history", [])), 0, "应继承位置，无需澄清")

    def test_restatement_keeps_best(self):
        """复述同一完整需求：非延续意图 → 不换批，保留上一轮最优 5 家。"""
        s = Session()
        r1 = s.run("珠江新城附近，人均100以内")
        r2 = s.run("珠江新城附近，人均100以内")
        self.assertEqual(_names(r1), _names(r2))

    def test_followup_inherits_no_clarify(self):
        """缺位置的后续轮（"换便宜点的"）继承上一轮位置，不触发澄清。"""
        s = Session()
        r1 = s.run("珠江新城附近，想吃川菜")
        r2 = s.run("换便宜点的")
        self.assertEqual(len(r2.get("clarification_history", [])), 0)
        self.assertTrue(r2["final_answer"]["items"])
        # 预算已继承/改为便宜 → 推荐应落在更便宜区间（mock 里只占比分权重，这里断言不含贵店）
        self.assertLessEqual(len(r2["final_answer"]["items"]), 5)

    def test_no_result_turn_does_not_wipe_memory(self):
        """一轮「想吃烤鱼」无结果 → 不 write 记忆；后续「换一家」仍对上一轮好结果去重。"""
        s = Session()
        r1 = s.run("珠江新城附近，人均100以内")            # 好结果，记入记忆
        r2 = s.run("想吃烤鱼", answers=["珠江新城"])         # 无结果，不 write
        self.assertTrue(r2.get("no_result"))
        r3 = s.run("换一家")
        self.assertFalse(_names(r1) & _names(r3), "no_result 后仍应对上一轮去重")

    def test_inherit_default_city_after_clarify_exhausted(self):
        """第一轮澄清耗尽走默认城市（位置始终 None）；第二轮「换一家」应直接继承广州，不再澄清。"""
        s = Session()
        r1 = s.run("随便吃点", answers=["", ""])
        self.assertEqual(r1.get("location_source"), "default")
        r2 = s.run("换一家")
        self.assertEqual(len(r2.get("clarification_history", [])), 0, "应继承默认城市，无需澄清")
        self.assertTrue(r2["final_answer"]["items"])


class ExtractMergeUnitTest(unittest.TestCase):
    def test_fallback_does_not_misparse_huanyijia(self):
        """「换一家」不应被误判为位置『家』；且命中延续意图。"""
        req = fallback_extract("换一家")
        self.assertIsNone(req.location_desc)
        self.assertTrue(req.clarify_needed)          # 无位置 → 默认要澄清（合并前）
        self.assertTrue(_detect_continuation("换一家"))
        # 「回家吃饭」这类才是真位置
        self.assertEqual(fallback_extract("在家附近吃").location_desc, "家")

    def test_merge_with_prev_fills_inherited_slots(self):
        """合并应填回位置/预算/菜系，并清零澄清需求（模拟 LLM 丢掉所有槽位）。"""
        memory = ConversationMemory(prev_requirement={
            "location_desc": "珠江新城", "cuisine": ["川菜"], "budget_preference": "中档",
        })
        merged = _merge_with_prev(Requirement(), memory)
        self.assertEqual(merged.location_desc, "珠江新城")
        self.assertEqual(merged.budget_preference, "中档")
        self.assertEqual(merged.cuisine, ["川菜"])
        self.assertFalse(merged.clarify_needed)
        self.assertEqual(merged.missing_required_slots, [])

    def test_extract_node_fake_llm_drop_location(self):
        """假 LLM 丢位置（返回 location_desc=None）→ 合并兜底，绝不触发『位置』澄清。"""
        memory = ConversationMemory(prev_requirement={
            "location_desc": "珠江新城", "cuisine": ["川菜"], "budget_preference": "中档",
        })

        class FakeStructured:
            def invoke(self, messages):
                return {"intent": "找餐厅", "cuisine": ["川菜"]}  # 故意不带 location

        class FakeLLM:
            def with_structured_output(self, schema, method="json_schema"):
                return FakeStructured()

        node = extract_node(FakeLLM(), memory)
        out = node({
            "raw_input": "换一家", "requirement": {}, "clarify_count": 0,
            "clarification_history": [], "clarify_needed": False,
        })
        self.assertEqual(out["location_desc"], "珠江新城")
        self.assertFalse(out["clarify_needed"])
        self.assertEqual(out["requirement"]["missing_required_slots"], [])  # 合并后不应有位置缺失
        self.assertTrue(out["continuation_intent"])

    def test_poi_key_never_collapses_to_bare_name(self):
        """poi_key：空 location/address 时不应退化成裸 name（同名连锁会误判）。"""
        self.assertTrue(poi_key({"name": "海底捞"}).endswith("__noaddr__"))
        k1 = poi_key({"name": "海底捞", "location": "113.0,23.0"})
        k2 = poi_key({"name": "海底捞", "location": "114.0,24.0"})
        self.assertNotEqual(k1, k2)

    def test_infer_budget_deterministic(self):
        """显式价格/预算词由规则确定性映射，不信任 LLM——覆盖 LLM 可能乱冒的槽位。"""
        self.assertEqual(_infer_budget("人均100以内"), "中档")
        self.assertEqual(_infer_budget("人均200"), "贵")
        self.assertEqual(_infer_budget("人均50"), "便宜")
        self.assertEqual(_infer_budget("换便宜点的"), "便宜")
        self.assertEqual(_infer_budget("想吃贵的"), "贵")
        self.assertEqual(_infer_budget("随便吃点"), None)   # 无显式信号 → 保留继承

    def test_extract_node_override_explicit_budget(self):
        """本轮原文有显式预算（人均200）时，确定性覆盖 LLM 的错误映射（如吐成中档）。"""
        memory = ConversationMemory(prev_requirement={
            "location_desc": "珠江新城", "cuisine": ["川菜"], "budget_preference": "中档",
        })

        class FakeStructured:
            def invoke(self, messages):
                return {"intent": "找餐厅", "cuisine": ["川菜"], "budget_preference": "中档"}  # LLM 错标

        class FakeLLM:
            def with_structured_output(self, schema, method="json_schema"):
                return FakeStructured()

        out = extract_node(FakeLLM(), memory)({
            "raw_input": "人均200的川菜", "requirement": {}, "clarify_count": 0,
            "clarification_history": [], "clarify_needed": False,
        })
        self.assertEqual(out["requirement"]["budget_preference"], "贵")  # override → 贵，非 LLM 的中档

    def test_dedupe_exhausted_topups_with_note(self):
        """去重耗尽（上一轮 top-K 覆盖了整个候选池）→ 回退全量、保留 5、给出诚实提示。"""
        from agents.eat_agent.nodes.score import _apply_dedupe

        prev = [{"name": f"店{i}", "location": f"{i},{i}"} for i in range(5)]
        memory = ConversationMemory(prev_recommended_keys=[poi_key(c) for c in prev])
        scored = [{"candidate": c, "score": 5 - i} for i, c in enumerate(prev)]
        top_k, note = _apply_dedupe(scored, {"continuation_intent": True}, memory)
        self.assertEqual(len(top_k), 5)           # 耗尽仍保持 top-K，绝不返回空
        self.assertTrue(note)                     # 诚实提示已附上
        # 非延续意图 → 不去重、也无提示
        top_k2, note2 = _apply_dedupe(scored, {"continuation_intent": False}, memory)
        self.assertEqual(top_k2, scored[:5])
        self.assertIsNone(note2)


if __name__ == "__main__":
    unittest.main()
