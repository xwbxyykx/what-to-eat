"""extract_requirement：把自由文本解析为结构化需求槽位。"""
from __future__ import annotations

import json
import re

import structlog

from ..state import ReqState, Requirement

log = structlog.get_logger(__name__)

EXTRACT_SYSTEM = (
    "你是餐饮需求分析助手。从用户自然语言中抽取结构化吃饭需求。"
    "缺失的信息保持 None/空列表；若关键信息（位置）缺失，在 missing_required_slots 列出，"
    "并在 clarification_questions 给出一条最关键的追问（一次只问一个）。\n"
    "预算 budget_preference 只能填「便宜」「中档」「贵」三选一（映射人均区间），"
    "没有明确预算就留 None，不要用经济实惠/性价比/大众/高档等其他说法。"
)

_BUDGET_ALIASES = {
    "便宜": ("便宜", "经济实惠", "平价", "实惠", "高性价比", "性价比", "不贵", "省钱", "低价"),
    "中档": ("中档", "适中", "中等", "大众", "普通", "合理", "一般"),
    "贵": ("贵", "高端", "高档", "高价", "精品", "奢华", "品质"),
}


def _normalize_budget(value: str | None) -> str | None:
    """把 LLM 可能吐出的非规范预算词，映射回 「便宜/中档/贵」 三选一。

    否则 `_BUDGET_RANGE.get(非规范词, (0,10000))` 会兜底成无约束，预算精修静默失效。
    """
    if not value:
        return None
    v = str(value).strip()
    if v in ("便宜", "中档", "贵"):
        return v
    for canon, aliases in _BUDGET_ALIASES.items():
        if any(a in v for a in aliases):
            return canon
    return v


def _infer_budget(text: str) -> str | None:
    """从原始文本确定性推断预算（显式人均金额/词），不信任 LLM 的槽位映射。

    按「LLM只做两件事」纪律：显式价格是确定性信号，交给规则而非 LLM。
    """
    m = re.search(r"人均\s*(\d+)", text)
    if m:
        n = int(m.group(1))
        return "便宜" if n <= 50 else ("中档" if n <= 120 else "贵")
    if any(k in text for k in ("便宜", "平价", "经济实惠", "实惠")):
        return "便宜"
    if any(k in text for k in ("贵", "高端", "高档", "好一点")):
        return "贵"
    return None

# 多轮延续意图：出现这些表达时，score 节点才会排除上一轮已推荐的店
_CONTINUATION_WORDS = (
    "换一家", "再来一家", "换别的", "换点别的", "换一个", "换一批",
    "重新推荐", "还有别的吗", "还有吗", "再推荐",
)

_AREA_KEYWORDS = ("珠江新城", "体育西", "天河", "广州", "北京", "上海", "深圳")
# 「家」是合法位置词（在家附近），但会跟「换一家/再来一家/这家/那家/哪家」冲突，用负向断言守卫
_AMBIGUOUS_PLACE_RE = re.compile(r"(?<![一这那哪请尝好])家")


def _detect_continuation(raw: str) -> bool:
    """判断本轮是否「换一批/再来一家」类延续意图（用于去重门控）。"""
    return any(w in raw for w in _CONTINUATION_WORDS)


def _detect_location(text: str) -> str | None:
    """从文本抽位置描述。先匹配无歧义区域词；短词（家/公司/附近）用守卫避免误判。"""
    for kw in _AREA_KEYWORDS:
        if kw in text:
            return kw
    if _AMBIGUOUS_PLACE_RE.search(text):
        return "家"
    if "公司" in text:
        return "公司"
    if "附近" in text:
        return "附近"
    return None


def _union(a: list[str], b: list[str]) -> list[str]:
    out = list(a)
    for x in b:
        if x and x not in out:
            out.append(x)
    return out


def fallback_extract(raw_input: str) -> Requirement:
    """无 Claude key 时的规则抽取，保证最小闭环可跑通。"""
    text = raw_input
    req = Requirement()

    loc = _detect_location(text)
    if loc:
        req.location_desc = loc

    if any(k in text for k in ("辣", "麻辣", "川菜", "重庆")):
        if "川菜" not in req.cuisine:
            req.cuisine.append("川菜")
        if "辣" not in req.taste:
            req.taste.append("辣")
    if any(k in text for k in ("清淡", "粤菜", "广式", "早茶")):
        if "粤菜" not in req.cuisine:
            req.cuisine.append("粤菜")
        if "清淡" not in req.taste:
            req.taste.append("清淡")
    if "日式" in text or "拉面" in text:
        if "日式" not in req.cuisine:
            req.cuisine.append("日式")
    if "火锅" in text and "火锅" not in req.dish:
        req.dish.append("火锅")
    if "烤鱼" in text and "烤鱼" not in req.dish:
        req.dish.append("烤鱼")

    req.budget_preference = _infer_budget(text)

    if "聚餐" in text:
        req.scenario = "聚餐"
    elif "约会" in text:
        req.scenario = "约会"
    if "一个人" in text or "一人" in text or "独自" in text:
        req.party_size = 1

    if req.location_desc is None:
        req.missing_required_slots = ["位置"]
        req.clarification_questions = ["你大概在哪个位置？（如珠江新城、天河、公司附近）"]
    req.clarify_needed = bool(req.missing_required_slots)
    return req


def _merge_with_prev(req: Requirement, memory) -> Requirement:
    """把上一轮已确认的槽位确定性继承到本轮（位置/预算/菜系/口味/菜品）。

    只在上一轮存在需求时生效；用户本轮明确给出的槽位优先级更高（raw Requirement 已含）。
    关键：LLM 常会丢掉继承的位置（"换一家"），导致本轮又去澄清 —— 这里兜底填回并清零澄清需求。
    """
    if memory is None or not memory.prev_requirement:
        return req
    prev = memory.prev_requirement

    # 位置：本轮未给则继承上一轮（原始文本位置 > 上一轮定位城市兜底）
    if not req.location_desc:
        req.location_desc = prev.get("location_desc") or memory.prev_city
    # 预算：本轮未给则继承
    if not req.budget_preference:
        req.budget_preference = prev.get("budget_preference")
    # 菜系/口味/菜品：继承（并集，保留本轮新增）
    req.cuisine = _union(req.cuisine, prev.get("cuisine", []))
    req.taste = _union(req.taste, prev.get("taste", []))
    req.dish = _union(req.dish, prev.get("dish", []))

    if req.location_desc:
        # 位置已知 → 无需澄清（覆盖上一步的 missing 兜底判定）
        req.missing_required_slots = []
        req.clarification_questions = []
        req.clarify_needed = False
    else:
        req.clarify_needed = bool(req.missing_required_slots)
    return req


def _llm_extract(llm, raw_input: str, memory=None) -> Requirement:
    """用 LLM 结构化输出抽取；json_schema → function_calling 依次降级，再退回规则抽取。

    说明：DeepSeek（OpenAI 兼容）不一定支持 json_schema 输出格式，运行时可能 400，
    这里对 invoke 异常也兜底重试 function_calling（DeepSeek 支持函数调用）。
    """
    prev = (memory.prev_requirement if memory else None) or {}
    system = EXTRACT_SYSTEM
    if prev:
        system += (
            "\n【对话延续】上一轮已确认的需求是："
            f"{json.dumps(prev, ensure_ascii=False)}。"
            "请继承其中未被本轮明确修改的信息（尤其位置/菜系/口味/预算）；"
            "若本轮只是『换一家/再来一家/还有别的吗』这类相对表达，字段沿用上一轮、"
            "变化的只是候选范围。仍输出一份完整需求。"
        )

    messages = [("system", system), ("human", f"用户本轮输入：{raw_input}")]
    last_exc: Exception | None = None
    for method in ("json_schema", "function_calling"):
        try:
            structured = llm.with_structured_output(Requirement, method=method)
            result = structured.invoke(messages)
            return (
                result
                if isinstance(result, Requirement)
                else Requirement.model_validate(result)
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("llm_extract_retry", method=method, error=str(exc))
    raise last_exc  # 两种 method 都失败 → 节点层回退规则抽取


def extract_node(llm, memory=None):
    def _node(state: ReqState) -> dict:
        raw = state["raw_input"]
        if llm is not None:
            try:
                req = _llm_extract(llm, raw, memory)
            except Exception as exc:  # noqa: BLE001
                log.warning("llm_extract_failed_fallback", error=str(exc))
                req = fallback_extract(raw)
        else:
            req = fallback_extract(raw)

        # 关键：继承合并对 LLM 和规则两条路径都执行，覆盖 LLM 可能丢掉的继承槽位
        req = _merge_with_prev(req, memory)
        # 预算规范化：LLM 可能吐「经济实惠」等非规范词，映射回 便宜/中档/贵，否则评分静默失效
        req.budget_preference = _normalize_budget(req.budget_preference)
        # 确定性兜底：原文有显式「人均N元 / 便宜 / 贵」时最高优先，不信任 LLM 的槽位映射。
        # 只在本轮原文给出明确信号时覆盖（None 则保留上面继承/规范化的值）。
        _explicit_budget = _infer_budget(raw)
        if _explicit_budget:
            req.budget_preference = _explicit_budget

        # 确定性补齐「必需槽位」判定（不完全信任 LLM/规则）
        missing = list(req.missing_required_slots or [])
        if not req.location_desc and "位置" not in missing:
            missing.append("位置")
        req.missing_required_slots = missing
        req.clarify_needed = bool(missing)
        if missing and not req.clarification_questions:
            req.clarification_questions = ["你大概在哪个位置？（如珠江新城、天河、公司附近）"]

        return {
            "requirement": req.model_dump(),
            "location_desc": req.location_desc,
            "clarify_needed": req.clarify_needed,
            "continuation_intent": _detect_continuation(raw),
        }

    return _node
