"""评分与推荐输出模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    base_quality: float = 0.0
    budget_penalty: float = 0.0
    distance_penalty: float = 0.0
    match_bonus: float = 0.0
    total: float = 0.0


class ScoredCandidate(BaseModel):
    candidate: dict
    score: float = 0.0
    breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    missing_rating: bool = False
