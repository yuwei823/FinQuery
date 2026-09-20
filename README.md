# FinQuery Studio 金融数据版

面向金融市场数据的中文自然语言问数应用，包含 Vue 3 前端、FastAPI + LangGraph
后端、股票与主要指数日行情、字段级 Schema 检索、只读 DuckDB SQL、已有结果分析以及
增量 Parquet 数据管道。默认数据库为 `trade_data`，一次问题目前不支持跨数据库联表。

## 环境要求

- Python 3.11
- Node.js 20.19 或更高版本
- 大模型、Embedding 和 Rerank 服务；默认配置使用阿里云百炼
- Docker Desktop（仅 Docker Compose 开发、数据转换或公网预览需要）

## 安装

以下命令均从项目根目录执行。

后端（Windows PowerShell）：

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

后端（macOS / Linux）：

```bash
cd backend
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

编辑 `backend/.env`，填写 `LLM_API_KEY`。默认模型配置为 `qwen3.7-plus`、`text-embedding-v4` 和 `qwen3-rerank`。
不要提交 `backend/.env`、API 密钥或访问令牌。

前端：

```powershell
Set-Location frontend
npm ci
```

`DATABASE_SWITCHES` 是逗号分隔、自动去重的数据库 key 集合，默认值为
`trade_data`。每个可选数据库需要在 `backend/app/database_sources/` 注册自己的
Schema 目录和 `SYNONYMS`；切换后端配置后需重启服务。

## 注册新的数据库

下面以数据库 key `fund_data` 为例。数据库 key 只能包含英文字母、数字和下划线，
并且必须以英文字母或下划线开头。

### 1. 添加 Schema 和查询数据

新建目录：

```text
backend/data/databases/fund_data/
├── _schema.json
└── funds.parquet
```

DuckDB 支持在查询目录中注册 `*.csv`、`*.parquet` 或包含 Parquet 分片的同名子目录。
文件或子目录名就是物理表名，必须是安全的 SQL 标识符，并与 `_schema.json`
中表的 `name` 一致；数据列名必须与 Schema 的字段名一致。若数据位于外部整理目录，在第 3 步
注册 `DatabaseSource.data_folder`，不要把大型数据文件提交到 Git。

`_schema.json` 至少需要包含：

```json
{
  "database": "fund_data",
  "tables": [
    {
      "id": "fund_data.funds",
      "name": "funds",
      "database": "fund_data",
      "label": "基金",
      "description": "基金基本信息",
      "fields": [
        {
          "name": "fund_code",
          "label": "基金代码",
          "type": "文本",
          "description": "基金唯一代码",
          "aliases": ["基金代码"]
        }
      ]
    }
  ],
  "relations": [],
  "role_tables": {
    "market_analyst": ["funds"]
  }
}
```

需要遵守以下约束：

- 顶层 `database` 必须等于数据库 key。
- 表 `id` 使用 `<database>.<table>` 格式，并且在所有启用数据库中唯一。
- 表 `name` 与对应 CSV/Parquet 文件或分片子目录名一致，不包含扩展名。
- `relations` 中的表 ID 和字段名必须使用实际 Schema 定义。
- `role_tables` 使用物理表名；未分配给业务角色的表默认只对管理员可见。
- `data_profile` 和 `index_content` 可以预生成。表设置 `profile_mode: "schema_only"` 时，
  Schema 索引不会扫描数据表；否则缺少预生信息的字段会从 CSV/Parquet 动态构建样例和分布。

### 2. 添加该数据库的 SYNONYMS

新建 `backend/app/database_sources/fund_data.py`：

```python
from __future__ import annotations


DATABASE_ID = "fund_data"

SYNONYMS: dict[str, list[str]] = {
    "fund_data.funds.fund_code": ["基金代码", "产品代码"],
}
```

SYNONYMS 的键必须是完整字段 ID：

```text
<database>.<table>.<field>
```

启动时会验证每个键是否对应真实字段。没有额外同义词时仍需提供空字典：

```python
SYNONYMS: dict[str, list[str]] = {}
```

### 3. 注册数据源

修改 `backend/app/database_sources/__init__.py`，导入新模块：

```python
from .fund_data import DATABASE_ID as FUND_DATA_ID
from .fund_data import SYNONYMS as FUND_DATA_SYNONYMS
```

然后在 `source_registry()` 返回值中添加：

```python
FUND_DATA_ID: DatabaseSource(
    database_id=FUND_DATA_ID,
    folder=database_root / FUND_DATA_ID,
    synonyms=FUND_DATA_SYNONYMS,
    data_folder=(
        curated_data_root / FUND_DATA_ID
        if curated_data_root is not None
        else database_root / FUND_DATA_ID
    ),
),
```

如果新数据库总是把数据与 `_schema.json` 放在同一目录，可以省略 `data_folder`。

只有放入该注册表的 key 才能写入 `DATABASE_SWITCHES`；未知 key 会让后端在启动时
明确报错。

### 4. 启用数据库

修改 `backend/.env`：

```env
DATABASE_SWITCHES=fund_data
```

同时启用多个数据库时使用逗号分隔：

```env
DATABASE_SWITCHES=trade_data,fund_data
```

修改后重启后端。Schema 索引会按已启用数据库集合生成独立缓存，例如：

```text
backend/data/schema_store.fund_data.json
backend/data/schema_store.fund_data-trade_data.json
```

这些缓存是自动生成物，已被 Git 忽略。首次查询会在签名不匹配或缓存不存在时重建；
管理员也可以调用 `POST /api/schema/index/rebuild` 强制重建。

### 5. 配置权限和测试账号（按需）

如果新数据库继续使用现有的 `market_analyst` 角色，只需在
新 Schema 的 `role_tables` 中列出对应表，无需修改权限代码。

如果需要新增角色或登录账号，还要同步修改：

- `backend/app/security/auth.py`：在 `AuthService.__init__` 的账号定义中添加用户。
- `backend/app/security/access_control.py`：同步更新 `USER_ROLES` 和 `ROLE_POLICIES`。

管理员角色会自动获得所有已启用数据库及其全部 Schema 表的访问权限。

### 6. 添加前端示例问题（推荐）

修改 `frontend/src/App.vue` 中的 `promptsByDatabase`：

```ts
const promptsByDatabase: Record<string, string[]> = {
  fund_data: [
    "查询最近一个月基金净值走势",
    "按基金类型统计产品数量",
  ],
}
```

前端根据 `/api/schema` 返回的数据库标识展示相应问题。数据库没有配置示例时，加载
Schema 后不会错误展示其他数据库的问题。

### 7. 补充验证（推荐）

- 为新数据库增加数据完整性验证脚本，并覆盖主键、日期范围、重复记录和空值检查。
- 在 `backend/tests/test_database_switches.py` 中增加注册、切换和 SYNONYMS 校验用例。
- 运行后端测试和前端构建：

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
cd ..\frontend
npm run build
```

数据库注册完成后，`backend/app/database.py`、Schema 检索、DuckDB 执行、MCP 工具注册
和索引缓存都会根据 `DATABASE_SWITCHES` 自动切换，通常不需要再逐一修改这些模块。
当前工作流可以同时加载多个数据库，但一次问题如果需要跨数据库联合分析，仍会进入
尚未实现的多数据库 Handoff 路径。

## 启动

### 使用 Docker Compose（本地开发）

复制后端环境变量文件并填写 `LLM_API_KEY`：

```powershell
Copy-Item backend/.env.example backend/.env
Copy-Item .env.docker.example .env.docker
docker compose --env-file .env.docker up --build
```

Compose 默认把 Windows 的 `D:\trade_data` 只读挂载到后端容器的
`/data/raw`，把标准化数据目录 `D:\trade_data_curated` 只读挂载到 `/data/curated`。
如果本机目录不同，只需修改
忽略提交的 `.env.docker`：

```env
TRADE_DATA_HOST_PATH=D:/trade_data
TRADE_DATA_CURATED_HOST_PATH=D:/trade_data_curated
```

启动后访问 `http://127.0.0.1:5173`，并用 `http://127.0.0.1:8000/api/health` 检查后端。
响应中的 `trade_data.available=true` 和 `curated_data.available=true` 表示后端能够看到两个挂载目录。

### 准备行情数据

首次接入股票日行情时，先扫描全部原始文件的表头：

```powershell
docker compose --env-file .env.docker --profile tools run --rm stock-daily-data-prep `
  python scripts/stock_daily_pipeline.py inventory `
  --source /data/raw/stock-trading-data-pro `
  --output /data/curated/trade_data/_inventory.json
```

确认 `invalid_header_count` 为 `0` 后运行增量转换：

```powershell
docker compose --env-file .env.docker --profile tools run --rm stock-daily-data-prep
```

转换器跳过数据提供方说明行，将 GB18030 CSV 标准化为 UTF-8 字段和分片 Parquet，
输出到 `D:\trade_data_curated\trade_data\stock_daily`。它根据源文件大小和修改时间跳过
未变化文件，可安全地在每日数据更新后重复执行。原始目录始终只读。

把按股票生成的分片压实成查询文件，避免每次查询打开数千个小文件：

```powershell
docker compose --env-file .env.docker --profile tools run --rm stock-daily-data-prep `
  python scripts/stock_daily_pipeline.py compact `
  --output /data/curated/trade_data
```

转换后运行全量完整性检查：

```powershell
docker compose --env-file .env.docker --profile tools run --rm stock-daily-data-prep `
  python scripts/stock_daily_pipeline.py validate `
  --output /data/curated/trade_data
```

只有命令返回成功且 `errors` 为空时，才应发布新数据版本或重启生产服务。

主要指数数据使用相同的增量构建流程，但采用独立的字段契约和 manifest。执行：

```powershell
docker compose --env-file .env.docker --profile tools run --rm index-daily-data-prep `
  python scripts/index_daily_pipeline.py inventory `
  --source /data/raw/stock-main-index-data `
  --output /data/curated/trade_data/_inventory.index_daily.json

docker compose --env-file .env.docker --profile tools run --rm index-daily-data-prep

docker compose --env-file .env.docker --profile tools run --rm index-daily-data-prep `
  python scripts/index_daily_pipeline.py validate `
  --output /data/curated/trade_data

docker compose --env-file .env.docker --profile tools run --rm index-daily-data-prep `
  python scripts/index_daily_pipeline.py compact `
  --output /data/curated/trade_data
```

产物为分片目录 `trade_data/index_daily/`、压实查询文件
`trade_data/index_daily.parquet` 和独立增量清单
`trade_data/_pipeline_manifest.index_daily.json`。原始 CSV 首行就是英文表头，因此该配置不会跳过说明行。

邢不行财务数据产品名为 `stock-fin-data-xbx-daily`，其完整数据实际落在
`TRADE_DATA_ROOT/stock-fin-data-xbx`。源文件按股票代码分目录，记录粒度为财报披露，
并非日频行情。运行增量构建：

```powershell
docker compose --env-file .env.docker --profile tools run --rm financial-statement-data-prep

docker compose --env-file .env.docker --profile tools run --rm financial-statement-data-prep `
  python scripts/financial_statement_pipeline.py validate `
  --output /data/curated/trade_data

docker compose --env-file .env.docker --profile tools run --rm financial-statement-data-prep `
  python scripts/financial_statement_pipeline.py compact `
  --output /data/curated/trade_data
```

输出表为 `financial_statement`，主键是股票代码、报告期和披露日期。查询财务数据时应以
`publish_date` 判断当时是否已经披露，避免使用未来才发布的财报。该任务已经注册到每日
自动更新配置，无需单独修改计划任务。

ETF 日线原始目录为 `TRADE_DATA_ROOT/stock-etf-trading-data`，在现有 `trade_data`
数据库中注册为表 `stock_etf_trading_data`。运行：

```powershell
Set-Location backend
.\.venv\Scripts\python.exe scripts\etf_daily_pipeline.py inventory
.\.venv\Scripts\python.exe scripts\etf_daily_pipeline.py convert
.\.venv\Scripts\python.exe scripts\etf_daily_pipeline.py validate
.\.venv\Scripts\python.exe scripts\etf_daily_pipeline.py compact
```

也可以使用 `docker compose --env-file .env.docker --profile tools run --rm etf-daily-data-prep`。
产物为 `trade_data/stock_etf_trading_data/`、压实文件
`trade_data/stock_etf_trading_data.parquet` 和独立增量清单。该任务已加入每日更新配置。

### 每日自动更新行情数据

仓库提供统一更新入口，按数据源依次执行 `convert`、`validate`、`compact`。某个数据源失败时不会执行它的压实发布步骤，但会继续处理其他数据源；只要有一个任务失败，脚本就以非零状态结束：

```powershell
Set-Location D:\FinQuery\backend
.\.venv\Scripts\python.exe -m scripts.update_curated_data
```

脚本依次读取当前进程环境变量、`backend/.env` 和默认路径来确定 `TRADE_DATA_ROOT` 与 `CURATED_DATA_ROOT`。运行日志写入 `backend/logs/curated-data-update.log`，每天轮转并保留 30 份；转换器输出、验证错误、Python 异常和退出码都会进入日志。

在 Windows 上以管理员身份打开 PowerShell，然后安装每天凌晨 3 时运行的计划任务。管理员权限用于注册在用户注销后仍能运行的 S4U 任务：

```powershell
Set-Location D:\FinQuery
powershell -ExecutionPolicy Bypass -File backend\scripts\install_data_update_task.ps1
```

安装后可在“任务计划程序”中找到 `FinQuery Daily Data Update`。任务使用当前用户的 S4U 身份运行，不要求用户保持登录；电脑在 03:00 睡眠或关机时，会在下次可运行时补跑。S4U 任务适合这里使用的本机磁盘路径，但不能访问需要用户凭据的网络共享。可以先手动验证计划任务：

```powershell
Start-ScheduledTask -TaskName "FinQuery Daily Data Update"
Get-ScheduledTaskInfo -TaskName "FinQuery Daily Data Update"
Get-Content backend\logs\curated-data-update.log -Tail 100
```

增加新的数据源时，实现与现有脚本一致的 `convert`、`validate`、`compact` 命令接口，然后在 `backend/scripts/data_update_jobs.json` 的 `jobs` 数组中增加任务。`source_subdir` 相对于 `TRADE_DATA_ROOT`，`database` 是 `CURATED_DATA_ROOT` 下的目标数据库目录。计划任务和日志逻辑不需要修改。

转换完成后把 `backend/.env` 改为以下配置并重启后端：

```env
DATABASE_SWITCHES=trade_data
TRADE_DATA_ROOT=D:/trade_data
CURATED_DATA_ROOT=D:/trade_data_curated
```

如需同时启用其他金融数据库，使用逗号分隔，例如
`DATABASE_SWITCHES=trade_data,fund_data`；一次查询仍不能跨两个数据库联表。

### 不使用 Docker 启动

确认 `backend/.env` 中的 `TRADE_DATA_ROOT` 和 `CURATED_DATA_ROOT` 指向本机目录，然后分别打开两个终端。

后端（Windows）：

```powershell
cd backend
.\.venv\Scripts\python.exe run.py
```

后端（macOS / Linux）：

```bash
cd backend
./.venv/bin/python run.py
```

前端：

```powershell
cd frontend
npm run dev
```

访问 `http://127.0.0.1:5173`，API 文档位于 `http://127.0.0.1:8000/docs`。

### 本地开发更新

使用 Git 更新代码前，先检查本地改动，避免覆盖未提交的工作：

```powershell
Set-Location D:\FinQuery
git status --short
```

如果 `git status` 显示有本地改动，先提交或自行暂存后再拉取；不要为了更新代码而删除
`backend/.env`、`.env.docker`、本地数据目录或其他忽略提交的配置。
确认工作区可以安全更新后再执行：

```powershell
git pull --ff-only
```

不使用 Docker 时，普通源码变更只需重启后端；Vite 开发服务会自动热更新前端源码。
如果后端依赖或前端依赖发生变化，分别同步安装：

```powershell
Set-Location D:\FinQuery
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

Set-Location frontend
npm ci
```

如果 `backend/.env.example` 发生变化，手动将新增或修改的配置项合并到已忽略的
`backend/.env`，不要直接覆盖已填写的密钥和本地路径。然后按上一节的命令重启前后端。

使用 Docker Compose 本地开发时，`backend/` 和 `frontend/` 都会挂载到容器中：

- Python 或 Vue 源码变更通常会自动重载，不需要重建镜像。
- `backend/requirements.txt` 或后端 `Dockerfile` 变更时，重建并重建后端容器。
- `frontend/package.json` 或 `package-lock.json` 变更时，需要同步
  `frontend_node_modules` 命名卷中的依赖。
- `backend/.env` 或 `.env.docker` 变更时，需要重新创建后端容器，仅执行
  `restart` 不会重新读取 Compose 环境变量。

后端依赖或镜像配置变更：

```powershell
Set-Location D:\FinQuery
docker compose --env-file .env.docker build --pull=false backend
docker compose --env-file .env.docker up -d `
  --no-build --no-deps --force-recreate backend
```

前端依赖变更：

```powershell
Set-Location D:\FinQuery
docker compose --env-file .env.docker run --rm --no-deps frontend npm ci
docker compose --env-file .env.docker restart frontend
```

后端环境变量变更：

```powershell
Set-Location D:\FinQuery
docker compose --env-file .env.docker up -d `
  --no-deps --force-recreate backend
```

更新完成后检查容器和后端健康状态，并访问前端完成一次登录和查询：

```powershell
docker compose --env-file .env.docker ps
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

如果更新同时修改了前后端契约或共享流程，还应运行后端测试和前端生产构建：

```powershell
Set-Location D:\FinQuery\backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

Set-Location ..\frontend
npm run build
```

### 本机公网预览（Cloudflare Tunnel）

公网预览使用独立的生产后端、Nginx 静态前端和 Cloudflare Tunnel，不暴露开发服务器、
FastAPI 端口或本地数据目录。该模式适合受控预览和内部使用，不是完整的生产身份认证方案。
开始前应已完成以下准备：

- `backend/.env` 已填写模型密钥和启用的数据库。
- 原始数据与整理后数据目录已就绪，并通过完整性验证。
- Docker Desktop 已启动，域名已接入 Cloudflare。

复制公网配置：

```powershell
Copy-Item .env.public.example .env.public
```

编辑忽略提交的 `.env.public`：

- 为 `FINQUERY_ADMIN_PASSWORD` 和 `FINQUERY_MARKET_PASSWORD` 设置不同的随机密码，长度至少 16 位。
- 设置 `ENABLE_GUEST=true` 时，登录页显示“游客体验”；游客复用只读行情权限，每个来源身份
  每个 Asia/Shanghai 自然日最多提交 5 个新问题。设置为 `false` 可立即关闭游客入口。
- 将文档中的 `finquery.dev` 替换为实际域名。
- 如果只允许指定用户，先在 Cloudflare Zero Trust 创建 Access Self-hosted Application；
  若要对公众开放游客入口，Access 策略也必须允许相应访问。
- 再创建 remotely-managed Tunnel（建议命名 `finquery-home`），把 token 填入 `CLOUDFLARE_TUNNEL_TOKEN`。
- 在 Tunnel 中添加 Published application：Hostname 为 `finquery.dev`，Service 为 `http://public-gateway:80`。

Cloudflare 官方建议先建立 Access 应用，再发布 Tunnel route，避免域名在没有访问控制的时间窗内
直接暴露。不要把 Tunnel token 提交到 Git；持有该 token 的机器可以运行这个 Tunnel。

先不启动 Tunnel，只验证本机生产链路：

```powershell
docker compose --env-file .env.public --profile public-preview up -d --build `
  backend-public public-gateway

Invoke-RestMethod http://127.0.0.1:8080/api/health
```

确认健康后启动隧道：

```powershell
docker compose --env-file .env.public --profile public-preview up -d cloudflared
docker compose --env-file .env.public --profile public-preview ps
docker compose --env-file .env.public --profile public-preview logs cloudflared
```

#### 手动部署代码更新

以下命令均在仓库根目录 `D:\FinQuery` 执行。`--pull=false` 优先使用本机缓存的基础镜像，
可以降低 Docker Hub 网络超时对部署的影响。代码部署不需要重新创建 Tunnel，也不需要更改
Cloudflare route。

仅前端发生变化：

```powershell
docker compose --env-file .env.public --profile public-preview build `
  --pull=false public-gateway

docker compose --env-file .env.public --profile public-preview up -d `
  --no-build --no-deps --force-recreate public-gateway
```

仅后端发生变化：

```powershell
docker compose --env-file .env.public --profile public-preview build `
  --pull=false backend-public

docker compose --env-file .env.public --profile public-preview up -d `
  --no-build --no-deps --force-recreate backend-public

# 让 Nginx 重新解析新 Backend 容器地址
docker compose --env-file .env.public --profile public-preview restart public-gateway
```

前后端均发生变化：

```powershell
docker compose --env-file .env.public --profile public-preview build `
  --pull=false backend-public public-gateway

docker compose --env-file .env.public --profile public-preview up -d `
  --no-build --force-recreate backend-public public-gateway
```

每次部署后检查服务和本机公网链路：

```powershell
docker compose --env-file .env.public --profile public-preview ps
Invoke-RestMethod http://127.0.0.1:8080/api/health
```

`cloudflared` 通常不需要重启；仅在修改 `CLOUDFLARE_TUNNEL_TOKEN` 或排查 Tunnel 连接时执行：

```powershell
docker compose --env-file .env.public --profile public-preview restart cloudflared
docker compose --env-file .env.public --profile public-preview logs --tail=100 cloudflared
```

#### Windows 重启后恢复服务

单纯重启 Windows 不需要重新构建镜像。`backend-public`、`public-gateway` 和 `cloudflared`
都使用 `restart: unless-stopped`；Docker Desktop 启动后，未被手动停止的容器通常会自动恢复。
建议在 Docker Desktop 中开启 **Start Docker Desktop when you sign in to your computer**。

登录 Windows 并等待 Docker Desktop 启动后，在仓库根目录检查状态：

```powershell
Set-Location D:\FinQuery
docker compose --env-file .env.public --profile public-preview ps
```

如果 `backend-public`、`public-gateway` 和 `cloudflared` 均为 `Up`，且前两个服务显示
`healthy`，无需执行部署命令。继续验证本机入口和 Tunnel：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/health
docker compose --env-file .env.public --profile public-preview logs `
  --tail=30 cloudflared
```

如果容器未自动启动，使用已有镜像恢复服务，不执行 build：

```powershell
docker compose --env-file .env.public --profile public-preview up -d `
  --no-build backend-public public-gateway cloudflared

docker compose --env-file .env.public --profile public-preview ps
```

只有代码、Dockerfile 或依赖文件发生变化，或者本地镜像已被删除时，才需要使用上一节的
`build` 部署命令。Windows 重启不会删除镜像、`.env.public`、绑定挂载的数据或 Docker
named volume。不要执行 `docker compose down -v`；`-v` 会删除包括游客查询额度记录在内的
`guest_runtime` 持久化卷。

当前只有游客额度数据挂载到 `guest_runtime` 命名卷。访问令牌和 LangGraph 任务默认保存在进程内存中；
`backend/data/saved_memories.json` 也没有在公网 Compose 配置中挂载。因此重启后需重新登录，重新创建
`backend-public` 容器还会丢失容器内新增的收藏。如需长期或多实例运行，应先将认证、任务和收藏迁移到共享持久化存储。

公网模式会关闭 `/docs`、`/redoc` 和 `/openapi.json`，并在 Nginx 对登录、查询及普通 API
分别限流。如果仍使用默认密码或密码不足 16 位，`backend-public` 会拒绝启动。停止预览：

```powershell
docker compose --env-file .env.public --profile public-preview down
```

## 验证

后端单元测试和数据完整性检查：

```powershell
Set-Location D:\FinQuery\backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe scripts\stock_daily_pipeline.py validate
.\.venv\Scripts\python.exe scripts\index_daily_pipeline.py validate
.\.venv\Scripts\python.exe scripts\etf_daily_pipeline.py validate
```

前端类型检查和生产构建：

```powershell
Set-Location ..\frontend
npm run build
```

数据验证命令默认读取 `CURATED_DATA_ROOT`，未在当前 shell 设置时使用
`D:/trade_data_curated`。也可以显式传入 `--output <curated-root>/trade_data`。

## 测试账号

- 管理员：`admin` / `admin123`
- 行情分析：`market` / `market123`

上述默认密码仅用于本地开发。公网模式必须通过 `.env.public` 提供两个不同的、至少 16 位的非默认密码。
