# Where to Eat — 寻找吃饭目的地的 LangGraph Agent

基于 LangGraph 的吃饭推荐 agent，跑在自研 **harness 框架**（通用 agent 外壳）里，数据源为高德地图 Web服务 API。

架构与设计详见 [DESIGN.md](DESIGN.md)。

## 快速开始（无需任何 API Key）

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python main.py
```

不配置 Key 时自动使用 **mock 数据**（高德 mock + 规则抽取/模板推荐），最小闭环照常可跑：

```
需求> 想吃辣的，人均100以内，天河附近
```

## 接入真实数据

申请 Key 的完整图文步骤见 **[KEY_GUIDE.md](KEY_GUIDE.md)**。拿到 Key 后复制 `.env.example` 为 `.env` 填入，并跑自检脚本确认可用：

```bash
cp .env.example .env
# 编辑 .env，填入 AMAP_KEY / ANTHROPIC_API_KEY
.venv/bin/python scripts/check_keys.py
```

| 变量 | 说明 |
|---|---|
| `AMAP_KEY` | 高德**Web服务**类型 Key（lbs.amap.com 控制台 → 应用管理 → 添加 Key） |
| `AMAP_SOFT_LIMIT` | 本地软熔断（次/天，默认 200）——高德是月配额，此值仅防本地调试打爆 |
| `LLM_PROVIDER` | 模型层：`auto`（默认）\| `anthropic` \| `deepseek` |
| `ANTHROPIC_API_KEY` | Claude API Key（模型 `claude-opus-5`） |
| `DEEPSEEK_API_KEY` | DeepSeek API Key（国内可直连、OpenAI 兼容，默认模型 `deepseek-chat`） |
| `DEEPSEEK_MODEL` | DeepSeek 模型名（默认 `deepseek-chat`） |

**想跳过 Anthropic 的地区/支付门槛？** 模型层可直接用 DeepSeek：在 `.env` 填 `DEEPSEEK_API_KEY`（[platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) 申请，充值支持支付宝/微信）即可，无需 Anthropic Key。

有 Key 即自动切真实调用；缺一个就只 mock 对应的那一层。

## 最小闭环流程

```
用户文本输入 → extract_requirement(LLM/规则) → [需求不明确→interrupt()澄清→重抽]
  → resolve_location(高德地理编码) → search_restaurants(周边搜索+降级)
  → score_candidates(规则打分, top-K=5) → recommend(LLM/模板推荐) → 输出
```

## 多轮续聊

一次 `python main.py` 内可连续多轮对话，上下文自动延续：

```
需求> 想吃辣的，人均100以内，天河附近
需求> 换一家            ← 继承位置/菜系/预算，且排除上一轮已推荐的店
需求> 还有别的吗
```

- 每轮**独立跑最小闭环**（每轮全新 thread，避免 state reducer 跨轮累积），上下文经 `ConversationMemory`（[agents/eat_agent/memory.py](agents/eat_agent/memory.py)）在图闭包里流转。
- 「换一家/再来一家/还有别的吗」等延续意图 → 排除上一轮 top-K；复述同一需求 → 保留最优批。
- 位置继承：新一轮给不出位置时沿用上一轮（原始地点文本 → 兜底上一轮定位城市），不重复澄清。

## eat_react（纯 ReAct 并存 agent）

与上面的确定性 `eat` agent **并存**，走标准八股的 **纯 ReAct**：LLM 绑定工具、在推理循环里自主决定调什么、按什么顺序、重试几次。

```bash
python main.py eat_react      # 默认；也可用 AGENT=eat_react
python main.py eat            # 走确定性 agent
```

- **工具**：`amap_geocode` / `amap_search_around` / `amap_search_text`（复用高德真实/mock 数据）+ 可选的 `score_candidates`（复用 eat_agent 确定性评分）+ `ask_user`（`interrupt()` 挂起/恢复人机在环澄清）。
- **多轮记忆**：`run_mode="session_thread"` 用稳定 thread，checkpointer 保留 messages 历史 → LLM 天然继承上下文、能避免重复推荐。
- **⚠️ 纯 ReAct 必须绑定真实 LLM**（无 no-key 规则兜底，LLM 就是编排者）；无 key 时 `main.py eat_react` 会报错退出。测试用 `ScriptedLLM` 注入驱动（`tests/test_react_agent.py`）。
- **收益点**：ReAct LLM 能表达确定性 pipeline 处理不了的否定（「不要火锅/别太辣」）。

## 项目结构

```
main.py                  CLI 入口（注册 eat + eat_react，argv/[AGENT] 选择）
harness/                 通用 agent 外壳（config/llm/tool_registry/session/io/logging/core）
agents/eat_agent/        确定性 LangGraph 推荐 agent（state + 6 节点 + 条件路由）
agents/eat_react/        纯 ReAct 工具驱动 agent（create_react_agent v2）
tools/amap/              高德工具层（真实 API + mock 回退）
tests/                   mock 模式闭环测试
DESIGN.md                设计方案
```

## 测试

```bash
.venv/bin/python -m unittest tests.test_closed_loop -v
```

> ⚠️ 本项目用 `uv` 装环境：`uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .`
> （Homebrew Python 3.12 的 pyexpat/libexpat 符号不匹配时，用 `uv python install 3.12` 装独立 CPython。）

## 状态

- [x] harness 骨架
- [x] 高德工具层（v3，含 mock 回退）
- [x] eat_agent：需求抽取 / interrupt 澄清 / 定位 / 搜索 / 规则评分 / 推荐
- [x] 最小闭环（mock 模式端到端，10/10 单测通过）
- [x] 真实高德联调（AMAP_KEY 验证通过，真实餐厅数据跑通）
- [x] LLM 层可切换：Anthropic（claude-opus-5）/ DeepSeek（deepseek-chat）/ 无 key 模板推荐
- [x] DeepSeek 联调：真实需求抽取（function_calling 降级）+ 真实高德搜索 + LLM 推荐文案
- [x] 多轮续聊：同一会话内「换一家 / 再来一家 / 还有别的吗」继承上文（位置/菜系/预算）并对上一轮去重（`ConversationMemory`，见 DESIGN.md）
- [x] eat_react：纯 ReAct 并存 agent（create_react_agent v2 + AMAP 工具 + ask_user 澄清 + session 线程多轮记忆）
- [ ] Anthropic（claude-opus-5）联调（可选，需 `ANTHROPIC_API_KEY`）
- [ ] 评分权重调优、高德 v5 升级等（见 DESIGN.md §9 迭代项）

> ⚠️ mock 数据中的餐厅名称为虚构占位，仅用于演示流程。
