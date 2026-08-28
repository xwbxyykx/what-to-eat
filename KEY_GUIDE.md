# 申请 Key 指南

> 面向广州开发者。本项目需要两个第三方 API Key：高德 Web服务 Key（地理编码 + 周边餐厅搜索）与 Anthropic Claude API Key（模型 `claude-opus-5`）。下文每条结论标注置信度：[已确认]（来自调研结果/官方链接）或 [待实测]（可能但不保证）。

## 一、概览

| 变量 | 用途 | 申请平台 | 调用方式 |
|---|---|---|---|
| `AMAP_KEY` | 高德 Web服务 API：地理编码（把「天河附近」转成坐标）+ 周边/关键字餐厅搜索 | 高德开放平台（lbs.amap.com / console.amap.com） | HTTPS + `key=` 参数 |
| `ANTHROPIC_API_KEY` | Claude 模型 `claude-opus-5`，负责需求抽取与最终推荐文案 | Anthropic Console（console.anthropic.com） | HTTPS + `x-api-key` 头，经 `langchain-anthropic` 调用 |

**没有 Key 也能跑**：项目内置 mock 降级，两个 Key 任意缺失，对应那一层自动退回假数据，最小闭环照常可跑——[已确认]（项目代码）

- 缺 `AMAP_KEY`：`tools/amap/client.py` 的 `geocode / search_around / search_text / regeo` 全部走 `mock_data`（虚构占位餐厅）；
- 缺 `ANTHROPIC_API_KEY`：`harness/llm_client.py` 的 `build_chat_llm()` 返回 `None`，agent 走「规则抽取 + 模板推荐」；
- 判定逻辑在 `harness/config.py`：`Config.use_mock_amap` / `Config.use_mock_llm` 只看对应 key 是否为空。

所以可以先跑 mock 模式把流程走通，再按本指南逐个接入真实数据。

**模型层可换 DeepSeek（国内直连）**：若 Anthropic 受地区/支付限制，可用 DeepSeek 替代——国内直连、按量计费、支付宝/微信可充。在 `.env` 填 `DEEPSEEK_API_KEY`（[platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) 创建，`sk-` 开头，同样只在创建时显示一次），`LLM_PROVIDER=auto` 会自动识别，无需 Anthropic Key。默认模型 `deepseek-chat`（非思考模式，适合抽取/推荐）；如对特定推理需求可选 `deepseek-reasoner`。[已确认]（官方控制台 + OpenAI 兼容接口）

## 二、高德 Web服务 API Key（AMAP_KEY）

### 申请流程

1. **注册账号**：访问 [高德开放平台官网 lbs.amap.com](https://lbs.amap.com/) 或直接进 [控制台 console.amap.com](https://console.amap.com/)，右上角「注册」，手机号 + 验证码 + 设置密码完成注册（已有账号直接登录）。[已确认]
2. **个人开发者实名认证（必需）**：2023 年起仅手机号注册不再能申请 Key，必须先实名。进入 [开发者实名认证页](https://console.amap.com/dev/user/permission)，选「个人开发者」，通常走 **支付宝扫码 + 身份证 + 人脸识别** 即可，认证通过后即可申请 Key，默认套用「初级个人配额模板」，**无需审核**。个人认证材料：身份证 + 支付宝；企业认证才需营业执照（本场景个人即可）。[已确认]
3. **创建应用**：进入 [应用管理 → 我的应用](https://console.amap.com/dev/key/app)，右上角「创建新应用」，填应用名称（建议用项目名）、选应用类型（如「其他/生活/出行」），提交。[已确认]
4. **添加 Key**：在刚创建的应用下点「添加 Key」，填 Key 名称（支持汉字、数字、字母、下划线、中划线，≤15 字符）。[已确认]
5. **关键一步——服务平台选「Web服务」**：在「服务平台」下拉框务必选 **「Web服务」**，不要选「Web端(JS API)」。两者不通用：选错的话后端 `/v3/...` 调用会返回 key 类错误（常见 `INVALID_USER_KEY`，平台不匹配也可能报 `USERKEY_PLAT_NOMATCH`，具体以实际返回为准）。[已确认/待实测]
6. **IP 白名单（可选，非必填）**：见下节「IP 白名单的现实处理」。[已确认]
7. 勾选同意《高德服务条款》《Web服务API使用条款》等协议，点「提交」。[已确认]
8. 提交后应用下即生成一串 Key，点「复制」保存。**Web服务 Key 不需要 `securityJsCode` 安全密钥**，后端只需 `key=` 参数即可调用。[已确认]

> 官方图文参考：[成为开发者并创建 Web服务 Key](https://lbs.amap.com/api/common-components/dev-key-webservice)、[成为开发者并创建 Key（2026-06 更新）](https://developer.amap.com/api/mcp-server/create-project-and-key)。

### IP 白名单的现实处理

- 留空 = 不限 IP，任何 IP 都能调用；设置后仅白名单内 IP 可访问，白名单外返回错误码 `10005 INVALID_USER_IP`。[已确认]
- 白名单填的是服务器**公网出口 IP（IPv4）**，支持 IP 段（如 `202.202.2.*`），多 IP 每行一条；高德 Web服务只识别 IPv4。[已确认]
- **家庭/办公动态 IP 建议直接留空**：IP 一变就要回控制台改白名单，得不偿失；官方 [FAQ](https://lbs.amap.com/faq/webservice/webservice-api/basic-configuration/43238) 也建议线上正式使用再设白名单，防 Key 泄露被盗刷配额。[已确认]
- 本机调试时出口 IP 经常变化，还可能拿到 IPv6——填了 IPv4 白名单反而调不通，故开发阶段留空最省事。[已确认/待实测]
- 可选**替代/叠加加固**：开启**数字签名 `sig`**（`sig=MD5(参数升序拼接+私钥)`）。代价是每次请求都要带 `sig` 参数、后端要维护私钥；开发期建议先不启用，直接用 `key=`。[待实测]

### 配额数字（口径已更新，注意）

高德 **2025-05-20 起取消日配额、改为月配额**（[官方公告](https://lbs.amap.com/news/service_amap)），网上大量旧教程的「个人地理编码 5000/日、搜索 100/日」已失效，勿据此设计容量：[已确认]

| 服务组 | 含本项目哪些接口 | 个人认证 | 企业认证 | 企业+技术服务许可 |
|---|---|---|---|---|
| 基础 LBS 服务组 | 地理编码 `/v3/geocode/geo`、逆地理编码 `/v3/geocode/regeo` | 150,000 次/月 | 3,000,000 次/月 | 9,000,000 次/月 |
| 基础搜索服务组 | 周边搜索 `/v3/place/around`、关键字搜索 `/v3/place/text` | **5,000 次/月** | 50,000 次/月 | 500,000 次/月 |

配额在 API/JS/Android/iOS/小程序各平台间**共享**（同一账号所有 Key 用同一份配额）。[已确认]

**本项目瓶颈在搜索服务组**：一次完整推荐大致消耗 **1~2 次地理编码**（定位失败回退默认城市时会多耗 1 次）+ **1~3 次搜索**（周边→文本→扩半径的降级链），个人搜索组 5,000 次/月 ≈ 每月约 **1,700~5,000 次**完整推荐。（配额为官方公布值，换算为合理估计）[已确认/估算]

- 超月配额不会自动扣费，服务降级/停用后需主动购买流量包（约 30 元/万次）；更高配额需企业认证 + 配额申请审核。[已确认]
- QPS（每秒并发）官方无公开统一表，需到[控制台「流量分析 → 配额管理」](https://developer.amap.com/api/webservice/guide/tools/flowlevel)按服务实时查看；第三方数字（30/50/100/200/1000）互相矛盾，**以控制台为准**。[待实测]

### 一条 curl 验证命令

拿到 Key 后立刻验证（中文参数交给 `--data-urlencode` 自动编码，避免 URL 编码问题）：[已确认]

```bash
curl -G "https://restapi.amap.com/v3/geocode/geo" \
  --data-urlencode "address=广州市天河区珠江新城" \
  --data-urlencode "key=你的Key"
```

期望返回 JSON 中 `"status":"1"`、`"info":"OK"`，且 `geocodes[0].location` 是一对坐标（如 `113.324325,23.106006`）。

## 三、Anthropic Claude API Key（ANTHROPIC_API_KEY）

### 前置：地区与支付（先看，别白忙）

- **地区限制（客观事实）**：中国大陆、香港、澳门不在 [Anthropic 官方受支持国家/地区列表](https://www.anthropic.com/supported-countries) 中，被明确排除；台湾在支持列表中。Anthropic 保留对「多数所有权归属未支持地区实体」不提供服务的权利，并对来自/协助来自未支持地区的访问持续加大风控（2026-07 起加强执法，覆盖 VPN 跳节点、API 中转、海外子公司、云厂商渠道等）。广州开发者需自行评估是否具备合规获取渠道（如官方支持地区的账号主体，或经 [AWS Bedrock](https://aws.amazon.com/bedrock/claude/) / [Google Vertex AI](https://cloud.google.com/vertex-ai/generative-ai/docs/partner-models/use-claude) 等云平台合规使用）；这些渠道的政策需自行核实。[已确认（官方政策事实，不提供规避建议）]
- **无免费层，先充值后能用**：Claude API 没有长期免费额度。必须在 `Settings → Billing` 绑定信用卡（Visa / Mastercard / Amex；不接受 PayPal/Venmo、电汇、支付宝/微信、加密货币）并**预充值 credits（最低约 $5）**，否则即便拿到 Key，请求也会返回 401/配额类错误。账单地址需与卡片发行方一致且在受支持账单地区；跨境订阅常被银行风控拦截，需开通国际循环支付 / 3DS 验证。[已确认]

### 申请流程

1. **注册**：访问 [console.anthropic.com](https://console.anthropic.com/)（新入口也叫 [platform.claude.com](https://platform.claude.com/)），邮箱 + 密码（或 Google SSO），收邮件完成验证。[已确认] 部分账号/地区还要求**手机号 SMS 验证**：须为受支持地区、可收短信的移动号，VoIP/虚拟号会被拒，且验证后不可更改——大陆号码属未支持地区，这一步对广州开发者是常见卡点。[待实测，两份调研结论在此存在分歧]
2. **完成 onboarding**：填全名、确认年满 18、选账号类型（Individual / Organization）。控制台会自动建一个 workspace（Key 与用量以 workspace 为作用域）。[已确认]
3. **开通计费（必须，Key 才能用）**：进入 `Settings → Billing`，添加信用卡，购买预充值 credits（最低约 $5）。可选开 auto-reload 与用量上限（`Settings → Limits`）。[已确认]
4. **创建 API Key**：`Settings → API Keys`（直达 [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)）→ 点「Create Key」，填一个描述性名称，可选选择作用域 workspace 与过期时间，创建。[已确认]
5. **立即复制 Key**：Key **只在创建那一刻显示一次**，之后无法再查看（丢了只能重新建）。格式为 `sk-ant-api03-...` 开头的 32+ 位字符串，复制时**不要带行尾空白/换行**。正式使用建议 30–90 天轮换一次。[已确认]
6. **（可选）升级速率档**：新号从 Tier 1 起步（约 5 请求/分钟），预充约 $5 通常升到更高档（约 50 请求/分钟）；Tier 随累计消费自动升级。**升级阈值官方未公开统一口径**，第三方数字在「累计购买满 $40」与「30 天累计消费 $100+」之间不等，以控制台实际为准。[待实测]

> 官方参考：[快速开始](https://platform.claude.com/docs/en/get-started)、[控制台文档](https://platform.claude.com/docs/en/administration/console)。

### 一条 curl 验证命令

```bash
export ANTHROPIC_API_KEY="sk-ant-api03-..."

curl https://api.anthropic.com/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-opus-5","max_tokens":1024,"messages":[{"role":"user","content":"Hello, Claude!"}]}'
```

期望 200 + JSON，`content[0].type` 为 `"text"`，`stop_reason` 为 `"end_turn"`。[已确认]

- 常见返回：`401` = Key 无效 / 复制带了空白 / 未开通计费；`429` = 限流或余额耗尽（带 `retry-after` 头）；`400 invalid_request_error` = 模型名写错。[已确认]
- 2026-02 起 Anthropic 停用了 OAuth/订阅 token（`sk-ant-oat01-*`）的 API 访问，第三方集成只能用控制台生成的 `sk-ant-api03-*` Key，即使有 Pro/Max 订阅也不通。[已确认]
- `claude-opus-5` 计价（参考）：输入 $5 / 1M tokens、输出 $25 / 1M tokens；Batch API（异步）5 折；Fast mode 溢价约 2x。[已确认]

## 四、常见坑

### 1. 高德 JS API Key 与 Web服务 Key 不通用 [已确认]

后端 `/v3` 调用必须用 **Web服务** 类型 Key。申请时「服务平台」选成「Web端(JS API)」「Android」「iOS」等，后端调用会返回 key 类错误（常见 `INVALID_USER_KEY`，平台不匹配也可能报 `USERKEY_PLAT_NOMATCH`），同一 Key 不可跨平台混用。反之，2021-12-02 后申请的 JS API Key 强制要求 `securityJsCode` 安全密钥——那套机制**与 Web服务无关**，别拿它配到 Web服务 Key 上。Web服务后端直连只需 `key=` 参数。

### 2. 报错速查（白名单不匹配 / 平台选错等）

高德 [Web服务错误码说明](https://developer.amap.com/api/webservice/guide/tools/info)：[已确认/部分]

| 错误码 | 含义 | 常见原因与处理 |
|---|---|---|
| 10001 | 用户 key 不正确或过期（INVALID_USER_KEY） | key 复制不全/带空白，或**服务平台选错**（非 Web服务）；回控制台重新复制并确认平台 |
| 10002 | 用户 key 非法 | 回控制台核对 key 状态 |
| 10003 | 访问已超出配额（DAILY_QUERY_OVER_LIMIT） | 当月配额用完（个人搜索组 5,000/月），去控制台「配额管理」看进度 |
| 10004 | 用户 IP 非法 | 核对当前公网出口 IP |
| 10005 | INVALID_USER_IP | 设了 IP 白名单但当前出口 IP 不在名单内；改白名单，或干脆留空 |
| 10010 / 10019 | 配额超限 / 次数限制 | 去控制台「配额管理」看进度；次日或下月恢复 |
| 10014 | KEY_ERR（签名/白名单） | 与数字签名 `sig` 或白名单相关 [待实测] |

> ⚠️ **错误码含义官方文档各版本有出入**（尤其 10003/10005），网上还有另一套「10003=key 不合法」的旧口径；以上按官方「Web服务错误码说明」主口径整理，排查时以**实际返回 + 控制台「配额管理」**为准。排查顺序建议：① 确认平台是「Web服务」；② 确认 Key 复制完整；③ 若设了白名单确认当前公网 IP；④ 以上都没问题看配额。

### 3. Anthropic 地区与支付限制 [已确认]

- 中国大陆不在官方支持地区列表。若账号/卡片无法通过审核，这是**政策限制**而非 Key 格式问题；请评估合规渠道（AWS Bedrock / Google Vertex AI / 其他合规供应商），自行核实其政策。
- 标准账户为预付积分制，无后付费月结；预付/礼品卡实践中常被拒（3DS / 循环扣款校验），建议用标准 Visa/MC/Amex 信用卡。
- 2026-04 起对高风控用户/特定能力强制实名（政府照片身份证 + 人脸，经第三方 Persona 处理）。
- 账单地址需与卡片发行方一致，跨境订阅常被银行风控拦截——需开通国际循环支付 / 3DS 验证。

### 4. 配额熔断提示 [已确认/待实测]

- 项目内置**本地软熔断** `AMAP_SOFT_LIMIT`（默认 **200 次/天**，可经 .env 调整）：当天累计调用超限会抛 `AMAP_QUOTA_EXCEEDED` 并触发上层降级。[已确认（代码）]
- **注意**：这只是防本地调试打爆月配额的第一道闸。高德 2025-05-20 起为**月配额**（个人搜索服务组 5,000 次/月），本地软熔断无法替代控制台配额——用量大的话仍要按月在控制台「配额管理」核对进度。[已确认/待实测]
- 高德侧服务出错（如 10003 配额 / 10005 白名单）时 client 会退避后上抛，由 locate/search 节点降级（无结果兜底），不会崩。[已确认（代码）]
- Anthropic 侧：余额为 0 时 API 立刻失败（401/429），`scripts/check_keys.py` 会给出提示；正式使用建议在控制台开 auto-reload 并设用量上限，避免超支。[已确认]

## 五、填入 .env 后如何自测

1. **复制 .env 模板**：
   ```bash
   cp .env.example .env
   ```
2. **编辑 `.env`**，填入两个 Key：
   ```bash
   AMAP_KEY=你的高德Key
   ANTHROPIC_API_KEY=sk-ant-api03-你的ClaudeKey
   ```
   （其余 `MODEL=claude-opus-5`、`DEFAULT_CITY=广州`、`DEFAULT_RADIUS=5000` 已预设，无需改。）
3. **跑自检脚本**（只校验你填了的 Key）：[已确认（项目脚本）]
   ```bash
   .venv/bin/python scripts/check_keys.py
   ```
   - 高德：调 `/v3/geocode/geo` 解析「广州市天河区珠江新城」，返回 `status:1/OK` 且有坐标即通过；否则按错误码给修复指引（10001/10002/10003/10004/10005/10010/10014/10019 见第四节速查表）。
   - Anthropic：向 `/v1/messages` 发一条 32-token 的 `claude-opus-5` 请求，返回 200 即通过；401/403 提示检查 Key 与计费，429 提示检查 credits。
   - 两个 Key 都为空时脚本会明确提示「当前是 mock 模式」，并指回本指南。
4. **跑真实数据闭环**：
   ```bash
   .venv/bin/python main.py
   ```
5. **mock 降级如何观察**：只填一个 Key，就只 mock 对应的那一层（判定在 `harness/config.py` 的 `use_mock_amap` / `use_mock_llm`）。例如只填 `AMAP_KEY`：位置和餐厅是真数据，但推荐文案是模板；只填 `ANTHROPIC_API_KEY`：推荐文案是 LLM，但餐厅列表是虚构占位。日志中 `llm_mock_mode` / `llm_ready` 会标注当前是哪一层。[已确认（代码）]
6. **回归测试**：mock 模式闭环单测 `tests/test_closed_loop.py` 不依赖任何 Key，随时可跑：[已确认]
   ```bash
   .venv/bin/python -m unittest tests.test_closed_loop -v
   ```

## 参考链接汇总

**高德**

- [高德开放平台官网](https://lbs.amap.com/)
- [高德控制台](https://console.amap.com/)
- [应用管理 / 创建 Key](https://console.amap.com/dev/key/app)
- [开发者实名认证](https://console.amap.com/dev/user/permission)
- [成为开发者并创建 Web服务 Key（官方指引）](https://lbs.amap.com/api/common-components/dev-key-webservice)
- [成为开发者并创建 Key（官方，2026-06 更新）](https://developer.amap.com/api/mcp-server/create-project-and-key)
- [个人 vs 企业认证 FAQ](https://developer.amap.com/faq/account/certification/39670)
- [配额调整公告（2025-05 起月配额制）](https://lbs.amap.com/news/service_amap)
- [Web服务流量限制说明](https://developer.amap.com/api/webservice/guide/tools/flowlevel)
- [Web服务错误码说明](https://developer.amap.com/api/webservice/guide/tools/info)
- [IP 白名单 FAQ](https://lbs.amap.com/faq/webservice/webservice-api/basic-configuration/43238)
- [Web服务调用示例（key= 参数格式）](https://developer.amap.com/api/webservice/guide/api/staticmaps/)

**Anthropic**

- [Claude Console](https://console.anthropic.com)
- [API Keys 页面](https://console.anthropic.com/settings/keys)
- [Claude Platform（console + docs）](https://platform.claude.com)
- [官方快速开始](https://platform.claude.com/docs/en/get-started)
- [官方控制台文档](https://platform.claude.com/docs/en/administration/console)
- [受支持国家/地区列表](https://www.anthropic.com/supported-countries)
- [Claude 定价](https://www.anthropic.com/pricing)
- [Anthropic 帮助中心（计费与实名政策）](https://support.claude.com)

**本项目相关文件**

- `.env.example`（Key 模板）
- `scripts/check_keys.py`（Key 自检）
- `harness/config.py`（mock 判定：`use_mock_amap` / `use_mock_llm`）
- `tools/amap/client.py`（高德客户端 + `AMAP_SOFT_LIMIT` 软熔断 + mock 回退）
- `harness/llm_client.py`（langchain-anthropic 接入）
