"""LLM provider 切换逻辑：anthropic / deepseek / mock 的解析与构造（不发起网络请求）。"""
from __future__ import annotations

import unittest

from harness.config import Config
from harness.llm_client import build_chat_llm


class LLMProviderTest(unittest.TestCase):
    def test_auto_prefers_anthropic(self):
        c = Config(anthropic_api_key="sk-ant-test", deepseek_api_key="sk-deep-test")
        self.assertEqual(c.resolved_llm_provider, "anthropic")
        self.assertFalse(c.use_mock_llm)

    def test_auto_falls_to_deepseek(self):
        c = Config(deepseek_api_key="sk-deep-test")
        self.assertEqual(c.resolved_llm_provider, "deepseek")
        self.assertFalse(c.use_mock_llm)

    def test_mock_when_no_keys(self):
        c = Config()
        self.assertEqual(c.resolved_llm_provider, "mock")
        self.assertTrue(c.use_mock_llm)
        self.assertIsNone(build_chat_llm(c))

    def test_explicit_provider_overrides_auto(self):
        c = Config(llm_provider="deepseek", anthropic_api_key="sk-ant-test")
        self.assertEqual(c.resolved_llm_provider, "deepseek")

    def test_build_deepseek_returns_chat_openai(self):
        c = Config(deepseek_api_key="sk-deep-test")
        llm = build_chat_llm(c)
        self.assertIsNotNone(llm)
        self.assertEqual(llm.__class__.__name__, "ChatOpenAI")

    def test_build_anthropic_returns_chat_anthropic(self):
        c = Config(anthropic_api_key="sk-ant-test")
        llm = build_chat_llm(c)
        self.assertIsNotNone(llm)
        self.assertEqual(llm.__class__.__name__, "ChatAnthropic")


if __name__ == "__main__":
    unittest.main()
