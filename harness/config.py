"""配置加载：环境变量 / .env 文件。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    # ---- LLM ----
    # provider: "anthropic" | "deepseek" | "auto"（auto=有哪个 key 用哪个，都没有 → mock）
    llm_provider: str = "auto"
    anthropic_api_key: str | None = None
    model: str = "claude-opus-5"
    max_tokens: int = 16000
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"

    # ---- 高德 ----
    amap_key: str | None = None
    # 本地软熔断（次/天）：高德真实配额是月配额（搜索组个人 5,000/月），
    # 此值仅做防调试打爆的第一道闸，可经 AMAP_SOFT_LIMIT 调整
    amap_soft_limit: int = 200

    # ---- 位置兜底 ----
    default_city: str = "广州"
    default_radius: int = 5000

    # ---- 规则评分权重（开放调参）----
    scoring: dict = field(default_factory=lambda: {
        "bayes_prior_mean": 4.2,      # 评分贝叶斯先验均值
        "bayes_prior_count": 120,     # 先验评价数
        "budget_penalty_weight": 0.15,
        "distance_penalty_weight": 0.15,
        "match_bonus_max": 0.4,       # 菜系/菜品匹配加成上限
    })

    # ---- 澄清护栏 ----
    max_clarify_rounds: int = 2

    # ---- 搜索 ----
    search_page_size: int = 20

    # ---- 会话持久化 ----
    db_path: str = "data/checkpoints.db"

    # ---- 日志 ----
    log_level: str = "INFO"
    langsmith_enabled: bool = False

    @property
    def resolved_llm_provider(self) -> str:
        """实际走的 LLM：anthropic / deepseek / mock。"""
        if self.llm_provider in ("anthropic", "deepseek"):
            return self.llm_provider
        if self.anthropic_api_key:
            return "anthropic"
        if self.deepseek_api_key:
            return "deepseek"
        return "mock"

    @property
    def use_mock_llm(self) -> bool:
        """无任何模型 key 时退回规则抽取 + 模板推荐。"""
        return self.resolved_llm_provider == "mock"

    @property
    def use_mock_amap(self) -> bool:
        """无高德 key 时退回内置 mock 数据。"""
        return not self.amap_key

    def resolve_db_path(self) -> Path:
        if self.db_path == ":memory:":
            return Path(":memory:")
        p = Path(self.db_path)
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv(_PROJECT_ROOT / ".env")
        return cls(
            llm_provider=os.getenv("LLM_PROVIDER", "auto"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            amap_key=os.getenv("AMAP_KEY") or None,
            amap_soft_limit=int(os.getenv("AMAP_SOFT_LIMIT", "200")),
            model=os.getenv("MODEL", "claude-opus-5"),
            max_tokens=int(os.getenv("MAX_TOKENS", "16000")),
            default_city=os.getenv("DEFAULT_CITY", "广州"),
            default_radius=int(os.getenv("DEFAULT_RADIUS", "5000")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            langsmith_enabled=os.getenv("LANGSMITH_TRACING", "").lower()
            in ("1", "true", "yes"),
        )
