# 查询 → 出图自动衔接设计

## 问题现象

用户提问"获取最近一个月A股交易量前20的ETF及数据，并绘制柱状图"，系统正确返回了数字表格，但没有绘制任何图表。

根因：这是**复合意图**（查询新数据 + 可视化），而 `preprocessing.py` 的路由是三选一、单路由。预处理器识别到需要新数据后路由到 `database_query`，该链路只有 SQL → 表格 + 文字说明，没有任何图表能力；图表只存在于 `data_qa` 链路，而 `data_qa` 被明确定义为"分析已有结果、不查新数据"。"并绘制柱状图"半句在路由那一刻就被丢弃。

## 方案对比

| 方案 | 说明 | 结论 |
|---|---|---|
| A. 查询后自动衔接 data_qa | 预处理器额外提取 `presentation: none/chart/report`；查询成功后 LangGraph 条件边进入 `visualize_result` 节点，把本轮结果交给 data_qa agent 出图，合并进同一响应 | **采纳**：尊重工作流边界，前端零改动 |
| B. 前端自动追问 | 前端检测"绘制/图表"等词，表格返回后自动补发一轮"画成图" | 拒绝：意图识别退化为前端正则，多一轮请求，对话出现合成消息 |
| C. ResponseGenerator 直接出图 | 查询链路内嵌图表生成 | 拒绝：两套图表能力并行，违反工作流边界 |

## 实现

```text
用户复合提问
  → _preprocess（presentation=chart/report，随 state 经 checkpointer 跨澄清续跑保留）
  → retrieve_schema → prepare_single_database → execute_single_database（表格照常生成）
  → _after_execute 条件边：presentation ∈ (chart, report) 且执行成功且有行 → visualize_result
  → _visualize_result：
      emit "正在生成图表"（SSE 新阶段 visualizing）
      用 mcp_execution 构造 recent_result 上下文（形状与 SessionContext.recent_result_context 一致）
      data_qa_agent.run(原始用户问题, contexts, access_scope)
      ResultBuilder.attach_report：report / report_tool_calls 并入 result，steps 追加说明
  → END
```

关键决策：

1. **data_qa 仍是图表的唯一生产者**，只是数据源从"上一轮结果"扩展为"本轮刚查完的结果"，图表工具白名单、字段校验、`max_tool_calls` 全部复用。
2. **降级策略**：图表生成失败（`PipelineStageError`）或模型只输出 answer 时，保留已成功的表格结果，仅在 `execution_log` 追加失败记录——图表是锦上添花，不能拖垮查询。
3. **SKILL.md 规则放宽**：原规则"只有用户明确要求报告才输出 report"放宽为"明确要求图表/可视化时同样输出 report，正文可简短"。不为图表新增独立 output action，避免改动 `AnalysisReport` 契约。
4. **presentation 是模型提取的显式字段**，非法值在解析层归一为 `none`（输出清洗，不是语义回退）。
5. 前端零改动：`QueryResult.report` 与图表渲染、SSE 阶段清单均为现成机制。

## 测试

- `test_preprocessing.py`：`chart` 被保留、非法值归一 `none`、`data_qa`/`direct_response` 恒为 `none`。
- `tests/test_visualize_chaining.py`（新）：
  - `_after_execute` 谓词：chart/report + 成功 + 有行 → visualize；none / 失败 / 空行 → end；
  - `ResultBuilder.attach_report`：合并正确且不修改原 dict；answer-only 时原样返回；
  - `_visualize_result` 节点：stub agent 验证原始问题被传入；agent 抛错时降级为仅表格并记录 `execution_log`。

## 验证

`cd backend && .venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"` 通过（`test_guest_access.py` 3 个 WinError 32 为既有问题）。端到端验收（需真实模型）：提问"获取最近一个月A股交易量前20的ETF及数据，并绘制柱状图"，应看到进度序列追加"正在生成图表"，最终响应同时包含结果表格和柱状图。
