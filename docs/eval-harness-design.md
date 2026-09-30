# FinQuery Agent 评测体系设计

## 分层评测框架

Agent 是多阶段流水线，评测按层拆解，每层有各自的确定性指标，最后才是端到端：

| 层 | 指标 | 测法 | 状态 |
|---|---|---|---|
| 意图路由 | 路由准确率、`presentation` 正确率、越界拒绝正确率 | 标注集比对（轻量 LLM 调用） | 后续迭代 |
| Schema 检索 | 字段级 Recall、表级命中率、MRR | `SchemaIndex.retrieve()` 离线跑（每题 1 embed + 1 rerank） | **已落地** |
| SQL 质量 | 合法率、一次成功率、执行准确率 | 黄金 SQL/结果集比对（零 LLM） | **已落地（快照与比对工具）** |
| 幻觉/忠实度 | 答案数字可溯源率、越界承诺检测、报告引用合规率 | 数字回查结果行、`forbidden_in_answer` 子串匹配、LLM-judge | 后续迭代 |
| 速度 | 端到端与分阶段 p50/p95 | 进度事件自带 `ts` 时间戳 | 后续迭代 |
| 错误鲁棒性 | 重试成功率、各 `PipelineStageError` 分布 | `execution_log` 聚合 | 后续迭代 |

## 本次落地：评测集 + 离线 runner

### 数据集 `backend/eval/dataset.json`

```json
{
  "version": 1,
  "cases": [
    {
      "id": "q001",
      "category": "simple_query",
      "query": "……",
      "expected_route": "database_query",
      "expected_presentation": "chart",        // 可选，仅复合意图
      "retrieval_terms": ["……"],               // 查询类必填：手写，与预处理器质量解耦
      "expected_tables": ["trade_data.stock_daily"],
      "expected_fields": ["trade_data.stock_daily.close"],  // 正确 SQL 必需的最小字段集
      "golden_sql": "SELECT …",                // 可选：黄金 SQL
      "expected_result": {"columns": [], "rows": []},       // 由 golden 子命令生成
      "forbidden_in_answer": ["支持美股"]       // 正向承诺类子串，出现即判幻觉
    }
  ]
}
```

- 类别：`chitchat / out_of_scope / simple_query / complex_query / compound / clarification`；
- `retrieval_terms` 手写——测的是"给定正确检索词，检索链路能否召回正确字段"，与预处理器解耦；
- `forbidden_in_answer` 必须写成**正向承诺**模式（如"支持美股""为您查询到"），因为正确的拒绝回答也会提及"美股"等词；
- 种子集 13 题覆盖六类，字段名均已对照 `_schema.json` 核实。

### Runner `backend/scripts/evaluate.py`

```powershell
cd backend
# 黄金 SQL 校验 + 结果快照（零 LLM 成本）
.venv/Scripts/python.exe scripts/evaluate.py golden          # 执行并写回 expected_result
.venv/Scripts/python.exe scripts/evaluate.py golden --check  # 与已有快照比对，漂移则非零退出

# Schema 检索召回评测（每题 1 embed + 1 rerank 小额调用）
.venv/Scripts/python.exe scripts/evaluate.py recall --k 20
```

- `golden` 复用 `DuckDbEngine.execute()`，黄金 SQL 与模型 SQL 走同一套只读校验与执行路径；
- `recall` 逐题输出字段召回/表命中/MRR，汇总后写报告到 `backend/eval/reports/`（已 gitignore）；
- 指标实现在 `backend/eval/scoring.py`，`compare_result_sets` 列序行序不敏感、数值容差 1e-6，后续在线档执行准确率直接复用。

### 冻结数据快照（保证可复现）

数据目录在进程启动时由 `CURATED_DATA_ROOT` 决定。评测前复制一份 curated 数据：

```powershell
robocopy D:\trade_data_curated D:\trade_data_eval /E
$env:CURATED_DATA_ROOT="D:/trade_data_eval"
```

之后所有评测命令在该 shell 中运行，结果不因每日数据更新而漂移。

## 测试

`tests/test_eval_scoring.py`：三个召回指标、结果集比对（容差/列乱序/行乱序/不匹配）、数据集加载校验（种子集合法、未知类别与缺字段报错）。

## 后续迭代路线

1. 在线档 runner：走真实模型跑全链路，复用进度事件采集分阶段延迟，`expected_route`/`forbidden_in_answer` 打分路由与边界，结果集比对算执行准确率；
2. 幻觉自动检查：抽取答案数字回查结果行；报告 `source_task_id`/字段引用合规统计；
3. LLM-judge：仅用于报告综合质量，rubric 含数据忠实、结论有据、无编造；
4. 扩充评测集至 50~100 题，在线档按"改动跑小集、定期跑全量"控制成本。
