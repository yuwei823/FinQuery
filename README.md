# FinQuery Studio 金融数据版

面向金融市场数据的自然语言问数项目，包含 Vue 前端、FastAPI + LangGraph 后端、股票与指数日行情、字段级 Schema 检索、安全只读 SQL 和增量 Parquet 数据管道。

## 环境要求

- Python 3.11
- Node.js 20.19 或更高版本
- 兼容 OpenAI 接口的大模型、Embedding 和 Rerank 服务

## 安装

以下命令均从解压后的项目根目录执行。

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

`DATABASE_SWITCHES` 是逗号分隔、自动去重的数据库 key 集合，默认值为
`trade_data`。每个可选数据库需要在 `backend/app/database_sources/` 注册自己的
Schema 目录和 `SYNONYMS`；切换后端配置后需重启服务。

## 注册新的数据库

下面以数据库 key `fund_data` 为例。数据库 key 只能包含英文字母、数字和下划线，
并且必须以英文字母或下划线开头。

### 1. 添加数据库文件

新建目录：

```text
backend/data/databases/fund_data/
├── _schema.json
├── _database_manifest.json  # 推荐提供，但运行时不强制读取
├── funds.csv
└── fund_nav.csv
```

CSV 文件名就是 DuckDB 中的物理表名。文件名必须是安全的 SQL 标识符，并与
`_schema.json` 中表的 `name` 一致；CSV 表头必须与 Schema 的字段名一致。

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
    "market_analyst": ["funds", "fund_nav"]
  }
}
```

需要遵守以下约束：

- 顶层 `database` 必须等于数据库 key。
- 表 `id` 使用 `<database>.<table>` 格式，并且在所有启用数据库中唯一。
- 表 `name` 与对应 CSV 文件名一致，不包含 `.csv`。
- `relations` 中的表 ID 和字段名必须使用实际 Schema 定义。
- `role_tables` 使用物理表名；未分配给业务角色的表默认只对管理员可见。
- `data_profile` 和 `index_content` 可以预生成；缺少时后端会读取 CSV 动态构建。

### 2. 添加该数据库的 SYNONYMS

新建 `backend/app/database_sources/fund_data.py`：

```python
from __future__ import annotations


DATABASE_ID = "fund_data"

SYNONYMS: dict[str, list[str]] = {
    "fund_data.funds.fund_code": ["基金代码", "产品代码"],
    "fund_data.fund_nav.nav": ["单位净值", "基金净值"],
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
),
```

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

- `backend/app/security/auth.py`：在 `AuthService.ACCOUNTS` 中添加测试账号。
- `backend/app/security/access_control.py`：增加用户到角色的映射和对应角色策略。

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

### 7. 补充验证和评测（推荐）

- 为新数据库增加数据完整性验证脚本，并覆盖主键、日期范围、重复记录和空值检查。
- 在 `backend/tests/test_database_switches.py` 中增加注册、切换和 SYNONYMS 校验用例。
- 如果新数据库用于正式问数评测，在 `backend/evaluation/cases/` 增加对应数据集和
  gold fields、gold SQL。
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

前端：

```powershell
cd frontend
npm install
```

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

启动后访问 `http://127.0.0.1:8000/api/health`。响应中的
`trade_data.configured=true` 和 `trade_data.available=true` 表示后端能够看到挂载目录。
首次接入股票日行情时，先扫描全部原始文件的表头：

```powershell
docker compose --profile tools run --rm stock-daily-data-prep `
  python scripts/stock_daily_pipeline.py inventory `
  --source /data/raw/stock-trading-data-pro `
  --output /data/curated/trade_data/_inventory.json
```

确认 `invalid_header_count` 为 `0` 后运行增量转换：

```powershell
docker compose --profile tools run --rm stock-daily-data-prep
```

转换器跳过数据提供方说明行，将 GB18030 CSV 标准化为 UTF-8 字段和分片 Parquet，
输出到 `D:\trade_data_curated\trade_data\stock_daily`。它根据源文件大小和修改时间跳过
未变化文件，可安全地在每日数据更新后重复执行。原始目录始终只读。

把按股票生成的分片压实成查询文件，避免每次查询打开数千个小文件：

```powershell
docker compose --profile tools run --rm stock-daily-data-prep `
  python scripts/stock_daily_pipeline.py compact `
  --output /data/curated/trade_data
```

转换后运行全量完整性检查：

```powershell
docker compose --profile tools run --rm stock-daily-data-prep `
  python scripts/stock_daily_pipeline.py validate `
  --output /data/curated/trade_data
```

只有命令返回成功且 `errors` 为空时，才应发布新数据版本或重启生产服务。

主要指数数据使用相同的增量构建流程，但采用独立的字段契约和 manifest。执行：

```powershell
docker compose --profile tools run --rm index-daily-data-prep `
  python scripts/index_daily_pipeline.py inventory `
  --source /data/raw/stock-main-index-data `
  --output /data/curated/trade_data/_inventory.index_daily.json

docker compose --profile tools run --rm index-daily-data-prep

docker compose --profile tools run --rm index-daily-data-prep `
  python scripts/index_daily_pipeline.py validate `
  --output /data/curated/trade_data

docker compose --profile tools run --rm index-daily-data-prep `
  python scripts/index_daily_pipeline.py compact `
  --output /data/curated/trade_data
```

产物为分片目录 `trade_data/index_daily/`、压实查询文件
`trade_data/index_daily.parquet` 和独立增量清单
`trade_data/_pipeline_manifest.index_daily.json`。原始 CSV 首行就是英文表头，因此该配置不会跳过说明行。

转换完成后把 `backend/.env` 改为以下配置并重启后端：

```env
DATABASE_SWITCHES=trade_data
TRADE_DATA_ROOT=D:/trade_data
CURATED_DATA_ROOT=D:/trade_data_curated
```

如需同时启用其他金融数据库，使用逗号分隔，例如
`DATABASE_SWITCHES=trade_data,fund_data`；一次查询仍不能跨两个数据库联表。

分别打开两个终端。

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

### 本机公网预览（Cloudflare Tunnel）

公网预览使用独立的生产后端、Nginx 静态前端和 Cloudflare Tunnel，不暴露开发服务器、
FastAPI 端口或本地数据目录。先复制配置：

```powershell
Copy-Item .env.public.example .env.public
```

编辑忽略提交的 `.env.public`：

- 为 `FINQUERY_ADMIN_PASSWORD` 和 `FINQUERY_MARKET_PASSWORD` 设置不同的随机密码，长度至少 16 位。
- 先在 Cloudflare Zero Trust 为 `finquery.dev` 创建 Access Self-hosted Application，只允许指定邮箱。
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

公网模式会关闭 `/docs`、`/redoc` 和 `/openapi.json`，并在 Nginx 对登录、查询及普通 API
分别限流。如果仍使用默认密码或密码不足 16 位，`backend-public` 会拒绝启动。停止预览：

```powershell
docker compose --env-file .env.public --profile public-preview down
```

## 测试

在 `backend` 目录执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe scripts\stock_daily_pipeline.py validate
.\.venv\Scripts\python.exe scripts\index_daily_pipeline.py validate
```

## 测试账号

- 管理员：`admin` / `admin123`
- 行情分析：`market` / `market123`
