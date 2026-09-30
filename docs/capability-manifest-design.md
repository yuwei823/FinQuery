# 能力清单注入：矫正 direct_response 的越界回答

## 问题现象

用户问"你能查到哪些金融数据？覆盖哪些市场、指标和时间段？"时，Agent 回答声称支持 A股、港股、美股、债券、基金、期货、宏观经济指标，并引导用户"查询茅台""今日纳斯达克指数"——全部超出实际能力。

根因：`backend/app/preprocessing.py` 的 system prompt 完全静态，对启用的数据库、表和时间范围一无所知。`direct_response` 的回答由预处理器在同一次 LLM 调用中顺手生成，模型没有任何事实依据，只能凭"金融问数系统"的刻板印象编造。

## 设计讨论与取舍

讨论过的备选架构：

| 方案 | 结论 |
|---|---|
| 能力清单注入预处理器（采纳） | 不增加 LLM 调用次数；权限过滤在构建期完成；schema 是唯一事实来源 |
| 拆分独立的 direct-response agent 节点 | 拒绝：多一次 LLM 调用、闲聊延迟翻倍，收益不成比例 |
| RAG 检索能力文档 | 拒绝：能力信息只有几百字，检索是杀鸡用牛刀 |
| 模板硬答能力问题 | 拒绝：僵硬，无法处理能力问题的各种变体问法 |

关键设计原则：

1. **单一事实来源**：能力声明不写进 prompt 字符串或前端，而是利用 `_schema.json` 已有的 `scenario` / 表级 `label` / `domain` / `description`，另补两个顶层可选字段 `time_coverage`、`example_questions`。
2. **权限过滤在构建期完成**：能力清单只包含当前用户 `AccessScope` 可见的数据库和表，访客看不到的表根本不出现在 prompt 里——不依赖模型自觉"保密"。这与现有"schema visibility 贯穿检索与执行"的授权哲学一致。
3. **负面边界靠指令 + 替代示例**：prompt 追加边界规则，清单未覆盖的请求必须明确回答「当前未接入」，并从清单示例问法中推荐 1-2 个替代，避免生硬的拒绝。
4. **不增加调用次数**：清单注入预处理器的同一次 `chat_json`，闲聊延迟不变。

## 实现

```text
_schema.json（scenario / time_coverage / example_questions / 表级 label+description）
      │  load_database_catalog() 透出第 6 个返回值 database_meta → DATABASE_META
      ▼
backend/app/capabilities.py
      render_capability_manifest(scope) → ≤300 token 紧凑文本，按权限范围缓存
      ▼
QueryWorkflow._preprocess（state.access_scope 构建清单）
      ▼
RequestPreprocessor.prepare(query, context, capability)
      system prompt 追加能力清单 + 边界规则
```

改动点：

- `backend/data/databases/trade_data/_schema.json`：新增 `time_coverage`（按 Parquet 实际查询结果填写：A股日线 1990-12 至 2026-09、指数 2005-06 起、ETF 2010-01 起、财报 2007 年起）和 3 条 `example_questions`。
- `backend/app/database.py`：`load_database_catalog()` 返回 6 元组，模块级导出 `DATABASE_META`。
- `backend/app/capabilities.py`（新）：`render_capability_manifest(scope)`，空权限返回"当前账号暂无可查询的数据表。"，按 `(allowed_databases, allowed_tables)` 缓存。
- `backend/app/preprocessing.py`：`prepare()` 新增 `capability` 参数（默认空，向后兼容），非空时向 system prompt 追加清单与边界规则。
- `backend/app/workflows/query_graph.py`：`_preprocess` 节点按 `access_scope` 构建清单并传入。

## 测试

- `tests/test_capabilities.py`（新）：全权限包含场景/表/时间覆盖/示例；部分权限隐藏未授权表；空权限不泄露任何表名；同 scope 命中缓存。
- `tests/test_preprocessing.py`：fake model 记录 system prompt，断言清单与"边界规则"被注入、空 capability 时 prompt 不变。
- `tests/test_database_switches.py`：解包改为 6 元组并断言 meta 默认值。

## 验证

`cd backend && .venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"` 全部通过（`test_guest_access.py` 的 3 个 WinError 32 为改动前既有问题）。未做真实 LLM 调用；上线后可用"你能查什么数据""你能查美股吗"两问人工验收边界行为。

## 后续可选

- `data_qa` / `response_generator` 的 prompt 如需"知道自己是谁"，可复用同一个 `render_capability_manifest`，口径永远一致。
- `time_coverage` 目前手工声明；若数据更新频繁，可由 pipeline 在生成 Parquet 时自动写回真实日期区间。
