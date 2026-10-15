# 财务派生指标建设计划

> 状态：P0 已实现、完成四类报表口径抽样，并已重建和校验生产数据。

## 0. 实施进度（2026-10-15）

- 已在统一术语/公式注册表 `_terms.json` 中启用 `pe_ttm`、`pb`、`pcf_ttm`、`earnings_yield_ttm`、`liabilities_to_assets`、`liabilities_to_equity`。
- `stock_daily` 转换管道直接从注册表读取公式并生成上述字段；注册表是可执行公式的唯一事实来源。
- 管道版本升级为 2。旧 manifest 中没有对应记录版本时，源 CSV 即使未变化也会重新生成，避免沿用缺少指标列的旧 Parquet。
- Schema、字段别名、空值规则和验证测试已经对齐；负利润、负权益与零分母场景已有回归测试。
- 已用真实原始行情的20个分片完成临时转换：11,184行、20个股票、2021-11-15至2026-10-15，字段契约、主键、异常值规则和注册公式一致性校验均无错误。
- 已按一般企业、证券公司、商业银行和保险公司各5家完成口径抽样：`net_profit_ttm` 对应合并净利润TTM，`net_assets` 对应所有者权益合计，`cash_flow_ttm` 对应经营现金流TTM；P0名称和说明已据此改为显式口径。20家中19家的最新资产、负债可与财报快照精确对齐；`sh600816` 的整理财报停留在2023年而行情快照仍更新，列为数据新鲜度例外，不用于口径结论。
- 生产 `stock_daily` 已全量重建并压实：5,916个股票、18,237,130行、1990-12-19至2026-10-15；空主键、重复主键、异常值规则违规和公式不一致均为0。

## 1. 目标

让用户能够用自然语言稳定查询PE、PB、ROE、利润率、偿债、周转和现金流质量等派生指标，同时保证：

- 公式有唯一、可版本化的定义，而不是让模型临时猜公式；
- 任一历史交易日只使用当时已经披露的财报，避免未来数据泄漏；
- TTM、单季度、期末值和平均余额口径可追溯；
- 一般企业与银行、保险、证券等报表格式分开处理；
- 无意义值返回空值和原因，不通过极端数字误导用户；
- 查询结果能够展示分子、分母、财报期和披露日以供核验。

设计基线见：

- `docs/financial-metrics-glossary.md`
- `docs/financial-metrics-formulas.md`

## 2. 已确认的仓库现状

### 2.1 当前表与能力

- `stock_daily` 已有总市值、净利润TTM、现金流TTM、净资产、总资产和总负债，可单表计算第一批PE、PB、PCF等指标。
- `financial_statement` 当前只整理20个核心字段，覆盖资产、负债、权益、收入、利润、EPS和三类现金流。
- 原始 `stock-fin-data-xbx` 文件包含数百个明细字段，具备扩充毛利率、流动比率、EBITDA、净债务、周转率、FCF和ROIC的潜力。
- `financial_statement` 的利润与现金流字段是源报表累计口径，不是天然单季度值。
- Schema 的 `relations` 当前为空，查询代理按现有规则不能自行关联 `stock_daily` 与 `financial_statement`。

### 2.2 术语和公式机制

- 本次整理前，字段术语分散在 `_schema.json` 的 `aliases`、`business_terms` 与 `database_sources/trade_data.py` 的 `SYNONYMS`。
- 现在表级词、字段别名、财务概念和派生指标术语统一存放在 `backend/data/databases/trade_data/_terms.json`；Schema加载器负责校验并回填运行时Schema。
- P0 指标已有可执行公式注册项；其他指标仍处于术语与公式设计阶段。
- Schema 暴露已物化的 P0 字段；公式、期间类型和分母限制保存在统一注册表，行业适用性与 PIT 规则仍需后续扩展。

## 3. 建议目标架构

```text
原始财报 CSV
    │ 字段映射、格式分类、质量校验
    ▼
标准化财报事实表
    │ 累计值→单季度值、TTM、平均余额、修订版本处理
    ▼
财务期间快照层
    │ 与交易日按 publish_date 做 as-of 关联
    ▼
股票每日财务快照
    │ 由受控公式注册表计算
    ▼
stock_financial_metrics_daily
    │ Schema 暴露指标、别名、公式说明和质量标记
    ▼
自然语言检索 → 安全SQL → 可解释结果
```

建议使用“机器可读指标注册表 + 预计算每日指标表”，而不是只把公式写进模型提示：

1. 高频估值指标预计算，查询简单、速度稳定、历史结果可复现。
2. 注册表是公式的唯一事实来源，可用于生成Schema描述、ETL计算、测试和文档。
3. 查询代理只选择已注册指标，不自由创造未审计公式。
4. 结果表保留基础量与质量标记，回答时可以解释NM或数据缺失原因。

候选指标注册表字段：

| 字段 | 含义 |
|---|---|
| `metric_id` | 稳定英文标识，例如 `pe_ttm`。 |
| `label` / `aliases` | 中文名称、缩写和常见问法。 |
| `category` | 估值、盈利、偿债、效率、现金流、增长。 |
| `formula_version` | 公式版本，避免历史口径静默变化。 |
| `expression` | 受限表达式或明确的计算函数。 |
| `dependencies` | 物理字段或标准化中间量。 |
| `period_basis` | 时点、单季度、YTD、TTM、预测。 |
| `applicable_formats` | 一般企业、银行、保险、证券等。 |
| `invalid_policy` | 分母为零、负利润、负权益、跨零增长的处理。 |
| `unit` / `precision` | 比率、倍数、天数及展示精度。 |
| `aggregation_policy` | 公司级、整体聚合比率、中位数等。 |
| `explanation` | 面向用户的口径说明。 |

## 4. 时间与版本规则

### 4.1 披露日对齐

对交易日 `T`，财报候选记录必须满足 `publish_date <= T`。同一股票、同一 `report_date` 如有多个披露版本，选择 `publish_date` 最大且不晚于 `T` 的版本。

禁止使用最终修订后的历史财报回填早于修订披露日的交易日，否则回测和历史查询会产生未来数据泄漏。

### 4.2 单季度还原

假定源利润表和现金流量表为年内累计值：

- Q1单季 = Q1累计；
- Q2单季 = 半年累计 - Q1累计；
- Q3单季 = 三季累计 - 半年累计；
- Q4单季 = 年报累计 - 三季累计。

缺少前序累计期、会计年度变更或报表口径变化时，不强行还原，记录质量标记。

### 4.3 TTM桥接

- 年报：TTM = 当前年报累计值；
- Q1/半年报/Q3：`TTM = 上一年度年报 + 本年YTD - 上年同期YTD`。

所有组成财报都必须在目标交易日已经披露。若追求严格PIT，应按组成项各自的披露日判断，而不是使用事后整理的最终值。

### 4.4 平均余额

ROE、ROA和周转率第一版使用期初期末简单平均。后续如具备季度完整序列，可增加季度平均版本，但必须使用独立指标ID，不能静默替换。

## 5. 分阶段实施计划

### 阶段0：定义冻结与样本审计

状态：P0所需口径审计已完成；更广泛的字段覆盖率审计随P2明细扩充继续。

交付物：

- 审阅并冻结术语表、公式表和第一批指标范围；
- 对 `stock_daily.net_profit_ttm`、`cash_flow_ttm`、`net_assets` 的源口径做抽样核验；
- 统计一般企业、银行、保险、证券各类原始字段覆盖率和空值率；
- 确认金额单位、复权、市值单位和股票代码格式一致。

验收标准：随机选择不少于20家公司、4类报表格式和多个报告期，能把源CSV字段追溯到当前整理字段。

### 阶段1：P0单表估值指标

状态：已完成。代码、元数据、真实数据抽样、生产重建、全量校验和压实均已通过。

范围：PE TTM、PB、PCF TTM、盈利收益率、资产负债率、产权比率。

实施要点：

- 以当前 `stock_daily` 为输入建立首版派生指标；
- 明确PE/PB/PCF的NM规则；
- 输出分子、分母和质量标记；
- 不在这一阶段引入跨表关联。

验收标准：指定股票、日期、行业排行和行业整体比率均有确定口径；负利润、负权益、零分母测试通过。

### 阶段2：标准化财报期间层

状态：进行中。已修正财报事实表主键并完成全量基线校验；期间派生表尚待实现。

基线发现：原主键遗漏 `statement_format`，导致公司在一般企业、证券、银行等报表格式转换期间出现42组伪重复。主键已改为 `symbol + statement_format + report_date + publish_date`，591,973行全量校验后重复组为0。单季度和TTM计算必须在相同 `statement_format` 内连续计算；格式转换边界依赖不完整时返回空值，不跨格式相减。

范围：单季度、YTD、TTM、同比、平均余额、修订版本。

实施要点：

- 建立“股票 + 报告期 + 披露版本”的去重规则；
- 产生标准化的期间类型与会计年度字段；
- 实现单季度还原和TTM桥接；
- 保留每个计算组成项的来源报告期和披露日。

验收标准：年报、Q1、半年报、Q3四类期间都有固定测试；任意历史交易日不会读取未来披露或未来修订。

### 阶段3：P1核心财务指标

范围：PS TTM、归母净利率、标准ROE、ROA、总资产周转率、经营现金含量、CFO Margin、营收和利润同比/环比/CAGR。

实施要点：

- 添加受控的行情—财报PIT关联；
- 为关联补充Schema `relations`，但不要允许普通等值连接绕过披露日规则；
- 对公司级比率、行业整体比率和行业中位数分别建模。

验收标准：杜邦三因素乘积与直接ROE在容许误差内一致；累计值没有被误当成单季度值。

### 阶段4：P2财报明细扩充

优先整理以下原始字段族：

1. 现金、流动资产、流动负债、存货、应收和应付；
2. 短期借款、长期借款、应付债券、一年内到期债务、租赁负债；
3. 营业成本、利息费用、所得税费用；
4. 折旧、摊销、购建长期资产支付的现金；
5. 少数股东权益、优先股及其他权益工具。

由此上线毛利率、EBITDA Margin、EV/Sales、EV/EBIT、EV/EBITDA、流动/速动比率、D/E、净杠杆、利息保障、DSO/DIO/DPO/CCC、FCFF、FCFE和ROIC。

验收标准：每个物理字段在不同 `statement_format` 下有显式映射；不适用行业返回NA而非零。

#### 阶段4.1：拟新增资产负债表字段

下表字段已在原始CSV表头中确认存在。目标字段名是后续实施建议，本轮不修改ETL。

| 原始字段 | 建议目标字段 | 中文含义 | 主要用途 |
|---|---|---|---|
| `B_currency_fund@xbx` | `monetary_funds` | 货币资金 | 现金比率、净债务、EV；需识别受限资金。 |
| `B_bill_receivable@xbx` | `notes_receivable` | 应收票据 | 应收周转扩展口径、营运资本。 |
| `B_account_receivable@xbx` | `accounts_receivable` | 应收账款 | 应收周转率、DSO、营运资本。 |
| `B_bill_and_account_receivable@xbx` | `notes_and_accounts_receivable` | 应收票据及应收账款 | 新旧会计报表列报切换时的兼容字段。 |
| `B_receivable_financing@xbx` | `receivables_financing` | 应收款项融资 | 应收扩展口径、营运资本。 |
| `B_other_receivables_sum@xbx` | `other_receivables_total` | 其他应收款合计 | 非现金营运资本。 |
| `B_prepays@xbx` | `prepayments` | 预付款项 | 速动资产调整、营运资本。 |
| `B_inventory@xbx` | `inventory` | 存货 | 速动比率、存货周转、DIO。 |
| `B_total_current_assets@xbx` | `total_current_assets` | 流动资产合计 | 流动比率、速动比率、营运资本。 |
| `B_fixed_asset@xbx` | `fixed_assets` | 固定资产 | 资本密集度、资产结构和CapEx核验。 |
| `B_intangible_assets@xbx` | `intangible_assets` | 无形资产 | 投入资本、摊销与资产结构分析。 |
| `B_goodwill@xbx` | `goodwill` | 商誉 | ROIC的含商誉/剔除商誉版本。 |
| `B_st_borrow@xbx` | `short_term_borrowings` | 短期借款 | 有息债务、净债务、D/E。 |
| `B_bill_payable@xbx` | `notes_payable` | 应付票据 | DPO扩展口径、营运资本。 |
| `B_accounts_payable@xbx` | `accounts_payable` | 应付账款 | 应付周转率、DPO、营运资本。 |
| `B_bill_and_account_payable@xbx` | `notes_and_accounts_payable` | 应付票据及应付账款 | 新旧报表列报切换兼容。 |
| `B_contract_liab@xbx` | `contract_liabilities` | 合同负债 | 非现金营运资本。 |
| `B_payroll_payable@xbx` | `employee_benefits_payable` | 应付职工薪酬 | 非现金营运资本。 |
| `B_tax_payable@xbx` | `taxes_payable` | 应交税费 | 非现金营运资本。 |
| `B_other_payables_sum@xbx` | `other_payables_total` | 其他应付款合计 | 营运资本；需剔除其中有息项目。 |
| `B_noncurrent_liab_due_in1y@xbx` | `current_portion_noncurrent_liabilities` | 一年内到期的非流动负债 | 有息债务；需确认其中非有息组成。 |
| `B_st_bond_payable@xbx` | `short_term_bonds_payable` | 短期应付债券 | 有息债务。 |
| `B_total_current_liab@xbx` | `total_current_liabilities` | 流动负债合计 | 流动/速动/现金比率。 |
| `B_lt_loan@xbx` | `long_term_borrowings` | 长期借款 | 有息债务、净债务、EV。 |
| `B_bond_payable@xbx` | `bonds_payable` | 应付债券 | 有息债务、净债务、EV。 |
| `B_lease_libilities@xbx` | `lease_liabilities` | 租赁负债 | 调整后债务、EV、净杠杆；保留源字段拼写映射。 |
| `B_total_noncurrent_liab@xbx` | `total_noncurrent_liabilities` | 非流动负债合计 | 长期偿债结构。 |
| `B_preferred_shares@xbx` | `preferred_shares_equity` | 优先股权益 | EV桥接；需和负债性优先工具区分。 |
| `B_minority_equity@xbx` | `minority_interest` | 少数股东权益 | 合并口径EV和ROIC。 |

字段兼容原则：应收票据/应收账款、应付票据/应付账款同时存在“分列”和“合并列”。标准化层应按报告格式选择一套来源，不能把合并值与分列值再次相加。

#### 阶段4.2：拟新增利润表字段

| 原始字段 | 建议目标字段 | 中文含义 | 主要用途 |
|---|---|---|---|
| `R_operating_total_revenue@xbx` | `total_operating_revenue` | 营业总收入 | 金融及多业务报表收入口径。 |
| `R_operating_total_cost@xbx` | `total_operating_cost` | 营业总成本 | 成本结构分析。 |
| `R_operating_cost@xbx` | `operating_cost` | 营业成本 | 毛利润、毛利率、存货/应付周转。 |
| `R_operating_taxes_and_surcharge@xbx` | `taxes_and_surcharges` | 税金及附加 | EBIT桥接与成本分析。 |
| `R_sales_fee@xbx` | `selling_expenses` | 销售费用 | 费用率、经营利润桥接。 |
| `R_manage_fee@xbx` | `administrative_expenses` | 管理费用 | 费用率、经营利润桥接。 |
| `R_rad_cost_sum@xbx` | `research_and_development_expenses` | 研发费用 | 研发费用率、调整后投入资本。 |
| `R_financing_expenses@xbx` | `finance_expenses` | 财务费用 | EBIT桥接、资本结构分析。 |
| `R_interest_fee@xbx` | `interest_expense` | 利息费用 | 利息保障倍数、FCFF桥接。 |
| `R_fc_interest_income@xbx` | `interest_income_finance_expense_note` | 财务费用中的利息收入 | 净利息调整、EV口径核验。 |
| `R_income_tax_cost@xbx` | `income_tax_expense` | 所得税费用 | 有效税率、NOPAT。 |
| `R_minority_gal@xbx` | `minority_profit_loss` | 少数股东损益 | 合并净利润到归母净利润桥接。 |

`operating_revenue`、`operating_profit`、`total_profit`、`net_profit`、`parent_net_profit` 已在当前整理表中，无需重复增加，但需纳入标准化期间层。

#### 阶段4.3：拟新增现金流量表字段

| 原始字段 | 建议目标字段 | 中文含义 | 主要用途 |
|---|---|---|---|
| `C_initial_cce_balance@xbx` | `beginning_cash_equivalents` | 期初现金及现金等价物 | 现金变动核验。 |
| `C_final_balance_of_cce@xbx` | `ending_cash_equivalents` | 期末现金及现金等价物 | EV现金扣减、现金比率；当前已有字段可沿用。 |
| `C_depreciation_etc@xbx` | `depreciation_fixed_assets` | 固定资产折旧等 | EBITDA、FCFF、FCFE。 |
| `C_intangible_assets_amortized@xbx` | `amortization_intangible_assets` | 无形资产摊销 | EBITDA、FCFF、FCFE。 |
| `C_lt_deferred_expenses_amrtzt@xbx` | `amortization_long_term_deferred_expenses` | 长期待摊费用摊销 | EBITDA扩展口径。 |
| `C_cash_paid_for_assets@xbx` | `capital_expenditure_cash` | 购建长期资产支付的现金 | CapEx、简化FCF、FCFF和FCFE。 |
| `C_cash_received_of_borrowing@xbx` | `cash_proceeds_from_borrowings` | 取得借款收到的现金 | 净新增债务、FCFE。 |
| `C_cash_received_from_bond_issue@xbx` | `cash_proceeds_from_bond_issuance` | 发行债券收到的现金 | 净新增债务、FCFE。 |
| `C_cash_pay_for_debt@xbx` | `cash_repayment_of_debt` | 偿还债务支付的现金 | 净新增债务、FCFE。 |
| `C_cash_paid_of_distribution@xbx` | `cash_paid_for_dividends_interest` | 分配股利、利润或偿付利息支付的现金 | 股东回报与债务现金流；需拆分明细时另寻字段。 |
| `C_dap_paid_to_minority_holder@xbx` | `dividends_paid_to_minority` | 向少数股东支付的股利 | 合并口径现金流桥接。 |
| `C_inventory_decrease@xbx` | `inventory_decrease_cashflow_adjustment` | 存货减少调整项 | 间接法经营现金流核验，不替代资产负债表差额。 |
| `C_operating_items_decrease@xbx` | `operating_receivables_decrease_adjustment` | 经营性应收项目减少 | 间接法经营现金流核验。 |
| `C_increase_of_operating_item@xbx` | `operating_payables_increase_adjustment` | 经营性应付项目增加 | 间接法经营现金流核验。 |

#### 阶段4.4：字段派生组

物理字段进入标准化层后，再形成以下受控中间量：

| 中间量 | 组成 |
|---|---|
| `cash_and_equivalents` | 优先使用现金流量表期末现金及现金等价物；缺失时才按规则回退到货币资金，并设置质量标记。 |
| `receivables_for_turnover` | 根据报表列报版本选择“应收账款”或“应收票据及应收账款”，可选纳入应收款项融资。 |
| `payables_for_turnover` | 根据报表列报版本选择“应付账款”或“应付票据及应付账款”。 |
| `interest_bearing_debt` | 短期借款 + 短期债券 + 一年内到期有息债务 + 长期借款 + 应付债券 + 租赁负债。 |
| `depreciation_and_amortization` | 固定资产折旧 + 无形资产摊销 + 经确认应纳入的长期待摊摊销。 |
| `net_debt_issuance` | 借款现金流入 + 债券发行流入 - 偿债现金流出；非现金债务变化另行标记。 |
| `operating_working_capital` | 非现金流动经营资产 - 无息流动经营负债；排除现金、交易性金融资产及短期有息债务。 |

#### 阶段4.5：暂缓直接纳入的字段

- `*_diff_sri`、`*_diff_tbi` 等差额校验字段：保留在原始层用于质量核验，不作为用户查询指标。
- 同一会计项目的旧准则、新准则和合并展示字段：先在标准化层选择，避免重复计算。
- 银行、保险、证券专用资产负债与损益字段：后续按 `statement_format` 建独立指标包，不强塞进一般企业公式。
- 仅用于现金流量表间接法勾稽的调整项：用于质量检查，不替代资产负债表期初期末差额。

### 阶段5：查询系统接入

实施要点：

- 将指标注册表内容加入字段检索索引；
- Schema向查询代理提供指标ID、别名、物理列、口径、单位和可用性；
- 更新查询Skill，要求优先选择已物化派生指标，并返回基础量；
- 增加自然语言例句，如“银行股中PB最低的十家公司”“截至某日PE TTM低于15且ROE高于10%的股票”；
- 对无法计算的指标给出明确原因，不退化为近似字段。

验收标准：术语命中、字段召回、生成SQL和最终解释四层均有离线测试。

### 阶段6：质量、性能与发布

实施要点：

- 增加公式单元测试、PIT防泄漏测试、财报修订测试和行业适用性测试；
- 用已知公司公开年报手工验算代表性指标；
- 检查每日物化表的行数、唯一键、空值率、极值和公式恒等式；
- 为公式版本变化提供重算和迁移策略；
- 先以P0灰度发布，再逐批开放P1/P2。

## 6. 测试矩阵

| 场景 | 必测内容 |
|---|---|
| 正常盈利公司 | PE、PB、ROE、现金含量能手工复算。 |
| 亏损公司 | PE为NM，盈利收益率可保留负值。 |
| 负净资产公司 | PB、ROE和权益乘数为NM。 |
| 净现金公司 | 净债务及净杠杆允许为负。 |
| 零利息费用 | 利息保障倍数为NA，不产生无穷大。 |
| 财报修订 | 修订披露日前后使用不同版本。 |
| 披露延迟 | 报告期结束但尚未披露时继续使用上一可见财报。 |
| 季度累计 | Q2/Q3/Q4能正确还原单季度值。 |
| 跨零增长 | 不输出误导性同比百分比，改给增减额与标记。 |
| 金融企业 | 不计算通用毛利率、存货周转和CCC。 |
| 行业汇总 | 整体比率使用汇总分子/分母，中位数使用公司级有效值。 |

## 7. 风险与待确认事项

1. 已确认 `stock_daily.net_profit_ttm` 是合并净利润TTM而非严格归母口径；P0使用显式“合并口径”名称，标准归母PE需等待PIT财报层。
2. 已确认 `net_assets` 对应所有者权益合计，通常含少数股东权益；P0使用显式“总权益口径”名称，标准归母PB需等待PIT财报层。
3. 原始不同报表格式可能使用不同字段族，同名指标不能只靠一般企业样本映射。
4. A股会计准则下营业利润与估值用EBIT并非始终相同，需要明确调整项。
5. 总市值、财务数据的金额单位必须统一，否则倍数会出现固定数量级错误。
6. 预测PE、PEG、股息率等P3指标需要新增可靠数据源，不能从现有字段猜测。
7. P0代码、Schema、ETL和测试已经实施；P1及以后仍需完成PIT和期间标准化后分批上线。

## 8. 建议的实施顺序

```text
口径评审
  → P0（现有行情快照直接计算）
  → PIT/单季度/TTM基础层
  → P1（现有核心财报字段）
  → P2（扩充原始财报明细字段）
  → P3（预测、分红、股本等外部数据）
```

优先建议先完成P0与时间口径基础层。PE/PB看似只是除法，真正决定可信度的是归母口径、披露日、TTM、修订版本和无意义值处理。

