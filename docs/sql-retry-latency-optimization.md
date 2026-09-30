# SQL 修正重试延迟优化记录

## 问题

用户提问：当前 SQL 查询失败后，多久才会进行第二次查询？这个数字是否可以优化？

## 结论：没有固定等待时间

阅读代码后确认（`backend/app/querying/single_database_agent.py`）：SQL 执行失败后**没有人为的固定延迟**，失败后几乎立即（毫秒级）发起修正。「失败 → 第二次查询」的间隔本质上等于**一次完整 LLM 决策调用的耗时**（通常几秒到几十秒）。

具体链路：

1. DuckDB 执行失败，错误立即返回（本地执行，很快）
2. 错误信息作为 observation 附上修正指令，马上进入下一次 Agent 循环
3. `_validated_decision` 发起一次 LLM 调用，让模型生成修正后的 SQL ← **间隔全部来自这里**
4. 拿到新 SQL 立即执行

## 拖慢修正的三个因素

1. **修正调用的 prompt 过大**：第二次决策携带完整上下文（MCP 工具目录的完整 JSON Schema、检索 hits、低置信候选、Schema 文本、观测记录），首 token 延迟高
2. **输出校验的自我修正**：模型输出不合法时最多额外重试 2 次，每次都是一次完整 LLM 调用（`_validated_decision`）
3. **网络层重试和熔断**（仅网络故障时触发，与 SQL 错误无关）：最多 2 次重试（指数退避 0.8s / 1.6s），全部失败后熔断 30 秒（`model_client.py` `_post`）

## 讨论的优化方向

| 方向 | 说明 | 结论 |
|------|------|------|
| 精简修正 prompt（采用） | 修正时不带完整 schema 和工具目录，只传原 SQL、错误信息、相关表结构，减少 LLM 首 token 延迟 | 本次实施 |
| 修正调用换更快的模型 | 用轻量模型（如 LLM_FAST_MODEL）做修正，生成更快但修正能力可能略降 | 暂不实施，作为后续选项 |
| 暂不修改 | 保持现状 | 未选 |

## 实施的修改

`backend/app/querying/single_database_agent.py`：

- 新增 `_retry_payload()` 静态方法：SQL 修正调用的精简上下文
  - **去掉**：`mcp_tools`（工具目录完整 JSON Schema，体积最大）、`low_confidence_candidates`（低置信候选字段）、`retrieval.threshold`
  - **保留**：原问题 `query`、`schema_text`（表结构文本）、`confirmed_fields` / `confirmed_parameters`（用户确认字段/参数）、`tool_results`（失败观测记录）、`retrieval.selected_fields`（供 `_explicit_filter_error` 显式枚举值校验继续使用）
- Agent 循环内增加 `retry_after_failure` 标记：数据库工具执行失败且还有剩余调用次数时置位，下一次循环改用精简 payload
- 首次生成 SQL 的调用不受影响，仍使用完整上下文

效果：修正调用的输入 token 明显减少，LLM 首 token 更快返回，「SQL 失败 → 第二次查询」的间隔随之缩短。配合此前的 SSE 进度提示，用户此时会看到「查询失败，正在修正 SQL（第 n 次尝试）」。

## 验证

- 新增 `backend/tests/test_single_database_agent.py`：用 fake model client 和 fake MCP client 模拟首次 SQL 失败、二次成功的场景，断言修正调用的 payload 不含 `mcp_tools` 和 `low_confidence_candidates`、保留 `schema_text` 与 `selected_fields` — 通过
- 全量后端 unittest 43 个测试通过（仅 3 个与本次无关的既有 Windows 临时文件锁定错误）
- Docker 后端带 `--reload`，改动自动生效
