# 查询进度提示优化方案讨论记录

## 背景与问题

用户提交 query 后，前端只有一个静态 loading 文案「正在分析 / 理解问题并检索相关 Schema…」（原 `frontend/src/App.vue`），直到最终结果返回前没有任何中间反馈。一次数据库查询通常包含 3~6 次串行 LLM 调用，等待时间长，用户容易误以为页面卡住。

目标：在等待期间实时告诉用户当前查询进行到哪一阶段——是否已发送、SQL 是否已生成、是否正在执行查询。

## 现状分析：一次 query 的完整阶段链路

前端 `POST /api/query` 原本是同步请求（超时 300s），后端实际按以下顺序执行：

| # | 阶段 | 位置 | 说明 |
|---|------|------|------|
| 0 | 请求接收 | `backend/app/api/routes.py` | 认证、游客配额扣减 |
| 1 | 预处理（意图路由） | `query_graph.py` `_preprocess` → `preprocessing.py` | 1 次 LLM 调用：判断 direct_response / data_qa / database_query，改写独立查询、提取检索词 |
| 2a | 直接回答 | `query_graph.py` `_respond_directly` | 闲聊类，预处理结果直接返回 |
| 2b | 已有结果分析 (data_qa) | `query_graph.py` `_answer_qa` | LLM 生成文字/报告，可能调用图表工具 |
| 2c | Schema 检索 | `query_graph.py` `_retrieve_schema` | BM25 + 向量 + RRF + rerank，构建 Schema 图 |
| 3 | SQL 生成与执行 | `query_graph.py` `_prepare_single_database` → `single_database_agent.py` | Agent 循环（最多 3 次工具调用，每次决策 1 次 LLM 调用），SQL 经 MCP `query_<db>` 工具执行 DuckDB，失败自动修正重试 |
| 3.5 | （可能）人工澄清 | `query_graph.py` `_human_clarification` | LangGraph interrupt 暂停，返回 waiting_clarification |
| 4 | 结果整理 | `query_graph.py` `_execute_single_database` → `response_generator.py` | 1 次 LLM 调用：生成标题和结果说明 |
| 5 | 收尾 | `finquery_service.py` | 任务缓存、归档、异步短期记忆摘要 |

## 方案讨论

### 方案 A：SSE 流式推送（最终采用）

前端只发一次 `POST /api/query`，但响应保持为长连接；后端每进入一个阶段就通过这条连接主动推送一条事件，最后推送携带完整 QueryResult 的 `result` 事件并关闭连接。

- 事件驱动、零延迟：状态一变前端立刻知道
- 只有一次 HTTP 请求，不增加请求数量
- 代价：前端需要解析流式响应；经过 nginx 时需要关闭响应缓冲

### 方案 B：异步任务 + 轮询（未采用）

`POST /api/query` 立即返回 `task_id`，后端在后台线程跑工作流并把进度写入内存；前端每秒轮询一次 `GET /api/tasks/{id}/progress`。

- 优点：实现直观、对任何代理/浏览器都稳定
- 缺点：进度最多有 1 秒滞后；每个查询额外产生几十次轮询请求；后端需要管理后台任务的生命周期清理；改变了 `/api/query` 的同步契约

### 讨论中的关键问答

**问：两个方案的本质区别是什么？**

答：后端"进度来源"完全一样——都是在工作流各阶段埋点记录状态。区别只在传输方向：方案 A 是后端主动推（有进展才发，一次连接覆盖全程）；方案 B 是前端定时来问（不管有没有新进展，每秒都发一次请求）。

**问：流式响应是什么概念？有哪些其他应用？**

答：普通 HTTP 是"一问一答、一次给完"，服务器准备好完整响应才返回；流式响应是连接建立后不关闭，服务器算出一小块就立刻推给浏览器一块。SSE（Server-Sent Events）是最常用形式：响应头声明 `Content-Type: text/event-stream`，之后持续写入 `event:`/`data:` 文本段。典型应用包括：

- AI 对话逐字输出（ChatGPT/Kimi 的打字机效果）
- 耗时任务的进度推送（文件导出、报表生成、视频转码）
- 实时通知（股票行情、协作光标）
- CI 构建/部署日志实时滚动

对本项目还有扩展价值：未来若要结果说明逐字流式输出，这条通道可直接复用。

## 最终实施（方案 A）

### 用户可见的阶段序列

数据库查询路径：`已提交 → 正在理解问题 → 正在检索相关数据表 → 正在生成 SQL → SQL 已生成（附 SQL 预览）→ 正在执行查询 → 正在整理结果`

data_qa 路径：`已提交 → 正在理解问题 → 正在分析已有结果`；direct_response 路径：`已提交 → 正在理解问题 → 正在生成回答`。SQL 执行失败重试时显示「查询失败，正在修正 SQL（第 n 次尝试）」。

### 后端改动

1. **`backend/app/workflows/progress.py`（新增）**：`ProgressBus` 进程内进度总线，按 task_id 订阅/分发事件；`alias()` 处理澄清续跑（沿用旧 task_id 的 LangGraph 线程）时事件转发给新订阅者。不把回调放进 QueryState，因为 InMemorySaver 需要序列化 state。
2. **`query_graph.py`**：各节点入口埋点 emit 阶段事件。
3. **`single_database_agent.py`**：`prepare()` 新增可选 `progress` 回调，LLM 决策前、数据库工具调用前、失败重试时分别推送事件。
4. **`models.py`**：新增 `ProgressEvent` 模型（task_id / stage / message / detail / ts）。
5. **`routes.py`**：`POST /api/query` 改为 `StreamingResponse`（`text/event-stream`），工作流在独立线程运行，主线程流式转发事件；25 秒无事件发心跳注释保持连接；响应头带 `Cache-Control: no-cache` 和 `X-Accel-Buffering: no`。
6. **`finquery_service.py`**：`submit` 支持外部传入 task_id；入口推 `submitted` 事件；`PipelineStageError` 时推 `failed` 事件。

### 前端改动

7. **`api.ts`**：`query()` 改为 fetch + ReadableStream 解析 SSE，新增 `onProgress` 回调；非流式错误响应（401/429）仍按原方式解析；保留 300s 超时。
8. **`App.vue`**：静态 loading 文案替换为阶段清单——已完成阶段绿色 ✓，当前阶段转圈，同一阶段的连续事件合并显示；SQL 生成后直接展示 SQL 文本预览。
9. **`types.ts`**：新增 `ProgressEvent` 接口。
10. **`_conversation.scss`**：新增 `.progress-steps` 样式（沿用现有字阶变量）。
11. **`nginx.public.conf`**：`/api/query` location 加 `proxy_buffering off`，保证公共预览链路不缓冲 SSE。

### 验证

- 新增 `backend/tests/test_progress.py`：ProgressBus 收发、别名转发、SSE 流式端到端（事件顺序 + 最终 result）共 3 个测试，全部通过
- 适配 `test_guest_access.py` 中 mock service 的 ProgressBus 依赖
- 全量后端 unittest 42 个测试通过（仅 3 个与本次无关的既有 Windows 临时文件锁定错误）
- 前端 `npm run build`（含 vue-tsc 类型检查）通过
- Docker 开发容器 uvicorn `--reload` 自动热重载，无启动错误
