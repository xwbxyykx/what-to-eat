"""eat_react 纯 ReAct agent 测试：用 ScriptedLLM 确定性驱动 ReAct 循环（无需任何 key）。

ScriptedLLM 是 BaseChatModel 子类，按脚本顺序每次吐出预设 AIMessage（先 tool_calls，后最终文本），
从而验证：工具确实被调用、ask_user 的 interrupt 挂起/恢复返回答案、多轮历史保留、无 key 明确报错。
"""
from __future__ import annotations

import unittest
import uuid
from typing import List

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agents.eat_react import build_graph
from harness.config import Config
from harness.core import Harness
from harness.io import CLI, run_graph_with_interrupts
from tools.amap import AmapClient, register_amap_tools


def _tool_call(name: str, args: dict, cid: str) -> dict:
    """构造一个 AIMessage.tool_calls 条目（含 langchain 要求的 type）。"""
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}


class ScriptedLLM(BaseChatModel):
    """Test double：每次 agent-node 调用按脚本顺序吐一条 AIMessage。

    必须覆写 bind_tools（BaseChatModel 默认会抛 NotImplementedError，实测 chat_models.py:2372），
    _llm_type 必须是 @property 而非类属性。
    """

    script: List[dict]
    _i: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self  # 脚本已自带 tool_calls，绑定为 no-op

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        step = self.script[min(self._i, len(self.script) - 1)]
        self._i += 1
        return ChatResult(generations=[ChatGeneration(message=AIMessage(**step))])


class FakeCLI:
    def __init__(self, answers: list[str] | None = None) -> None:
        self._a = iter(answers or [])
        self.out: list[str] = []

    def prompt(self, message: str) -> str:
        self.out.append(message)
        try:
            return next(self._a)
        except StopIteration:
            return ""

    def say(self, text: str) -> None:
        self.out.append(text)


def _make_harness(llm: BaseChatModel) -> Harness:
    config = Config(db_path=":memory:")  # 独立内存库，避免跨用例串污染
    harness = Harness(config)            # harness.llm 此时为 None（无 key）
    harness.llm = llm                    # 注入 ScriptedLLM —— 纯 ReAct 必须驱 LLM
    register_amap_tools(harness.tools, AmapClient(config.amap_key, default_city=config.default_city))
    return harness


class ReactAgentTest(unittest.TestCase):
    def test_geocode_search_then_recommend(self):
        """geocode + search 两个工具被调用，最终产出推荐文本。"""
        llm = ScriptedLLM(script=[
            {"content": "", "tool_calls": [
                _tool_call("amap_geocode", {"address": "珠江新城"}, "c1"),
                _tool_call("amap_search_around", {"location": "113.3228,23.1200", "keywords": "川菜"}, "c2"),
            ]},
            {"content": "推荐：川香居（川菜），人均68，评分4.6。"},
        ])
        app = build_graph(_make_harness(llm))
        r = run_graph_with_interrupts(
            app, FakeCLI([]), {"messages": [HumanMessage("珠江新城吃川菜")]}, f"t-{uuid.uuid4()}"
        )
        self.assertEqual(r["messages"][-1].content, "推荐：川香居（川菜），人均68，评分4.6。")
        tool_names = {getattr(m, "name", None) for m in r["messages"] if isinstance(m, ToolMessage)}
        self.assertIn("amap_geocode", tool_names)
        self.assertIn("amap_search_around", tool_names)

    def test_ask_user_interrupt_resumes_and_returns_answer(self):
        """ask_user 触发 interrupt 挂起，用户答案作为工具输出回到历史，并继续走完推荐。"""
        cli = FakeCLI(["珠江新城"])
        llm = ScriptedLLM(script=[
            {"content": "", "tool_calls": [_tool_call("ask_user", {"question": "你想去哪个位置？"}, "a1")]},
            {"content": "好的，那推荐珠江新城的川菜。"},
        ])
        app = build_graph(_make_harness(llm))
        r = run_graph_with_interrupts(
            app, cli, {"messages": [HumanMessage("随便吃点川菜")]}, f"t-{uuid.uuid4()}"
        )
        self.assertIn("位置", cli.out[0])  # CLI 确实向用户问了 question
        ask_msgs = [m for m in r["messages"] if isinstance(m, ToolMessage) and m.name == "ask_user"]
        self.assertTrue(ask_msgs and ask_msgs[-1].content == "珠江新城")
        self.assertEqual(r["messages"][-1].content, "好的，那推荐珠江新城的川菜。")

    def test_multi_turn_retains_history(self):
        """同一 session_thread：第二轮 messages 更长（checkpointer 保留历史）。"""
        llm = ScriptedLLM(script=[
            {"content": "", "tool_calls": [_tool_call("amap_geocode", {"address": "珠江新城"}, "g1")]},
            {"content": "第一轮推荐：川香居。"},
            {"content": "", "tool_calls": [_tool_call("amap_search_around", {"location": "113.3228,23.1200", "keywords": "粤菜"}, "s1")]},
            {"content": "第二轮推荐：粤味轩。"},
        ])
        app = build_graph(_make_harness(llm))
        thread = "mem-session-thread"
        r1 = run_graph_with_interrupts(app, FakeCLI([]), {"messages": [HumanMessage("珠江新城川菜")]}, thread)
        n1 = len(r1["messages"])
        r2 = run_graph_with_interrupts(app, FakeCLI([]), {"messages": [HumanMessage("换个粤菜")]}, thread)
        n2 = len(r2["messages"])
        self.assertGreater(n2, n1, "第二轮应保留第一轮的历史（messages 增长）")

    def test_no_key_raises_clear_error(self):
        """harness.llm=None（无 key）→ build_graph 明确抛错，而非静默降级。"""
        harness = Harness(Config(db_path=":memory:"))
        with self.assertRaisesRegex(RuntimeError, "ReAct"):
            build_graph(harness)


if __name__ == "__main__":
    unittest.main()
