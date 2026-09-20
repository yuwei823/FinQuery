# AGENTS.md

This file applies to the entire repository. It is a working guide for coding agents; `README.md` remains the user-facing setup and database-registration guide.

## Project purpose

FinQuery Studio is a Chinese-language natural-language analytics application for financial market data. A Vue 3 client sends questions and optional workspace context to a FastAPI backend. The backend uses LangGraph to route requests, retrieve field-level schema, ask for clarification when needed, generate read-only DuckDB SQL through an in-process MCP tool, and turn the results into an answer or report.

The registered database is `trade_data`, backed by curated Parquet generated from external daily market-data directories. It currently exposes stock and major-index daily tables. Multiple financial databases can be enabled, but a query spanning more than one database deliberately ends in the not-yet-implemented multi-database path.

## Repository map

```text
frontend/
  src/App.vue                 Main UI, login, conversations, workspace, examples
  src/api.ts                  HTTP client and session token handling
  src/types.ts                Frontend API contracts
  src/components/             Result tables, reports, markdown, and charts
  src/styles/                 SCSS tokens, mixins, feature modules, responsive rules
  vite.config.ts              Dev server on 127.0.0.1:5173; proxies /api to :8000

backend/
  run.py                      Uvicorn entry point
  app/main.py                 FastAPI app and CORS
  app/api/routes.py           /api endpoints and auth dependencies
  app/config.py               .env loading and all runtime settings
  app/models.py               Pydantic request/response contracts
  app/services/               Service facade, session context, memory persistence
  app/workflows/query_graph.py LangGraph orchestration and human clarification
  app/preprocessing.py        One-call intent routing/query rewrite/retrieval terms
  app/retrieval/              BM25 + embeddings + RRF + rerank and schema graph
  app/querying/               Query agent, SQL validation/execution, response/QA
  app/mcp_runtime/            In-process MCP server, client, and tool definitions
  app/skills/                 App-specific prompts and tool/action allowlists
  app/security/               Mock auth and table/database access control
  app/database.py             Enabled database catalog and schema validation
  app/database_sources/       Database registry and field synonym modules
  data/databases/             Schema manifests and optional colocated CSV/Parquet data
  scripts/                    Data/schema generation and integrity validation
  tests/                      `unittest` suite

compose.yaml                  Local development, data tools, and public-preview services
.env.*.example                Ignored local/Compose configuration templates
docs/                         Design and migration notes; not runtime contracts
```

## Request flow

1. `POST /api/query` authenticates the user and calls `FinQueryService.submit`.
2. `RequestPreprocessor` returns one of `direct_response`, `data_qa`, or `database_query`.
3. Database questions retrieve schema fields using BM25 and dense search, fuse candidates with RRF, rerank them, and build a connected schema graph.
4. `SingleDatabaseAgent` follows `app/skills/database_query/SKILL.md` and calls only its allowed in-process MCP tools.
5. `DuckDbEngine` validates one DuckDB `SELECT`/`WITH` statement, enforces access scope, rejects `SELECT *`, and registers CSV files, Parquet files, or partition directories as read-only views. It returns at most 200 rows.
6. LangGraph uses an in-memory checkpointer and `interrupt`/`Command(resume=...)` for clarification. Active clarification state remains process-local. Optional session archiving restores completed turns and summaries, not an interrupted LangGraph checkpoint.

Existing-result analysis is a separate `data_qa` route. It can produce Markdown plus bar/pie chart specifications, but charts must reference columns from an available prior result.

## Setup and common commands

Use Python 3.11 and Node.js 20.19 or newer. Docker Desktop is additionally required for Compose development, data-tool containers, and public preview. Commands below start at the repository root.

```powershell
# Backend setup (Windows)
py -3.11 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
Copy-Item backend/.env.example backend/.env

# Backend server
Set-Location backend
.venv/Scripts/python.exe run.py

# Frontend setup/server (from repository root in another shell)
Set-Location frontend
npm ci
npm run dev
```

Required live-model configuration belongs in ignored `backend/.env`. `LLM_API_KEY` is the critical secret. Host data paths for Compose belong in ignored `.env.docker` or `.env.public`. Never commit environment files, access tokens, generated caches, or dependency/build directories.

## Verification

There is no configured linter. Run the checks relevant to the changed area; for cross-cutting changes run all of these:

```powershell
# Backend unit tests
Set-Location backend
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"

# Dataset/schema integrity
.venv/Scripts/python.exe scripts/stock_daily_pipeline.py validate
.venv/Scripts/python.exe scripts/index_daily_pipeline.py validate
.venv/Scripts/python.exe scripts/financial_statement_pipeline.py validate

# Frontend type-check and production build
Set-Location ../frontend
npm run build
```

Live model calls can incur cost, so do not run them unless the task explicitly requires live evaluation and credentials are available.

## Change guidance

- Keep backend API models in `backend/app/models.py` and matching TypeScript contracts in `frontend/src/types.ts` synchronized.
- Put HTTP behavior in `frontend/src/api.ts`; keep view/workspace behavior in `App.vue` or a focused component.
- Preserve the workflow boundaries: routing/preprocessing, schema retrieval, SQL planning, SQL execution, and response generation are separate stages with explicit errors.
- Do not add heuristic semantic fallbacks silently. The current design exposes model/embedding/rerank failures as named `PipelineStageError` stages; the only conservative routing fallback is a direct response when preprocessing is unavailable.
- Preserve SQL safety: one read-only query, explicit projection, known tables, database/table authorization, and path-safe database identifiers. Do not bypass `DuckDbEngine._validate_sql` for model-generated SQL.
- Apply authorization at every new data-bearing endpoint/tool. User sessions, tasks, memories, visible schema, retrieval, and DuckDB execution are user-scoped.
- Treat `backend/app/skills/*/SKILL.md` and `config.json` as runtime contracts. If a tool or output action changes, update the skill allowlist, implementation, validation, and tests together.
- The frontend stores the bearer token in `sessionStorage` and conversation/workspace UI state locally. Authentication is intentionally mock/in-memory and is not production security.
- Public-preview passwords come from `.env.public`; default development passwords are rejected when `FINQUERY_PUBLIC_MODE=true`. Guest quota is persisted in the `guest_runtime` Compose volume, while bearer tokens, active tasks, and public-container memory files are not shared durable state.
- Use UTF-8 for Chinese text and fixtures. Avoid mechanical rewrites of `_schema.json`, CSVs, Parquet data, or generated manifests.

## Adding or changing a database

Follow the detailed checklist in `README.md`. In summary:

1. Add `backend/data/databases/<database_key>/_schema.json` and matching CSV/Parquet tables, or configure a separate `DatabaseSource.data_folder`.
2. Add a module under `backend/app/database_sources/` with `DATABASE_ID` and fully qualified field `SYNONYMS`.
3. Register it in `backend/app/database_sources/__init__.py`, including the query-data folder when it is separate from the schema folder.
4. Add `role_tables` in the schema and update mock accounts/access policy only if introducing roles.
5. Add frontend examples in `promptsByDatabase` when useful.
6. Add database-switch, schema, synonym, permission, and data-integrity tests.

`DATABASE_SWITCHES` is a comma-separated set. Changing it requires a backend restart. Schema caches are generated as `backend/data/schema_store.<sorted-database-signature>.json` and are ignored by Git; do not hand-edit or commit them.

## Generated and persistent files

- Ignored/generated: environment files, `backend/data/schema_store.*.json`, `backend/data/*.db`, generated Parquet/manifest data, `frontend/node_modules/`, `frontend/dist/`, Python caches, and TypeScript build info.
- `backend/data/saved_memories.json` is checked in even though the app mutates it during use. Tests should use temporary paths, and agents should avoid committing incidental runtime changes to this file.
- Public Compose persists guest quota in `guest_runtime`, but does not mount `saved_memories.json` or the optional session archive. Recreating `backend-public` therefore discards runtime changes stored only in that container.

## Test expectations

Add focused `unittest` coverage for backend behavior. Existing tests use small fake model clients and temporary files where practical; prefer that pattern over network calls. Important regression areas are intent routing, database switches, schema/synonym integrity, CSV/Parquet registration, pipeline integrity, permission isolation, guest quota/public mode, saved-memory isolation, short-term summarization, skill allowlists, and DuckDB read-only enforcement.

For frontend changes, at minimum run `npm run build`; there is currently no browser test suite. Manually exercise login, a query, clarification, memory actions, and report rendering when the change touches those flows.
