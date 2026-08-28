# 「寻找吃饭目的地」Agent + Harness 框架 — 设计方案（v0.1）

> 目标：先实现一个**可行的最小闭环**——用户文本输入 → 需求分析 → 位置解析 → 饭店搜索 → 评分推荐 → 输出。
> 本文档是设计基线，实现过程中对细节有改动时同步更新本文档。

- 日期：2026-08-20
- 语言：Python（≥3.10，建议 3.12）
- 核心 LLM：Claude API（`claude-opus-5`）
- 位置/饭店数据源：高德地图 Web服务 API（v3 为主）
- 交互：纯文本 CLI；澄清采用 LangGraph `interrupt()` 挂起/恢复

---

## 1. 已确认决策

| 决策项 | 结论 | 说明 |
|---|---|---|
| Harness 框架 | 自研通用 agent 外壳 | 配置/LLM客户端/工具注册/会话记忆/I-O/日志 六件套，不感知业务；LangGraph agent 作为可插拔组件注册进去 |
| 核心 LLM | Claude API | Python 接入，`ChatAnthropic(model="claude-opus-5")`，首选 `with_structured_output(method="json_schema")` |
| 数据源 | 高德地图 Web服务 API | POI 周边搜索 + 文本搜索 + 地理编码 + 逆地理编码；MVP 锁 v3 |
| 交互形式 | 纯文本输入 | MVP 走 CLI REPL |
| 澄清方式 | `interrupt()` 挂起/恢复 | 需求不明确时图暂停，追问用户，`Command(resume=...)` 恢复后重抽 |
| 默认城市 | **广州** | `DEFAULT_CITY`，位置缺失时兜底并提示用户确认 |
| MVP 目标 | 最小闭环 | 见 §9 MVP 范围 |

---

## 2. 核心设计纪律

> **LLM 只做两件事：① 把自然语言需求解析成结构化槽位；② 对最终 top-K 候选生成推荐解释。**
> 坐标解析、饭店召回、评分排序——**全部交给确定性代码和高德 API**，LLM 绝不造坐标、绝不编饭店。

依据（同类系统实证）：

- LLM 读的是文本不是地图，**83% 的餐厅不在训练数据里**；AI 推荐覆盖率极低，强制锚定坐标反而让幻觉率 +23%。
- LLM 直接做排序有固有缺陷：约 **30% 位置偏差**、约 **10% 输出格式不对齐**、约 **1% 幻觉**（生成不存在的店/菜）。
- 排序的"准度"交给确定性规则引擎承担（约 80% 的检索质量由排序算法决定），LLM 只做最终润色。

**衍生约束**：候选必须严格限定在高德真实返回集内；坐标只来自高德 geocode；评分缺失项不硬排。

---

## 3. 三层架构

```
┌─────────────────────────────────────────────────────────┐
│ ① Harness 框架（通用外壳，不感知业务）                     │
│   config · llm_client · tool_registry · session · io ·   │
│   logging/tracing —— register_tool() / register_agent()   │
├─────────────────────────────────────────────────────────┤
│ ② LangGraph 推荐 Agent（可插拔业务组件）                   │
│   需求抽取 → 澄清回环 → 定位 → 搜索 → 规则评分 → LLM推荐     │
├─────────────────────────────────────────────────────────┤
│ ③ 高德工具层（确定性数据源）                                │
│   geocode / regeo / place_around / place_text（v3 为主）   │
└─────────────────────────────────────────────────────────┘
```

依赖方向单向向下：harness 不感知业务；agent 只依赖注入的 `llm_client` 与 `tool_registry`；工具层无业务逻辑。

---

## 4. LangGraph 节点图（6 节点 + 条件回环）

```
START → [extract_requirement] ── 需求不明确且澄清次数<上限 ──→ [clarify] ─┐
            │                                                        │ 补充后
            │ 否则（清晰）                                             │ 重抽
            ▼                                                        ▼
       [resolve_location] ── 定位失败 ──→ [clarify]
            │
            ▼
       [search_restaurants] ── 无结果 → 降级重试(扩大半径→文本搜索) → 兜底文案→END
            │
            ▼
       [score_candidates]  ← 规则打分（非 LLM），输出 top-K=5 + breakdown
            │
            ▼
       [recommend]  ← LLM 只对 top-K 生成带理由的推荐（引用真实 POI 字段）
            ▼
            END
```

### 节点规格

| 节点 | LLM? | 职责 | 产出 |
|---|---|---|---|
| `extract_requirement` | ✅ | 自由文本 → 结构化槽位（菜系/菜品/口味/位置/预算/人数/场景/忌口/评分门槛），判是否需澄清 | 覆盖写 `requirement`；输出 `clarify_needed`、`missing_required_slots`、`clarification_questions` |
| `clarify` | ✅ | 一次只追问最关键 1 个缺失槽位 + 推荐选项；`clarify_count` 上限 2-3 次防死循环；"随便/都可以"走默认 | `interrupt()` 挂起；恢复后追加 `clarification_history`，回 `extract_requirement` 重抽 |
| `resolve_location` | ❌ | `amap_geocode` 把位置描述解析为 GCJ-02 坐标；已是坐标直接用；缺失用 DEFAULT_CITY=广州兜底 | 更新 `location`、`city`、`radius`；失败置 `location_error=true` |
| `search_restaurants` | ❌ | `amap_place_around`（types=050000 餐饮）+ 文本搜索降级 | 追加 `candidates`（reducer 累积）；无结果置 `search_hint` |
| `score_candidates` | ❌ | 硬过滤 + 规则打分（见 §6） | 追加 `scored`（候选+score+breakdown）；覆盖写 `top_k` |
| `recommend` | ✅ | 对 top-K 生成带理由的推荐（引用真实 POI 字段） | 覆盖写 `final_answer` → END |

### 条件路由（`add_conditional_edges` + `path_map` 必须覆盖所有返回值）

1. **抽取后**：`clarify_needed` 或缺失必需槽位且 `clarify_count<上限` → `clarify`；否则 → `resolve_location`
2. **定位失败**：`location_error=true` → `clarify`（一次只问"位置是哪里/哪个城市"）；有默认城市则降级用广州坐标继续
3. **搜索后**：`candidates` 为空/过少 → 回 `search` 并调整参数（扩大 radius → `place/text` 文本搜索 → 放宽关键词）；仍无结果 → END 兜底文案
4. **评分后**：无条件边 → `recommend` → END

---

## 5. State 设计

**纪律**：累积类列表字段必须用 `Annotated[list, operator.add]` 追加（否则默认 last-write-wins 覆盖，是常见数据丢失 bug）；当前值类字段用裸类型覆盖写；消息类列表用 `add_messages`。

```python
# ---- 结构化抽取结果（with_structured_output method="json_schema"）----
class Requirement(BaseModel):
    intent: str                       # '找餐厅' / 其他
    cuisine: list[str]                # 菜系 ['川菜','粤菜']
    dish: list[str]                   # 菜品 ['烤鱼','火锅']
    taste: list[str]                  # 口味 ['麻辣','清淡']
    location_desc: str | None         # 自然语言位置（交高德 geocode，LLM 不造坐标）
    budget_preference: str | None     # 便宜/中档/贵 → 映射人均区间
    party_size: int | None
    scenario: str | None              # 一人食/聚餐/约会/商务
    dining_time: str | None           # 午餐/晚餐/夜宵（营业时间过滤用）
    dietary: list[str]                # 忌口/素食/过敏原
    rating_threshold: float | None
    clarify_needed: bool
    missing_required_slots: list[str]  # 必需槽位缺失（位置/预算优先）
    clarification_questions: list[str] # 待追问（一次只取最关键 1 个）

# ---- 图状态 ----
class ReqState(TypedDict):
    raw_input: str                                    # 覆盖写（含澄清后补充）
    requirement: dict                                 # 覆盖写（Requirement.model_dump()）
    clarify_needed: bool
    clarify_count: int                                # 澄清次数护栏（上限 2-3）
    clarification_history: Annotated[list[str], operator.add]
    location_desc: str | None
    location: str | None                              # '经度,纬度'（GCJ-02，经度在前）
    city: str | None
    radius: int                                       # 默认 5000
    search_mode: str                                  # 'around' | 'text' | 'text_fallback'
    candidates: Annotated[list[dict], operator.add]   # 各次召回追加，规范化 POI
    scored: Annotated[list[dict], operator.add]       # 追加：候选 + score + breakdown
    top_k: list[dict]                                 # 覆盖写（MVP 取 5）
    final_answer: dict                                # 覆盖写
    location_error: bool
    search_hint: str | None
    messages: Annotated[list[AnyMessage], add_messages]  # 多轮预留（MVP 可选）
```

规范化 POI 模型字段：`name` / `type` / `typecode` / `location` / `distance` / `address` / `tel` / `business_area` / `rating` / `cost`（后两者 `Number()`+判空）。

### 澄清节点（`interrupt()` 实现）

```python
from langgraph.types import interrupt, Command

def clarify_node(state):
    question = 生成单句追问（附推荐选项）      # 基于 missing_required_slots 取最关键 1 个
    answer = interrupt({"type": "clarify", "question": question})  # 图在此挂起
    # 用户回答后通过 app.invoke(Command(resume=answer), config) 恢复，execution 从 interrupt() 返回处继续
    return {
        "raw_input": f"{state['raw_input']}（补充：{answer}）",
        "clarify_count": state["clarify_count"] + 1,
        "clarification_history": [f"{question} → {answer}"],
    }
```

- 恢复后无条件路由回 `extract_requirement` 重抽，形成「澄清 ↔ 抽取」回环。
- 护栏：`clarify_count` 达上限强制跳 `resolve_location` 用默认值继续；低意图（"随便/都可以"）直接走默认 + 跳过追问。
- `interrupt()` 依赖 checkpointer（SqliteSaver）；`invoke` 遇 interrupt 会返回带 `.interrupts` 的响应。

---

## 6. 规则评分公式（借鉴 ProperFood）

```
总分 = base_quality + budget_penalty + distance_penalty + match_bonus

base_quality    = 贝叶斯校正评分（先验均值 4.2 / 先验评价数 120）
                  —— 防「4.2分/5条评价」排在「4.0分/800条」前面
budget_penalty  = |cost − 预算区间中值| 的惩罚项
distance_penalty = 距离越远分越低
match_bonus     = 菜系/菜品/口味/场景匹配加成（权重配置化）
```

**硬过滤**（不进打分，直接剔除）：营业时间不符 / 忌口违规（素食、过敏原、清/穆斯哈等）/ 菜系不匹配。

**缺失兜底**：`rating`/`cost` 缺失率高（小店/新店），缺失项**不硬排**、标注"暂无评分"，按 `distance` 降序。

**关键点**：
- 权重全部放 config 开放调参。
- 纯规则打分：确定性、可解释（每项都有 breakdown）、零幻觉、便宜。
- LLM 不做全量打分，只对 top-K 重排/解释（LLM 排序缺陷已在 §2 说明）。

---

## 7. 高德工具层

### 7.1 工具清单

| 工具 | 高德 API | 关键参数 | 说明 |
|---|---|---|---|
| `amap_geocode` | GET `/v3/geocode/geo` | `address`(必填)、`city`(辅助) | 自然语言地址/地标 → GCJ-02 坐标 + 城市信息。坐标一律由此产生，杜绝空间幻觉 |
| `amap_regeo` | GET `/v3/geocode/regeo` | `location`、`extensions=all` | 坐标 → 结构化地址（MVP 可选，直接用 POI.address） |
| `amap_place_around` | GET `/v3/place/around` | `location`(必填)、`types=050000`、`radius`(0-50000)、`sortrule=1`(综合)、`extensions=all`、`offset=20`、`page=1` | 周边搜索，默认召回主工具，一次拿全附近餐饮 + 距离 + 评分/人均 |
| `amap_place_text` | GET `/v3/place/text` | `keywords`、`types=050000`、`city`+`citylimit=true`、`extensions=all` | 文本搜索，周边搜索无结果/需关键词约束时的降级路径 |
| `amap_place_around_v5`（预留） | GET `/v5/place/around` | `location`、`types=050000`、`radius`、`page_size=25`；**必须** `show_fields=business` | 生产可选升级：`biz_ext.tag`(特色菜)、`opentime_today/week`(营业时间)。MVP 不启用 |

### 7.2 响应处理

- **成功判定唯一标准**：`status==1 && info=='OK'`（HTTP 通常 200 但业务失败，别依赖 HTTP 状态码）。
- `rating`/`cost`：位于 `pois[].biz_ext`（v3，需 `extensions=all`），数字字符串，防御式 `Number()` + 判空。
- 常见错误码：`10001`(key错误) / `10003`(日配额超限，次日0点解封) / `10004`(1分钟访问频繁) / `10010`(参数非法) / `10014`(QPS超限)。`10003/10014` 需退避重试或降级。
- v3/v5 差异：v5 数组名是 `poi_list`（非 `pois`），且需 `show_fields=business` 才有评分/人均——切换版本解析代码要重写，MVP 锁 v3。

### 7.3 调用序列（一次完整推荐）

```
输入 → extract_requirement(LLM)
  → [缺失→clarify→resume→重抽]
  → amap_geocode(address=位置描述)              → 广州 GCJ-02 坐标
  → amap_place_around(location, types=050000, radius, sortrule=1, extensions=all)
  → [无结果→扩大radius→place_text→兜底文案]
  → score_candidates(规则打分) → top_k=5
  → recommend(LLM 生成推荐) → 输出
```

每会话约 3-6 次高德调用（1 次 geocode + 1-3 次搜索/分页）。免费配额约 2000-5000 次/日（**推测**，以控制台实时为准），需内置双计数缓存 + 提前熔断 + 退避。

---

## 8. Harness 框架设计

通用 agent 外壳，与业务无关。这是方案中"Harness 框架"的定位：一套可复用的 agent 脚手架，吃饭 agent 只是第一个注册进去的组件。

### 8.1 内部模块

| 模块 | 职责 |
|---|---|
| `config.py` | 加载 `.env`：`AMAP_KEY`、`ANTHROPIC_API_KEY`、`MODEL=claude-opus-5`、`THINKING/effort`、`DEFAULT_CITY=广州`、`DEFAULT_RADIUS`、QPS/日配额计数缓存参数、`LOG_LEVEL`、`LANGSMITH`开关 |
| `llm_client.py` | `ChatAnthropic` 工厂（model/max_tokens 显式调高/`thinking=adaptive`）；`with_structured_output(schema, method="json_schema")` 助手；429/5xx 指数退避（max_retries=2）；`BadRequestError/AuthenticationError/RateLimitError/APIStatusError/APIConnectionError` 分链捕获 |
| `tool_registry.py` | `Tool` ABC（name/description/参数 schema/run）；`register_tool(name, tool)`；调用包装器自动套 QPS 信号量 + 限流退避 + 防御式解析 |
| `session.py` | checkpointer 管理：`SqliteSaver.from_conn_string()` 文件持久化（生产换 PostgresSaver）；`thread_id` 生成与多会话隔离（`f"user-{id}"`）；封装 `get_state/update_state` |
| `io.py` | CLI REPL 输入输出 + 处理 `interrupt/resume` 流 + `final_answer` 渲染 |
| `logging_tracing.py` | structlog 结构化日志（节点/工具耗时与错误）；可选 LangSmith（默认关） |
| `core.py` | `Harness` 主类，持有上述模块 |

### 8.2 对外接口（复用契约）

```python
harness.register_tool(name, Tool)      # 注册工具（高德或任意工具）
harness.register_agent(AgentMeta)      # 注册可插拔 agent
#   AgentMeta 含：name、build_graph(llm_client, tool_registry) -> Runnable、start_state 工厂、描述
harness.run()                          # 进入 REPL：每会话建 thread_id，转 start_state → 图 invoke（处理 interrupt/resume）→ 输出
```

**约定**：agent 不直接依赖 io/config，只依赖注入的 `llm_client` 与 `tool_registry` —— 保证 harness 可复用、agent 可替换。

---

## 9. MVP 范围

### 明确做

- 纯文本 CLI 单入口（`main.py` → `harness.run()`）。
- 单会话内最多 2-3 轮澄清的对话式追问（`interrupt()` 挂起/恢复）。
- LLM 需求抽取（`claude-opus-5` + `with_structured_output` json_schema）。
- 确定性位置解析（`amap_geocode`）、周边搜索召回（`amap_place_around` 为主，`place_text` 降级）、规则评分（贝叶斯校正 + 预算/距离/菜系加权 + 营业/忌口硬过滤）、LLM 对 top-K 生成带理由推荐。
- Sqlite 文件级多会话持久化（thread_id 隔离，进程重启后历史可续）。
- 限流/退避/错误码兜底（10003/10014/10010）与"无结果"降级文案。

> **状态（2026-08-25）**：会话内**多轮续聊**已实现 —— 同一 run() 内「换一家/再来一家」继承上文（位置/菜系/预算）并对上一轮 top-K 去重（`agents/eat_agent/memory.py`）。实现要点见 §14 修改记录。

### 明确砍掉（后续迭代）

- ~~多轮续聊~~ ✅（已实现：会话内继承 + 去重，经 `ConversationMemory`，每轮独立 thread 避免 reducer 累积）。
- 多轮**长期**记忆/个人画像/"推荐官沉淀"（`messages` 字段预留但不上 profile；跨进程重启续聊属后续）。
- 低星评价抓取与 LLM 安全审计。
- 多路召回与 RRF 融合（MVP 单路周边搜索）。
- v5 API 升级（营业时间过滤/特色菜标签，工具预留不启用）。
- 订座/下单/支付等动作执行；语音/图片/地图可视化；网页/服务端/移动端；天气/心情/节气上下文。
- 用户点赞/叉反馈落库、已推荐去重（MVP 可接受重复推荐）。

### MVP 简化决策

- 评分缺失项不硬排、标注"暂无评分"按距离降序兜底。
- 低意图输入（"随便"）跳过澄清走默认。
- 澄清追问一次只问 1 个最关键问题、带推荐选项。

---

## 10. 技术栈与依赖

```text
Python        >= 3.10（建议 3.12；langgraph-cli 本地模式需 >=3.11）
langgraph     >= 1.2.11
langchain-core>= 1.4.7
langchain-anthropic >= 1.6.0     （anthropic >= 0.78）
langgraph-checkpoint-sqlite ~3.1.1
structlog / pydantic >= 2.7.4 / httpx
```

LLM 接入关键点（claude-opus-5）：

- `ChatAnthropic(model="claude-opus-5", max_tokens=16000, thinking={"type": "adaptive"})`。
- **`budget_tokens` 已移除**，传了返回 400；用 `thinking=adaptive`。
- `output_config={"effort": ...}` 是否被当前 langchain-anthropic 接受需实测（接受则用，否则 `model_kwargs` 兜底）。
- 结构输出首选 `with_structured_output(Requirement, method="json_schema")`。

LangGraph v1 注意：

- `create_react_agent` / `MessageGraph` 已废弃，用 `StateGraph` + `messages` 字段。
- node 签名 `def node(state) -> dict`，返回部分更新 dict；原地 mutate 再返回会静默失败。
- `add_conditional_edges` 的 `path_map` 必须覆盖路由函数所有返回值。
- 持久化：`invoke(config={"configurable": {"thread_id": "..."}})` 才落库。

---

## 11. 目录结构

```text
where-to-eat/
├── pyproject.toml                 # 依赖与构建
├── .env.example                   # AMAP_KEY / ANTHROPIC_API_KEY / MODEL / DEFAULT_CITY / DEFAULT_RADIUS / LOG_LEVEL
├── README.md
├── DESIGN.md                      # 本文档
├── main.py                        # CLI 入口：装配 harness + 注册工具 + 注册 agent + run()
├── harness/                       # 顶层通用外壳（不感知业务）
│   ├── __init__.py
│   ├── core.py                    # Harness 主类：register_tool / register_agent / run
│   ├── config.py                  # env 加载、配额/限流参数、默认城市
│   ├── llm_client.py              # ChatAnthropic 工厂 + with_structured_output + 重试/异常
│   ├── tool_registry.py           # Tool ABC、注册、限流/退避包装
│   ├── session.py                 # SqliteSaver checkpointer + thread_id 会话隔离
│   ├── io.py                      # CLI REPL 与推荐文案渲染（含 interrupt/resume 流）
│   └── logging_tracing.py         # structlog + 可选 LangSmith
├── agents/
│   └── eat_agent/                 # 可插拔 LangGraph agent
│       ├── __init__.py            # build_graph(llm_client, tool_registry) -> app
│       ├── graph.py               # StateGraph 组装 + 条件路由 + checkpointer 编译
│       ├── state.py               # ReqState TypedDict + Requirement Pydantic
│       ├── routing.py             # route_after_extract / route_after_locate / route_after_search
│       ├── schemas.py             # Candidate / ScoreBreakdown / FinalAnswer
│       └── nodes/
│           ├── extract.py         # 需求抽取
│           ├── clarify.py         # 澄清（interrupt/resume 追问）
│           ├── locate.py          # 位置解析
│           ├── search.py          # 搜索召回
│           ├── score.py           # 规则评分
│           └── recommend.py       # LLM 推荐解释
├── tools/
│   └── amap/
│       ├── __init__.py            # 注册 4 个工具
│       ├── client.py              # httpx 封装、限流信号量、退避、错误码处理、日配额计数
│       ├── geocode.py             # amap_geocode / amap_regeo
│       ├── place.py               # amap_place_around / amap_place_text
│       └── models.py              # POI / GeocodeResult 规范化 Pydantic 模型
├── tests/                         # client 单测、节点单测、端到端 smoke（mock 高德响应）
└── data/
    └── checkpoints.db             # Sqlite 会话持久化（gitignore）
```

---

## 12. 分步实施与验收标准

> 状态：2026-08-20 全部完成（MVP mock 闭环跑通，4/4 单测通过）。未做真实 Key 联调（见 §14-5）。

| 步 | 内容 | 验收标准 | 状态 |
|---|---|---|---|
| 1 | 建目录 + pyproject；实现 config + llm_client + tool_registry + io；main.py | 跑通"输入任意文本→空 agent 原样回显"空闭环，验证 harness 可注册与运行 | ✅ |
| 2 | 实现 tools/amap/client.py（httpx + 限流 + 退避 + 错误码）；geocode + place_around | 有 Key 则手工调试"三里屯→坐标→餐饮 POI"；pytest mock 响应工具单测通过 | ✅ mock 回退（真实 Key 联调待做） |
| 3 | 最小线性链路（extract 写死 requirement，不调 LLM）：extract→locate→search→score(简化)→recommend | 在 harness 里跑通"位置+菜系→输出推荐"最小闭环 | ✅ |
| 4 | extract 改用 with_structured_output；接 route_after_extract + clarify（interrupt）+ clarify_count 护栏 | "想吃点便宜的川菜"这类不完整输入能追问一次后继续 | ✅ |
| 5 | 完善规则评分：贝叶斯校正 + 预算/距离惩罚 + 菜系/口味匹配 + 营业/忌口硬过滤 + 缺失兜底 | 产出 top_k=5 与 breakdown，供 recommend 引用 | ✅（营业/忌口过滤预留，见 §9 砍掉项） |
| 6 | 接 SqliteSaver + thread_id 隔离；封装 session.py | 重启进程后同会话可续；多会话隔离 | ✅ 会话隔离（进程重启续聊属后续迭代） |
| 7 | 打磨收尾：无结果降级、10003/10014 熔断、CLI 渲染、端到端 smoke（mock 高德）、README 与 .env.example | 全链路 mock 测试通过 | ✅ 4/4 单测 + CLI smoke 通过 |

---

## 13. 主要风险与对策

| 风险 | 对策 |
|---|---|
| 高德配额与限流（个人认证约 2000-5000 次/日，QPS 受限） | 内建双重计数缓存 + 提前熔断 + 退避重试；商用需企业认证（**配额数字为推测，以控制台为准**） |
| `rating`/`cost` 缺失率高（小店/新店常同时缺失，官方标注"逐渐废弃"） | 缺失不硬排、标注"暂无评分"、按距离降序兜底；评分不当唯一数据源 |
| v3/v5 字段差异（数组名、show_fields） | MVP 锁 v3，升级时解析代码整体重写 |
| LLM 幻觉/越界（造坐标/造店/造菜） | 候选严格限定高德返回集；坐标只来自 geocode；LLM 只做抽取+解释 |
| 澄清死循环/过度追问 | `clarify_count` 护栏（2-3 次）、一次一问带选项、低意图走默认 |
| LangGraph v1 API 变更 | 按 §10 纪律写；path_map 覆盖全部分支；Python ≥3.10 |
| GCJ-02 坐标系隔离 | 高德坐标只用于高德系服务，勿跨服务直用 |
| claude-opus-5 参数与成本 | 用 `thinking=adaptive` 不用 `budget_tokens`；max_tokens 显式调高；只对结构化抽取 + top-K 解释过 LLM，避免全量 |
| 评分质量难评估 | 权重配置化、预留人工抽查；城市场景→POI type 码映射需实测覆盖度 |

---

## 14. 待确认的遗留问题

1. **高德 API 版本**：MVP 锁 v3（兼容最稳），后续增量加 v5 —— 是否接受？
2. **澄清交互复杂度**：`interrupt()` 依赖 checkpointer，CLI 需处理 resume 流 —— 已确认采用，实现时留意。
3. **评分公式初始权重**：贝叶斯先验（4.2/120）、预算/距离惩罚系数、匹配加成上限等初值由实现预设并开放 config 调参 —— 是否有期望（如"评分优先还是距离优先"）？
4. **配额与认证**：个人认证还是企业认证？决定召回深度与是否预埋频控。
5. **高德 Key**：需在 lbs.amap.com 申请 **Web服务类型** Key（与 JS API/Android/iOS Key 不通用），配 IP 白名单。未申请期间用 mock 响应开发。
6. **多轮续聊**：MVP 是否保留 `messages` 多轮字段与 thread 续聊能力（同会话多轮输入），还是严格"单次输入→推荐即结束"？
7. **LangSmith tracing**：默认关；是否需要开启辅助调试？是否用 mock 高德响应做 CI（避免消耗真实配额）？

---

### 14.1 多轮续聊实现记录（2026-08-25）

- **不跨轮复用 thread_id**：`candidates/scored/clarification_history` 用 `operator.add`、`messages` 用 `add_messages`，复用同一 thread 会累积旧状态并残留上轮 `requirement/top_k`。故每轮全新 thread（`harness/core.py` 已加断言挡住"按用户复用"的未来改动），多轮上下文改走图闭包里的 `ConversationMemory`。
- **确定性继承对 LLM/规则双路径生效**（`extract._merge_with_prev`）：LLM 常丢位置（"换一家"），仅靠 prompt 继承不可靠；合并作为最后一步兜底填回位置/预算/菜系并清零澄清需求。
- **去重按延续意图门控**（"换一家/再来一家/还有别的吗"），普通复述保留最优批；窗口只限上一轮 top-K，先过滤再切片，耗尽时回退全量并给诚实提示。
- **去重键 `name|location`**（`poi_key`）：真实高德 address 常空，`name|address` 会塌缩成裸名致同名连锁误判。
- **`fallback_extract` 位置词误判修复**："换一家/再来一家" 中的「家」原会被当成位置词；已用负向断言守卫（`(?<![一这那哪请尝好])家`）。

## 15. 参考资源（同类实现/研究）

| 名称 | 链接 | 可借鉴点 |
|---|---|---|
| ProperFood | github.com/zent-zaxux/QwenHackathon-ProperFood | 最佳范本：7 节点 LangGraph，确定性硬过滤→规则打分带 breakdown→LLM 最终解释；贝叶斯评分校正 |
| Restaurant-Agent（中文） | tomevault.io/tome/bba70/Restaurant-Agent | 中文餐厅推荐：LangGraph Plan-and-Execute + 高德（地理编码+周边搜索），场景→POI type 码映射 |
| RecRanker / RecRankerEval | dl.acm.org/doi/full/10.1145/3705728 | LLM 排序缺陷量化：幻觉~1%、格式错位~10%、位置偏差~30% |
| What-to-eat-today | github.com/FutureUnreal/What-to-eat-today | 图RAG 中文美食推荐（多条件筛选） |
| 个人推荐官（CSDN） | blog.csdn.net/2501_90670820/article/details/161985858 | 推荐官沉淀/即时意图优先于长期画像 |
| Kotaemon 菜单推荐设想 | cnnetsun.cn/news/633941.html | SlotFillingPolicy：先确认饮食禁忌再谈口味 |

---

## 16. eat_react:纯 ReAct 并存 agent（2026-08-25）

在上述**确定性** `eat` agent 之外，新增一个**标准八股纯 ReAct** agent（`agents/eat_react/`，与 eat_agent 并存，独立注册）。它与 §2「LLM 只做两件事」的方法论**有意分歧**——纯 ReAct 是反方向的工程取舍，供对比实验。

**构建**：`create_react_agent(v2)` + 预构建 `ToolNode(tools, handle_tool_errors=True)`。
- 工具（`tools.py`）：`amap_geocode` / `amap_search_around` / `amap_search_text`（复用 harness 已注册的高德工具，自动带 mock/real）+ 可选 `score_candidates`（复用 `agents/eat_agent/nodes/score.py` 的 `score_node(config, None)`，`memory=None` 绕过去重）+ `ask_user`（`interrupt()` 挂起恢复，人机在环澄清）。
- 状态（`state.py`）：最小化 `messages`（`add_messages`）+ `remaining_steps`（`create_react_agent` 强制要求）。刻意不用 `operator.add` 业务累积字段，避免 eat_agent 的 reducer 落地雷。
- 多轮记忆：`AgentMeta.run_mode="session_thread"`，harness 用稳定 thread 保留 messages 历史。

**harness 泛化**：`AgentMeta` 增 `run_mode`（默认 `per_turn_thread` 保持 eat 原行为；`session_thread` 走新循环 + `_report_react` 渲染最后一条 assistant 消息）。`io.py` 的 `run_graph_with_interrupts` 增 `recursion_limit`（默认 50）。

**⚠️ 纯 ReAct 必须绑定真实 LLM**（无 no-key 规则兜底，LLM 即编排者）；无 key 时 `main.py eat_react` 明确报错退出。测试用 `ScriptedLLM` 注入驱动（`tests/test_react_agent.py`，`bind_tools` 需 override、`_llm_type` 用 `@property`）。

**已知取舍（据 §14 复核）**：确定性 pipeline 无法表达否定（「不要火锅」），纯 ReAct LLM 天然能处理——这是本升级的一个实际收益点；代价是失去可复现的确定性排序保证与 no-key 优雅降级。

---

*本文档由设计研究（高德 API / LangGraph 最佳实践 / 同类 agent 三路调研 + 综合设计）产出，后续实现以本文件为基线，改动时同步更新。*
