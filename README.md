# AskData Studio 运营场景版

面向短视频运营的自然语言问数项目，包含 Vue 前端、FastAPI + LangGraph 后端、41 张 CSV 数据表、字段级 Schema 索引、测试脚本和当前评测报告。

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
`short_video_ops`。每个可选数据库需要在 `backend/app/database_sources/` 注册自己的
Schema 目录和 `SYNONYMS`；切换后端配置后需重启服务。

## 注册新的数据库

下面以数据库 key `customer_ops` 为例。数据库 key 只能包含英文字母、数字和下划线，
并且必须以英文字母或下划线开头。

### 1. 添加数据库文件

新建目录：

```text
backend/data/databases/customer_ops/
├── _schema.json
├── _database_manifest.json  # 推荐提供，但运行时不强制读取
├── customers.csv
└── orders.csv
```

CSV 文件名就是 DuckDB 中的物理表名。文件名必须是安全的 SQL 标识符，并与
`_schema.json` 中表的 `name` 一致；CSV 表头必须与 Schema 的字段名一致。

`_schema.json` 至少需要包含：

```json
{
  "database": "customer_ops",
  "tables": [
    {
      "id": "customer_ops.customers",
      "name": "customers",
      "database": "customer_ops",
      "label": "客户",
      "description": "客户主数据",
      "fields": [
        {
          "name": "customer_id",
          "label": "客户编号",
          "type": "文本",
          "description": "客户唯一编号",
          "aliases": ["客户编号"]
        }
      ]
    }
  ],
  "relations": [],
  "role_tables": {
    "growth_ops": ["customers"]
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

新建 `backend/app/database_sources/customer_ops.py`：

```python
from __future__ import annotations


DATABASE_ID = "customer_ops"

SYNONYMS: dict[str, list[str]] = {
    "customer_ops.customers.customer_id": ["客户编号", "客户ID"],
    "customer_ops.orders.paid_amount": ["销售额", "成交额", "实付金额"],
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
from .customer_ops import DATABASE_ID as CUSTOMER_OPS_ID
from .customer_ops import SYNONYMS as CUSTOMER_OPS_SYNONYMS
```

然后在 `source_registry()` 返回值中添加：

```python
CUSTOMER_OPS_ID: DatabaseSource(
    database_id=CUSTOMER_OPS_ID,
    folder=database_root / CUSTOMER_OPS_ID,
    synonyms=CUSTOMER_OPS_SYNONYMS,
),
```

只有放入该注册表的 key 才能写入 `DATABASE_SWITCHES`；未知 key 会让后端在启动时
明确报错。

### 4. 启用数据库

修改 `backend/.env`：

```env
DATABASE_SWITCHES=customer_ops
```

同时启用多个数据库时使用逗号分隔：

```env
DATABASE_SWITCHES=short_video_ops,customer_ops
```

修改后重启后端。Schema 索引会按已启用数据库集合生成独立缓存，例如：

```text
backend/data/schema_store.customer_ops.json
backend/data/schema_store.customer_ops-short_video_ops.json
```

这些缓存是自动生成物，已被 Git 忽略。首次查询会在签名不匹配或缓存不存在时重建；
管理员也可以调用 `POST /api/schema/index/rebuild` 强制重建。

### 5. 配置权限和测试账号（按需）

如果新数据库继续使用现有的 `growth_ops`、`channel_ops` 或 `content_ops` 角色，只需在
新 Schema 的 `role_tables` 中列出对应表，无需修改权限代码。

如果需要新增角色或登录账号，还要同步修改：

- `backend/app/security/auth.py`：在 `AuthService.ACCOUNTS` 中添加测试账号。
- `backend/app/security/access_control.py`：增加用户到角色的映射和对应角色策略。

管理员角色会自动获得所有已启用数据库及其全部 Schema 表的访问权限。

### 6. 添加前端示例问题（推荐）

修改 `frontend/src/App.vue` 中的 `promptsByDatabase`：

```ts
const promptsByDatabase: Record<string, string[]> = {
  customer_ops: [
    "查询本月销售额",
    "按地区统计客户数量",
  ],
}
```

前端根据 `/api/schema` 返回的数据库标识展示相应问题。数据库没有配置示例时，加载
Schema 后不会错误展示其他数据库的问题。

### 7. 补充验证和评测（推荐）

- 为新数据库增加数据完整性验证脚本，或将
  `backend/scripts/validate_short_video_ops.py` 泛化为多数据库脚本。
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

## 测试

在 `backend` 目录执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe scripts\validate_short_video_ops.py
```

评测命令与指标说明见 `backend/evaluation/README.md`。现有评测结果位于 `backend/evaluation/results`。

## 测试账号

- 管理员：`admin` / `admin123`
- 用户增长运营：`growth` / `growth123`
- 渠道投放运营：`channel` / `channel123`
- 内容运营：`content` / `content123`
