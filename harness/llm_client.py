"""LLM 客户端工厂：按 LLM_PROVIDER 切换 Anthropic / DeepSeek，都没有则 mock。

- ANTHROPIC_API_KEY → ChatAnthropic（claude-opus-5 + 自适应思考）
- DEEPSEEK_API_KEY   → ChatOpenAI（base_url 指向 DeepSeek，OpenAI 兼容接口）
- 都没有 → None，agent 层走规则抽取/模板推荐（mock 模式）

注意：本工厂只负责“构造不发起网络请求的 LLM 对象”；真实调用在节点里发生。
"""
from __future__ import annotations

import structlog
from langchain_core.language_models.chat_models import BaseChatModel

from .config import Config

log = structlog.get_logger(__name__)


def _build_anthropic(config: Config) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    try:
        llm = ChatAnthropic(
            model=config.model,
            max_tokens=config.max_tokens,
            thinking={"type": "adaptive"},
        )
    except (TypeError, ValueError):
        # 旧版 langchain-anthropic 不接受 thinking kwarg，去掉后重试
        llm = ChatAnthropic(model=config.model, max_tokens=config.max_tokens)
    log.info("llm_ready", provider="anthropic", model=config.model)
    return llm


def _build_deepseek(config: Config) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=config.deepseek_model,
        api_key=config.deepseek_api_key,
        base_url=config.deepseek_base_url,
        max_tokens=config.max_tokens,
        temperature=0.2,
    )
    log.info("llm_ready", provider="deepseek", model=config.deepseek_model)
    return llm


def build_chat_llm(config: Config) -> BaseChatModel | None:
    provider = config.resolved_llm_provider
    if provider == "mock":
        log.info("llm_mock_mode", reason="no model API key configured")
        return None
    if provider == "deepseek":
        return _build_deepseek(config)
    return _build_anthropic(config)
