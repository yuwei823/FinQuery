# 财务派生指标术语表

> 用途：解释自然语言查询、指标注册表和数据工程中的财务术语。运行时唯一术语源是
> `backend/data/databases/trade_data/_terms.json`；本文是便于评审的阅读版，不应单独新增术语。
>
> 当前数据能力以 `backend/data/databases/trade_data/_schema.json` 和 `backend/scripts/*_pipeline.py` 为准。

## 1. 口径约定

| 术语 | 英文/缩写 | 推荐别名 | 定义与口径 |
|---|---|---|---|
| 时点值 | Point-in-time value | 期末值、存量 | 资产负债表在报告期末的余额，例如总资产、存货、股东权益。回报率与周转率的分母优先使用期初和期末平均值。 |
| 期间值 | Flow value | 发生额、流量 | 利润表或现金流量表在一段期间内的累计发生额，例如收入、净利润、经营现金流。 |
| 单季度值 | Single-quarter value | 当季值、季度发生额 | 从累计披露值还原的单一季度发生额；Q2、Q3、Q4不能直接使用半年报、三季报、年报累计值。 |
| 滚动十二个月 | Trailing Twelve Months, TTM/LTM | 滚动年度、过去十二个月 | 截至指定报告期的连续十二个月期间值。非年报期通常用“上一年年报 + 本年累计 - 上年同期累计”计算。 |
| 披露日可见 | Point-in-time/PIT | 当时可知、无未来数据 | 对任一交易日，只能使用 `publish_date <= trade_date` 的财报；同一报告期有修订时，使用当时已披露的最新版本。 |
| 平均余额 | Average balance | 平均资产、平均权益 | 通常为 `(期初余额 + 期末余额) / 2`，用于ROA、ROE、周转率等跨期间指标。 |
| 归母口径 | Attributable to owners of parent | 归母、母公司股东口径 | 分子使用归母净利润时，分母应使用归母股东权益，避免与少数股东权益错配。 |
| 合并口径 | Consolidated | 集团口径 | 包含控股子公司全部资产、负债、收入和利润；涉及EV时需与少数股东权益口径保持一致。 |
| 一般企业口径 | Industrial/company format | 工商企业、非金融企业 | 适用于通常的流动资产、存货、营业成本、净债务等定义；不应直接套用于银行、券商、保险。 |
| 无意义值 | Not meaningful, NM | 不适用、不可比 | 例如净利润小于等于零时的PE、净资产小于等于零时的PB。系统应返回空值及原因，不应给出误导性倍数。 |

## 2. 市值与估值基础术语

| 术语 | 英文/缩写 | 推荐别名 | 定义与关系 |
|---|---|---|---|
| 总市值 | Market Capitalization | 市值、权益市值 | 收盘价乘以总股本；当前 `stock_daily.total_market_cap` 已直接提供。 |
| 流通市值 | Float Market Capitalization | 自由流通市值 | 流通股份对应的市值，不应作为标准PE/PB分子。 |
| 企业价值 | Enterprise Value, EV | 公司价值、企业估值 | 权益市值 + 有息债务 + 优先股 + 少数股东权益 - 现金及现金等价物；用于与企业整体经营指标匹配。 |
| 净债务 | Net Debt | 有息净负债 | 短期有息债务 + 长期有息债务 + 租赁负债 - 现金及现金等价物。不能用“总负债 - 现金”替代。 |
| 每股收益 | Earnings per Share, EPS | 基本EPS、稀释EPS | 归母普通股股东净利润除以加权平均普通股股数；基本与稀释口径必须区分。 |
| 每股净资产 | Book Value per Share, BVPS/BPS | 每股账面价值、每股净值 | 归母股东权益除以期末普通股股数。 |
| 市盈率 | Price/Earnings, PE/P/E | 本益比、收益倍数 | 权益市值除以归母净利润，或股价除以EPS；必须标明TTM、静态或预测口径。 |
| 滚动市盈率 | Trailing PE, PE TTM | 动态市盈率TTM、滚动PE | 总市值除以归母净利润TTM；利润小于等于零时标记NM。 |
| 静态市盈率 | Static PE | 年报PE | 总市值除以上一完整会计年度归母净利润。 |
| 预测市盈率 | Forward PE | 远期PE、一致预期PE | 总市值除以未来十二个月或下一财年预测净利润；需要外部分析师预测数据。 |
| 市净率 | Price/Book, PB/PBV | 股价净值比 | 权益市值除以归母股东权益，或股价除以每股净资产。 |
| 市销率 | Price/Sales, PS/P/S | 营收倍数 | 权益市值除以营业收入TTM；其分子属于股东、分母属于全体资本提供者，跨杠杆比较时EV/Sales更一致。 |
| 市现率 | Price/Cash Flow, PCF/P/CF | 现金流倍数 | 权益市值除以经营活动现金流TTM；不是PE的简单替代。 |
| 企业价值倍数 | EV/EBITDA | 企业倍数 | 企业价值除以EBITDA TTM；资本开支高的企业仍可能没有可分配现金。 |
| EV/EBIT | Enterprise Value/EBIT | 企业价值营业利润倍数 | 企业价值除以EBIT TTM，包含折旧摊销对利润的影响。 |
| EV/Sales | Enterprise Value/Sales | 企业价值营收倍数 | 企业价值除以营业收入TTM，比PS在资本口径上更一致。 |
| 盈利收益率 | Earnings Yield | PE倒数、收益市值比 | 归母净利润TTM除以总市值；负利润可以保留为负值，但应与PE的NM规则区分。 |
| 自由现金流收益率 | FCF Yield | 自由现金流率 | 自由现金流除以对应价值分子；FCFE对应权益市值，FCFF对应EV。 |
| PEG | PE/Growth | 市盈增长比率 | PE除以预期盈利增长率；增长率的单位及预测期限必须固定，负PE或非正增长通常为NM。 |

## 3. 盈利能力术语

| 术语 | 英文/缩写 | 推荐别名 | 定义与关系 |
|---|---|---|---|
| 毛利润 | Gross Profit | 毛利 | 营业收入减营业成本。金融企业通常不适用通用毛利口径。 |
| 毛利率 | Gross Margin | 销售毛利率 | 毛利润除以营业收入。 |
| 息税前利润 | EBIT | 税息前利润 | 通常以营业利润为起点调整非经营项目；不能在所有会计格式中机械等同于营业利润。 |
| 息税折旧摊销前利润 | EBITDA | 息税折旧前利润 | EBIT加折旧与摊销，是粗略经营现金能力指标，不等于经营现金流或自由现金流。 |
| 税后经营利润 | Net Operating Profit After Tax, NOPAT | 税后EBIT | EBIT乘以 `(1 - 经营适用税率)`，不扣利息，服务于ROIC和FCFF。 |
| 营业利润率 | Operating Margin | 经营利润率 | EBIT或明确的营业利润除以营业收入；实现时必须固定分子定义。 |
| EBITDA利润率 | EBITDA Margin | EBITDA率 | EBITDA除以营业收入。 |
| 净利率 | Net Margin | 销售净利率 | 净利润除以营业收入；受资本结构与利息费用影响。 |
| 净资产收益率 | Return on Equity, ROE | 权益回报率 | 归母净利润TTM除以平均归母股东权益。负权益时通常为NM。 |
| 总资产收益率 | Return on Assets, ROA | 资产回报率 | 推荐使用净利润TTM除以平均总资产；也可用NOPAT口径，但必须另设指标ID。 |
| 投入资本回报率 | Return on Invested Capital, ROIC/ROC | 投资资本回报率 | NOPAT除以平均投入资本，用于和WACC比较。 |
| 投入资本 | Invested Capital | 营运资本投入 | 常用口径为归母/总权益 + 有息债务 - 现金及现金等价物；需固定少数股东权益和租赁负债处理。 |
| 资本周转率 | Capital Turnover | 投入资本周转率 | 营业收入TTM除以平均投入资本。ROIC可拆为税后营业利润率乘以资本周转率。 |
| 杜邦分析 | DuPont Analysis | ROE分解 | 三因素关系：ROE = 净利率 × 总资产周转率 × 权益乘数。 |

## 4. 偿债与资本结构术语

| 术语 | 英文/缩写 | 推荐别名 | 定义与关系 |
|---|---|---|---|
| 流动比率 | Current Ratio | 短期偿债比率 | 流动资产除以流动负债。 |
| 速动比率 | Quick Ratio | 酸性测试比率 | `(流动资产 - 存货 - 其他低流动性项目)` 除以流动负债；不同数据商定义可能不同。 |
| 现金比率 | Cash Ratio | 现金偿债比率 | 现金及现金等价物除以流动负债。 |
| 资产负债率 | Liabilities/Assets | 负债率、总负债率 | 总负债除以总资产；总负债包括无息经营负债，不等同于有息债务率。 |
| 产权比率 | Liabilities/Equity | 负债权益比 | 总负债除以股东权益；与有息债务/权益必须使用不同指标ID。 |
| 有息债务权益比 | Debt/Equity, D/E | 杠杆率 | 有息债务除以股东权益。 |
| 净债务/EBITDA | Net Debt/EBITDA | 净杠杆倍数 | 净债务除以EBITDA TTM；EBITDA小于等于零时通常为NM。 |
| 利息保障倍数 | Interest Coverage | 已获利息倍数 | EBIT TTM除以利息费用TTM；利息费用为零或负值时需单独标记。 |
| 权益乘数 | Equity Multiplier | 财务杠杆倍数 | 平均总资产除以平均股东权益，是杜邦分解的杠杆项。 |

## 5. 营运效率与现金流术语

| 术语 | 英文/缩写 | 推荐别名 | 定义与关系 |
|---|---|---|---|
| 总资产周转率 | Asset Turnover | 资产周转 | 营业收入TTM除以平均总资产。 |
| 应收账款周转率 | Receivables Turnover | 应收周转率 | 营业收入或赊销收入除以平均应收账款；缺少赊销收入时使用营业收入并披露代理口径。 |
| 应收账款周转天数 | Days Sales Outstanding, DSO | 应收天数 | 平均应收账款除以营业收入TTM，再乘以365。 |
| 存货周转率 | Inventory Turnover | 存货周转 | 营业成本TTM除以平均存货。 |
| 存货周转天数 | Days Inventory Outstanding, DIO | 存货天数 | 平均存货除以营业成本TTM，再乘以365。 |
| 应付账款周转天数 | Days Payables Outstanding, DPO | 应付天数 | 平均应付账款除以营业成本或采购额，再乘以365；缺少采购额时应披露代理口径。 |
| 现金转换周期 | Cash Conversion Cycle, CCC | 现金周期 | DSO + DIO - DPO。 |
| 营运资本 | Working Capital | 净营运资本 | 流动资产减流动负债；估值中的“非现金营运资本”会进一步剔除现金和有息短债。 |
| 资本开支 | Capital Expenditure, CapEx | 资本性支出 | 购买长期资产支付的现金；不可简单等同于投资活动现金流净额。 |
| 自由现金流 | Free Cash Flow, FCF | 企业自由现金流 | 必须明确是FCFF还是FCFE；不得只写“经营现金流减投资现金流”。 |
| 企业自由现金流 | Free Cash Flow to Firm, FCFF | 公司自由现金流 | NOPAT + 折旧摊销 - 资本开支 - 非现金营运资本增加额。 |
| 股权自由现金流 | Free Cash Flow to Equity, FCFE | 股东自由现金流 | 净利润 + 折旧摊销 - 资本开支 - 营运资本增加额 + 净新增有息债务。 |
| 经营现金含量 | CFO/Net Income | 盈利现金比、现金净利比 | 经营现金流TTM除以净利润TTM，用于观察会计利润的现金实现程度。 |
| 经营现金流率 | CFO Margin | 经营现金流利润率 | 经营现金流TTM除以营业收入TTM。 |

## 6. 增长与股东回报术语

| 术语 | 英文/缩写 | 推荐别名 | 定义与关系 |
|---|---|---|---|
| 同比增长率 | Year-over-Year, YoY | 同比、年增长率 | 当前期间值除以上年同期间值减一；当前与基期必须是相同季度或相同累计区间。 |
| 环比增长率 | Quarter-over-Quarter, QoQ | 季度环比 | 当前单季度值除以上一单季度值减一，不能对累计值直接做环比。 |
| 复合增长率 | Compound Annual Growth Rate, CAGR | 年复合增速 | `(期末值 / 期初值)^(1/年数) - 1`；跨零或非正值时通常不计算。 |
| 股利支付率 | Dividend Payout Ratio | 分红率 | 普通股现金股利除以归母净利润。需要分红数据。 |
| 留存率 | Retention Ratio | 利润留存率 | `1 - 股利支付率`。 |
| 可持续增长率 | Sustainable Growth Rate | 内生增长率 | 留存率乘以ROE，是简化稳态关系，不是分析师预测增速。 |
| 股息率 | Dividend Yield | 现金分红收益率 | 过去十二个月每股现金股利除以当前股价，或现金股利总额除以总市值。 |

## 7. 关系总览

```text
价格/市值
├─ PE  ← 归母净利润TTM（核心伴随变量：增长、风险、派息）
├─ PB  ← 归母股东权益（核心伴随变量：ROE）
├─ PS  ← 营业收入TTM（核心伴随变量：净利率）
└─ PCF ← 经营现金流TTM（需结合资本开支与营运资本）

企业价值 EV
├─ EV/EBITDA
├─ EV/EBIT
└─ EV/Sales

ROE = 净利率 × 总资产周转率 × 权益乘数
ROIC = 税后营业利润率 × 投入资本周转率
CCC = DSO + DIO - DPO
FCFF = NOPAT + 折旧摊销 - CapEx - Δ非现金营运资本
```

## 8. 参考资料

- [SEC Investor.gov：P/E定义](https://www.investor.gov/introduction-investing/investing-basics/glossary/price-earnings-pe-ratio)
- [IAS 33：每股收益](https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2022/issued/part-a/ias-33-earnings-per-share.pdf?bypass=on)
- [IAS 1：流动资产和流动负债分类](https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2022/issued/part-a/ias-1-presentation-of-financial-statements.pdf?bypass=on)
- [IAS 7：经营、投资和筹资现金流](https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2022/issued/part-a/ias-7-statement-of-cash-flows.pdf?bypass=on)
- [Aswath Damodaran：Financial Ratios and Measures](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/definitions.html)
- [Aswath Damodaran：估值倍数及其基本面驱动因素](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/littlebook/multiples.htm)

