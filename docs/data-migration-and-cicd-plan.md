# FinQuery 数据迁移、云上发布与 CI/CD 方案

> 状态：Draft for Review  
> 更新日期：2026-09-18  
> 范围：FinQuery 应用、`D:\trade_data` 每日行情数据、开发/测试/生产环境

## 1. 背景与目标

当前 FinQuery 由 Vue 3 前端和 FastAPI + LangGraph 后端组成。行情数据位于本地 Windows 目录 `D:\trade_data`，每天自动更新。该目录约 35 GiB、约 5.6 万个文件，大部分是按股票或日期拆分的 CSV，并存在混合编码、首行说明文字、非安全字段名和嵌套目录等情况。

本方案目标：

1. 保持本地开发简单，并可读取每日更新的数据。
2. 建立可靠、可追踪、可回滚的数据发布流水线。
3. 将 FinQuery 安全部署到线上。
4. 解耦应用发布与每日数据发布。
5. 从低成本单机平滑扩展到多实例生产环境。
6. 通过 CI/CD 自动完成测试、构建、预发布和生产发布。

## 2. 核心决策

| 领域 | 推荐决策 | 说明 |
|---|---|---|
| 容器化 | Docker | 统一本地、CI、预发布和生产环境 |
| 初期编排 | Docker Compose | 单应用阶段不立即引入 Kubernetes |
| 扩展编排 | ACK Kubernetes | API/Worker 需要多副本后再迁移 |
| 原始及历史数据 | Alibaba Cloud OSS | 长期事实来源、版本管理和备份 |
| 本地分析 | DuckDB + Parquet | 适合开发、单机和少量用户 |
| 生产分析 | 初期 DuckDB，后期 ClickHouse | 根据并发量和数据量逐步迁移 |
| 应用数据 | PostgreSQL | 用户、任务、会话、记忆、审计、发布记录 |
| 任务与缓存 | Redis | 异步任务、状态共享和多实例 |
| 镜像仓库 | Alibaba Cloud ACR | 保存不可变应用镜像 |
| 前端托管 | OSS + CDN | Vue 构建产物无需常驻容器 |
| 基础设施 | Terraform | 环境可复制、变更可审查 |
| CI/CD | GitHub Actions | PR 验证、镜像构建和环境发布 |
| 密钥 | KMS Secrets Manager | 避免生产密钥进入仓库或镜像 |
| 日志监控 | SLS，后续增加 ARMS | 集中日志、指标和告警 |

不建议将全部行情写入 PostgreSQL。PostgreSQL 用于事务型应用状态；行情、资金流和财务宽表由 DuckDB 或 ClickHouse 承载。

## 3. 总体架构

```text
本地 Windows
D:\trade_data（每日自动更新）
        │
        ▼
Docker 数据发布任务
发现增量 → 清洗 → 校验 → Parquet → manifest
        │ 仅主动发起 HTTPS 出站连接
        ▼
Alibaba OSS
├── raw/                 可选原始备份
├── curated/             标准化 Parquet
├── manifests/           数据版本和 current 指针
└── rejected/            失败文件和错误报告
        │
        ├───────────────────────┐
        ▼                       ▼
ClickHouse                ECS 本地缓存
生产分析数据库               初期 DuckDB 方案
        │                       │
        └───────────┬───────────┘
                    ▼
              FinQuery Backend
              FastAPI + Worker
          ┌─────────┼─────────┐
          ▼         ▼         ▼
   PostgreSQL     Redis    DashScope
   用户/任务/记忆  队列/缓存   LLM/Embedding
          │
          ▼
     ALB / HTTPS / 域名
          │
          ├── /api → Backend
          └── / → OSS/CDN 中的 Vue 静态文件
```

应用和数据使用两套独立流水线：

- **应用流水线**发布前端、API 和 Worker。
- **数据流水线**每天处理 `D:\trade_data` 增量并发布数据版本。

任何一条流水线失败都不得破坏另一条流水线的线上版本。

## 4. 环境与配置规划

| 环境 | 用途 | 数据 |
|---|---|---|
| Local | 开发和调试 | 本地样本或 `D:\trade_data` 只读挂载 |
| CI | 自动化测试 | 仓库内小型、脱敏、确定性 fixture |
| Staging | 生产前验证 | 独立 OSS prefix、数据库和密钥 |
| Production | 正式服务 | 生产 OSS、RDS、分析数据库和域名 |

Staging 与 Production 不共享数据库账号、Redis、OSS 写入路径或密钥。

建议配置：

```env
FINQUERY_ENV=local
ANALYTICS_BACKEND=duckdb
TRADE_DATA_ROOT=/data/raw
CURATED_DATA_ROOT=/data/curated
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
CLICKHOUSE_URL=https://...
OBJECT_STORAGE_PROVIDER=minio
OBJECT_STORAGE_BUCKET=finquery-data-local
```

生产环境切换为：

```env
FINQUERY_ENV=production
ANALYTICS_BACKEND=clickhouse
OBJECT_STORAGE_PROVIDER=oss
OBJECT_STORAGE_BUCKET=finquery-data-prod
```

生产密钥不得写入仓库、Dockerfile、Compose 文件或镜像层。

## 5. 本地开发方案

新增根目录 `compose.yaml`：

```text
services:
  frontend
  api
  worker
  postgres
  redis
  clickhouse       # 通过 profile 可选启动
  minio            # 本地模拟 OSS，可选启动
  data-publisher
```

提供两种 profile：

```powershell
# 日常轻量开发
docker compose --profile lite up

# 模拟完整生产环境
docker compose --profile full up
```

原始数据只读挂载：

```yaml
volumes:
  - D:/trade_data:/data/raw:ro
  - finquery_curated:/data/curated
```

标准化产物写入独立 volume 或 `D:\trade_data\.finquery\`，不能覆盖每日自动更新的源文件。默认使用 DuckDB；需要验证生产兼容性时启动 ClickHouse，并使用 MinIO 模拟 OSS。

## 6. 数据迁移与每日发布

### 6.1 数据分层

推荐 OSS 结构：

```text
oss://finquery-data-prod/
├── raw/source=stock-trading-data-pro/date=2026-09-18/
├── curated/table=stock_daily/year=2026/month=09/
├── manifests/runs/<run_id>.json
├── manifests/current.json
└── rejected/run_id=<run_id>/
```

- `raw/`：原始备份，可按预算选择性启用。
- `curated/`：清洗、类型转换后的 Parquet。
- `manifests/`：来源、行数、校验和和 Schema 版本。
- `rejected/`：无法解析的文件及错误原因。

### 6.2 第一阶段逻辑表

| 逻辑表 | 原始目录 | 数据粒度 |
|---|---|---|
| `stock_daily` | `stock-trading-data-pro` | 股票 × 交易日 |
| `index_daily` | `stock-main-index-data` | 指数 × 交易日 |
| `etf_daily` | `stock-etf-trading-data` | ETF × 交易日 |
| `fx_daily` | `stock-cny-rate` | 货币对 × 交易日 |
| `money_flow_daily` | `stock-money-flow-xbx` | 股票 × 交易日 |
| `analyst_ratings` | `stock-analyst-ranking` | 股票 × 评级记录 |
| `company_notices` | `stock-notices-title` | 股票 × 公告 |
| `company_activities` | `stock-activation-records` | 股票 × 活动记录 |
| `stock_concepts` | `stock-popular-concept-detail` | 股票 × 概念 × 日期 |

后续再接入 5/15 分钟行情、超宽财务数据、`real_trading` 和加密货币 PKL。`real_trading` 建议作为独立 `trading_ops` 数据库，因为它包含实盘和回测业务数据。

### 6.3 转换规则

数据发布器需要：

- 自动识别 UTF-8 与 GB18030。
- 对存在说明文字的文件跳过首行，从第二行读取表头。
- 将中文、`@`、冒号等转换为安全 `snake_case` 字段名。
- 在 Schema 中保留原中文名称作为 label 和 aliases。
- 从文件名补充 `stock_code`、`trade_date` 或数据来源。
- 统一日期、数字、布尔、空值和百分比格式。
- 按自然主键去重。
- 记录无法解析的文件，不静默丢弃。
- 分区写入 Parquet，避免单个超大文件。

### 6.4 每日发布流程

```text
1. Discover  找出新增或修改的源文件
2. Stage     生成本次 run_id 临时区
3. Normalize 解码、跳过说明行、重命名和类型转换
4. Validate  检查行数、主键、日期、空值率和重复率
5. Write     生成按日期或月份分区的 Parquet
6. Upload    上传到 OSS _staging/<run_id>/
7. Load      写入 ClickHouse staging 表或更新 DuckDB 缓存
8. Compare   对比股票数、行数、最大交易日和关键指标
9. Publish   原子切换 current manifest 或目标分区
10. Notify   发送成功或失败通知
```

只有所有校验成功后才能修改 `current.json`，线上永远读取完整数据版本。

### 6.5 增量与幂等

每个源文件记录：

```text
path
size
mtime
sha256
source_date
ingestion_run_id
status
```

重复执行同一日期的发布任务不得生成重复业务记录。ClickHouse 表可评估：

```sql
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(trade_date)
ORDER BY (stock_code, trade_date)
```

最终表引擎需根据源数据是否修订、去重延迟和查询模式确定。

### 6.6 本地调度

近期使用 Windows Task Scheduler，在上游数据完成后执行：

```powershell
docker compose run --rm data-publisher publish --date 2026-09-18
```

本地数据机只向 OSS 发起出站 HTTPS 连接，不开放公网入站端口。不建议在该机器上部署通用 GitHub self-hosted runner。

## 7. FinQuery 应用改造

### 7.1 分离分析引擎

定义统一接口并分别实现 `DuckDbAnalyticsEngine` 和 `ClickHouseAnalyticsEngine`：

```python
class AnalyticsEngine:
    def execute(self, database, sql, access_scope): ...
    def validate_sql(self, database, sql, access_scope): ...
```

两种实现都必须保留单条只读查询、禁止 `SELECT *`、已知表校验、表级权限、超时、最大扫描量和最大返回行数。

### 7.2 状态迁移至 PostgreSQL

建议表：

```text
users
sessions
query_tasks
conversation_messages
clarifications
saved_memories
saved_fields
schema_versions
ingestion_runs
audit_events
```

使用 Alembic 管理迁移。生产环境不再依赖进程内 token、任务字典或 `saved_memories.json` 作为事实来源。

### 7.3 异步查询

建议接口：

```text
POST /api/query       → 创建任务并返回 task_id
GET /api/tasks/{id}   → 查询任务状态和结果
POST /clarify         → 恢复需要澄清的任务
```

API 将任务放入 Redis，Worker 执行路由、Schema 检索、LLM、SQL 和结果生成。这样可以避免长时间 HTTP 连接，并分别扩容 API 和 Worker。

### 7.4 认证与权限

生产必须移除 Mock 账号：

- 小团队：PostgreSQL 用户表 + Argon2 + JWT/refresh token。
- 企业内部：公司 OIDC、阿里云 IDaaS、钉钉或企业微信。
- 公网产品：正式注册、验证、密码重置、MFA 和风控。

建议角色为 `admin`、`market_analyst`、`quant_research` 和 `trading_ops`。实盘及回测数据只向 `trading_ops` 和管理员开放。

## 8. 云上部署

### 8.1 第一阶段：低成本生产版

建议资源：

- ECS：4 vCPU、8–16 GiB 内存。
- 独立数据盘：100–200 GiB。
- OSS：raw、curated、manifests。
- RDS PostgreSQL。
- ACR 镜像仓库。
- 域名、HTTPS 证书、SLS 日志。
- 根据入口需求配置 ALB。

ECS 运行 API、Worker、Redis、Nginx 和 DuckDB/Parquet cache。Vue 的 `dist` 发布到 OSS/CDN。

### 8.2 第二阶段：可扩展生产版

当出现持续并发、DuckDB 资源争抢、数据达到数百 GiB、API 需要多副本或更高可用要求时：

- DuckDB → ApsaraDB ClickHouse。
- Redis 容器 → 托管 Redis。
- ECS Compose → ACK。
- Nginx → ALB Ingress。
- API 和 Worker 分别扩容。
- RDS 切换多可用区高可用版本。

Kubernetes 不作为第一阶段前置条件。

## 9. 应用 CI/CD

### 9.1 Pull Request

```text
Backend
- 安装锁定依赖
- unittest
- 数据库迁移检查
- 小型行情 fixture 测试
- SQL 安全和权限测试

Frontend
- npm ci
- vue-tsc
- npm run build

Container
- 构建 Backend/Worker 镜像
- 漏洞扫描和 SBOM
- 检查镜像不包含 .env、原始数据或密钥

Infrastructure
- terraform fmt
- terraform validate
- terraform plan
```

### 9.2 main 分支

```text
1. 构建一次镜像
2. 使用 git SHA 和构建号打标签
3. 推送 ACR
4. 自动部署 Staging
5. 执行 PostgreSQL migration
6. 执行 readiness/health 检查
7. 执行固定 smoke queries
8. 保存部署和测试报告
```

部署记录使用镜像 digest，不依赖可覆盖的 `latest`。

### 9.3 Production

Git tag（如 `v1.2.0`）触发：

```text
人工审批
→ 使用 Staging 验证过的同一镜像 digest
→ 执行向前兼容数据库迁移
→ 滚动或蓝绿部署
→ readiness 检查
→ 业务 smoke test
→ 切换流量
→ 观察 15–30 分钟
```

失败时回滚到前一个镜像 digest，不重新构建所谓的回滚镜像。

### 9.4 数据库迁移

采用 expand/contract：

1. 新增 nullable 字段、新表或兼容索引。
2. 发布兼容新旧结构的应用。
3. 执行数据回填。
4. 切换读取路径。
5. 稳定后删除旧字段。

破坏性迁移必须有独立审批、备份和回滚步骤。

## 10. 基础设施即代码

```text
infra/
├── modules/
│   ├── network/
│   ├── ecs/
│   ├── oss/
│   ├── rds/
│   ├── acr/
│   ├── clickhouse/
│   └── observability/
└── environments/
    ├── dev/
    ├── staging/
    └── prod/
```

Terraform 管理 VPC、vSwitch、NAT、安全组、ECS/ACK、OSS、RDS、ACR、ALB、DNS、RAM Role 和日志资源。

```text
PR → terraform plan → 审核
main → staging apply
production → 人工批准后 apply
```

Terraform state 使用远端加密存储并启用锁，各环境不共享 state。

## 11. 版本兼容

每次结果应记录：

```text
app_version: 1.4.0
schema_version: 3
dataset_version: 2026-09-18T083000+08:00
```

数据 Schema 同样使用 expand/contract：先发布兼容应用，再发布数据并切换 `current` manifest，最后清理旧字段或分区。应用部署和每日数据任务不得同时执行破坏性结构修改。

## 12. 安全方案

- OSS、RDS、ClickHouse、Redis 只通过 VPC 访问。
- 仅 ALB 或指定入口暴露公网 443。
- 数据库安全组禁止公网直接访问。
- ECS/ACK 使用 RAM Role 和临时 STS 凭据。
- LLM key、数据库密码和 JWT key 存入 KMS Secrets Manager。
- ClickHouse 为 FinQuery 创建只读账号。
- 保留 SQL AST 校验和表级权限控制。
- 增加 API 限流、用户配额、查询超时和最大扫描量。
- 日志不记录 token、密码、完整密钥或敏感查询内容。
- 确认行情授权允许云存储、团队共享和商业展示。

若服务位于中国大陆并通过域名向公网提供，应在发布前处理 ICP 备案；涉及受监管金融服务时另行确认许可要求。

## 13. 监控、告警与灾备

数据监控：

- 最新交易日、每日新增行数和股票数。
- 拒绝文件数、重复率和空值率。
- 数据发布耗时和 manifest 年龄。
- ClickHouse 导入及查询失败率。

应用监控：

- API 5xx、P95/P99 延迟和任务排队时间。
- LLM、Embedding、Rerank 失败率、延迟和费用。
- Schema 检索空结果率。
- PostgreSQL 连接、CPU、磁盘和复制状态。
- Redis 内存、队列长度和淘汰数量。

初始目标：

```text
数据 RPO：24 小时
应用 RPO：15 分钟以内
应用 RTO：1 小时
数据更新成功率：99%
API 可用性：99.5%
```

备份措施：

- OSS 开启版本控制和生命周期。
- 保留最近 30 个数据 manifest。
- RDS 开启自动备份和时间点恢复。
- ClickHouse 保留上一版本分区或快照。
- 每季度执行一次实际恢复演练。

## 14. 分阶段实施清单

### 阶段 1：本地容器化

- [ ] Backend、Frontend、Worker Dockerfile。
- [ ] Compose lite/full profile。
- [ ] PostgreSQL 状态存储。
- [ ] Redis 异步任务框架。
- [ ] 小型确定性行情 fixture。
- [ ] DuckDB 和 ClickHouse 两种模式。

### 阶段 2：标准化数据层

- [ ] `data-publisher` 工具。
- [ ] 编码和首行识别。
- [ ] 字段映射及 `_schema.json`。
- [ ] Parquet 分区。
- [ ] manifest 和 rejected 输出。
- [ ] 幂等、增量和数据质量测试。

### 阶段 3：数据上云

- [ ] 创建 Staging/Production OSS。
- [ ] 第一次全量上传。
- [ ] Windows 每日增量任务。
- [ ] 发布原子性和失败告警。
- [ ] 数据版本回滚演练。

### 阶段 4：第一版生产环境

- [ ] Terraform 创建 VPC、ECS、RDS、ACR、OSS 和日志资源。
- [ ] ECS Docker Compose 部署。
- [ ] Vue 发布 OSS/CDN。
- [ ] 域名、HTTPS 和访问控制。
- [ ] Staging smoke test。
- [ ] Production 切换和回滚演练。

### 阶段 5：CI/CD

- [ ] PR 测试和安全扫描。
- [ ] main 自动发布 Staging。
- [ ] tag + 人工审批发布 Production。
- [ ] 镜像 digest 固定和自动回滚。
- [ ] Terraform plan/apply 审批流程。

### 阶段 6：规模化

- [ ] 分析查询迁移至 ClickHouse。
- [ ] 使用托管 Redis。
- [ ] API/Worker 多副本。
- [ ] ECS Compose 迁移 ACK。
- [ ] ALB 蓝绿或金丝雀发布。

## 15. 验收标准

### 数据迁移

- [ ] 原始 `D:\trade_data` 不被修改。
- [ ] 每次发布均有唯一 `run_id` 和 manifest。
- [ ] 重复执行不会产生重复业务记录。
- [ ] 发布失败不会改变线上 `current` 数据版本。
- [ ] 可回滚至上一数据版本。
- [ ] 质量异常阻止发布并触发告警。

### 应用

- [ ] API/Worker 重启不丢任务及澄清状态。
- [ ] 用户、权限、记忆和会话持久化到 PostgreSQL。
- [ ] DuckDB 与 ClickHouse 使用相同只读安全接口。
- [ ] Production 不包含 Mock 密码和硬编码密钥。
- [ ] 所有数据库仅通过私网访问。

### CI/CD

- [ ] PR 不通过测试不能合并。
- [ ] Staging 自动部署并执行 smoke test。
- [ ] Production 需要人工审批。
- [ ] Production 使用 Staging 验证过的镜像 digest。
- [ ] 可在不重新构建镜像的情况下回滚。
- [ ] 基础设施变更有 Terraform plan 和审核记录。

## 16. 待评审决策

1. 第一阶段必须接入哪些数据目录，是否以 `stock_daily` 为最高优先级。
2. 原始数据是否全部备份到 OSS，还是只上传标准化 Parquet。
3. 第一版预计在线用户数和查询并发量。
4. 是否部署在中国大陆，以及是否具备域名和 ICP 条件。
5. 数据授权是否允许云存储、团队共享或公网产品使用。
6. 登录面向内部员工还是外部用户。
7. 可接受的数据更新时间窗口，例如每日 08:00 前完成。
8. 初始云预算，以及是否直接购买 ClickHouse。
9. 使用 GitHub、GitLab 还是阿里云 Codeup。
10. 故障通知使用钉钉、企业微信、邮件还是 PagerDuty。

## 17. 推荐第一期范围

```text
Docker Compose
+ OSS
+ RDS PostgreSQL
+ DuckDB/Parquet
+ ECS
+ GitHub Actions
+ ACR
+ Terraform
```

第一期先接入 `stock_daily`、`index_daily`、`etf_daily`、`fx_daily` 和 `money_flow_daily`。完成数据质量、发布回滚和权限验证后，再增加 ClickHouse、ACK、高频行情和财务宽表。

## 18. 参考资料

- [Alibaba Cloud OSS Data Lake](https://www.alibabacloud.com/help/en/oss/user-guide/data-lake)
- [OSS Static Website Hosting](https://www.alibabacloud.com/help/en/oss/user-guide/hosting-static-websites)
- [ApsaraDB for ClickHouse](https://www.alibabacloud.com/help/en/clickhouse/product-overview/what-is-apsaradb-for-clickhouse)
- [ApsaraDB RDS 高可用与灾备](https://www.alibabacloud.com/help/en/rds/product-overview/high-availability-and-disaster-recovery)
- [Alibaba Cloud Container Registry](https://www.alibabacloud.com/help/en/acr/product-overview/what-is-container-registry)
- [Alibaba Cloud Terraform](https://www.alibabacloud.com/help/en/terraform/what-is-terraform)
- [KMS Secrets Manager](https://www.alibabacloud.com/help/en/kms/key-management-service/user-guide/secret-management-overview)
- [OSS RAM 权限最佳实践](https://www.alibabacloud.com/help/en/oss/user-guide/ram-policy/)
- [SLS Docker 日志采集](https://www.alibabacloud.com/help/en/sls/collect-docker-container-text-logs)
- [ICP 备案与 DNS](https://www.alibabacloud.com/help/en/dns/icp-and-dns)


是的，第一步是 Docker。但当前机器还没有安装 Docker，WSL 似乎也未启用。

  ## 现在先做这件事

  ### 1. 安装 WSL 2

  使用管理员 PowerShell：

  wsl --install

  完成后重启 Windows，再检查：

  wsl --status
  wsl --version

  ### 2. 安装 Docker Desktop

  安装 Docker Desktop for Windows，配置时选择：

  - 使用 WSL 2 backend
  - 启用 WSL integration
  - 使用 Linux containers

  Docker Desktop 已包含 Docker Engine 和 Docker Compose，不需要单独安装 Compose。Docker 官方说明

  ### 3. 验证安装

  重启终端后运行：

  docker version
  docker compose version
  docker run --rm hello-world

  然后验证容器能只读访问行情目录：

  docker run --rm `
    --mount 'type=bind,source=D:\trade_data,target=/data,readonly' `
    alpine ls -la /data

  ## Docker 安装后的第一个开发任务

  暂时不要迁移 OSS、ClickHouse 或 PostgreSQL。先完成一个不改变业务功能的容器化基线：

  D:\FinQuery\
  ├── backend\Dockerfile
  ├── frontend\Dockerfile
  ├── compose.yaml
  ├── .dockerignore
  └── .env.docker.example

  第一版 Compose 只包含：

  frontend
  backend

  并把 D:\trade_data 只读挂载给后端。先验证：

  - docker compose up --build 能启动。
  - 前端可以访问。
  - FastAPI /api/health 正常。
  - 登录和原有短视频数据查询正常。
  - 容器能够看到 D:\trade_data。
  - 镜像中没有 .env、API Key 和原始行情数据。
  - 停止并重建容器后功能仍正常。

  达成这个基线后，再按顺序加入：

  1. 交易数据转换器与 Parquet。
  2. PostgreSQL。
  3. Redis 和异步 Worker。
  4. OSS 数据发布。
  5. 云上 ECS。
  6. GitHub Actions CI/CD。
  7. 最后根据并发决定是否上 ClickHouse。

  所以你现在的下一步是：安装 WSL 2 和 Docker Desktop。完成后，我可以直接为这个仓库创建 Dockerfile、Compose 配置及健康检查。
