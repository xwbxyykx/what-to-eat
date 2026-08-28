"""score_candidates：确定性规则打分（非 LLM），产出 top-K + breakdown。"""
from __future__ import annotations

import structlog

from ..memory import poi_key
from ..state import ReqState

log = structlog.get_logger(__name__)

TOP_K = 5
_BUDGET_RANGE = {"便宜": (0, 60), "中档": (60, 150), "贵": (150, 10_000)}


def score_node(config, memory=None):
    w = config.scoring

    def _bayes(rating: float) -> float:
        prior_mean = w["bayes_prior_mean"]
        prior_count = w["bayes_prior_count"]
        # 高德 v3 不带评价数，用固定抽样数平滑（约 30 条）
        votes = 30.0
        return (prior_mean * prior_count + rating * votes) / (prior_count + votes)

    def _node(state: ReqState) -> dict:
        candidates = state.get("candidates", [])
        req = state.get("requirement") or {}
        budget = req.get("budget_preference")
        budget_range = _BUDGET_RANGE.get(budget, (0, 10_000))

        scored = []
        for c in candidates:
            rating = c.get("rating")
            cost = c.get("cost")
            missing_rating = rating is None

            base = 0.0 if missing_rating else _bayes(float(rating))

            # 预算偏差惩罚
            budget_pen = 0.0
            if budget and cost is not None:
                mid = (budget_range[0] + budget_range[1]) / 2
                budget_pen = -min(1.0, abs(cost - mid) / max(mid, 1e-6)) * w["budget_penalty_weight"]
            elif budget and cost is None:
                budget_pen = -0.05  # 未知人均，轻微惩罚

            # 距离惩罚
            dist = float(c.get("distance") or 0)
            norm = min(1.0, dist / 5000.0)
            dist_pen = -norm * w["distance_penalty_weight"]

            # 菜系/菜品匹配加成
            bonus = 0.0
            hay = f"{c.get('name', '')}{c.get('category', '')}"
            for cus in req.get("cuisine") or []:
                if cus and cus in hay:
                    bonus += 0.15
            for dish in req.get("dish") or []:
                if dish and dish in hay:
                    bonus += 0.2
            bonus = min(bonus, w["match_bonus_max"])

            total = base + budget_pen + dist_pen + bonus
            scored.append({
                "candidate": c,
                "score": round(total, 3),
                "breakdown": {
                    "base_quality": round(base, 3),
                    "budget_penalty": round(budget_pen, 3),
                    "distance_penalty": round(dist_pen, 3),
                    "match_bonus": round(bonus, 3),
                    "total": round(total, 3),
                },
                "missing_rating": missing_rating,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)

        top_k, note = _apply_dedupe(scored, state, memory)
        log.info("score_done", n=len(scored), top=len(top_k))
        out: dict = {"scored": scored, "top_k": top_k}
        if note:
            out["dedupe_note"] = note
        return out

    return _node


def _apply_dedupe(scored: list[dict], state: ReqState, memory) -> tuple[list[dict], str | None]:
    """多轮去重：仅在用户明确「换一家/再来一家」时，排除上一轮已推荐的店。

    设计纪律：
    - 先过滤再切片 —— 若先切片 top5 再过滤，第二轮会 5→0 直接回退成与上一轮相同的最优批。
    - 只排除上一轮 top-K（窗口有界，避免对固定池反复排除导致重复）。
    - 过滤后为空时才回退全量（此时已无新店可给，返回当前最优并诚实提示）。
    """
    if not (state.get("continuation_intent") and memory and memory.prev_recommended_keys):
        return scored[:TOP_K], None

    prev_keys = set(memory.prev_recommended_keys)
    filtered = [s for s in scored if poi_key(s["candidate"]) not in prev_keys]
    if filtered:
        return filtered[:TOP_K], None
    return (
        scored[:TOP_K],
        "该条件下符合条件的餐厅已经都推荐过了，这是当前最优的一批；换个条件或位置试试。",
    )
