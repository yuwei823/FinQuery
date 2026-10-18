from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from typing import Any, Callable

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from ..database import SCHEMA, physical_table_name
from ..errors import PipelineStageError
from ..mcp_runtime.client import LocalMcpClient
from ..model_client import ModelClient
from ..skills import SkillDefinition
from ..workflows.progress import STAGE_EXECUTING, STAGE_PLANNING_SQL, STAGE_SQL_READY


class SingleDatabaseAgent:
    """让模型通过MCP工具完成单数据库查询。"""

    def __init__(
        self,
        model_client: ModelClient,
        mcp_client_factory: Callable[[dict[str, Any]], LocalMcpClient],
        skill: SkillDefinition,
        max_tool_calls: int = 3,
    ) -> None:
        self.model_client = model_client
        self.mcp_client_factory = mcp_client_factory
        self.skill = skill
        self.max_tool_calls = min(max_tool_calls, skill.max_tool_calls)

    def prepare(
        self,
        query: str,
        database: str,
        schema_graph: dict[str, Any],
        schema_context: str,
        retrieval: dict[str, Any],
        workspace: dict[str, Any],
        access_scope: dict[str, Any],
        progress: Callable[[str, str, str], None] | None = None,
        original_query: str | None = None,
    ) -> dict[str, Any]:
        database_tool = f"query_{database}"
        notify = progress or (lambda _stage, _message, _detail="": None)
        mcp_client = self.mcp_client_factory(access_scope)

        # 每次请求都通过MCP tools/list获取当前工具定义。
        catalog = mcp_client.list_tools()
        tools = [
            tool
            for tool in catalog
            if any(fnmatch(tool["name"], pattern) for pattern in self.skill.allowed_tools)
            and (not tool["name"].startswith("query_") or tool["name"] == database_tool)
        ]
        tool_names = {tool["name"] for tool in tools}
        if database_tool not in tool_names:
            raise PipelineStageError(
                "mcp_tool_discovery",
                f"没有找到数据库工具：{database_tool}",
            )

        system = f"你是单数据库问数智能体。\n\n{self.skill.instructions}"

        observations: list[dict[str, Any]] = []
        tool_trace: list[dict[str, Any]] = []
        base_payload = {
            "query": query,
            "original_query": original_query or query,
            "database": database,
            "schema_graph": schema_graph,
            "retrieval": {
                "threshold": retrieval.get("threshold"),
                "selected_fields": retrieval.get("hits", []),
                "low_confidence_candidates": retrieval.get("low_confidence_candidates", []),
            },
            "confirmed_fields": workspace.get("schema_fields", []),
            "confirmed_parameters": workspace.get("confirmed_parameters", {}),
            "schema_text": schema_context,
            "mcp_tools": tools,
        }

        retry_after_failure = False
        try:
            for call_index in range(1, self.max_tool_calls + 1):
                # SQL 执行失败后的修正调用使用精简上下文，缩短模型首 token 延迟。
                if retry_after_failure:
                    payload = self._retry_payload(base_payload, observations)
                else:
                    payload = {**base_payload, "tool_results": observations}
                notify(
                    STAGE_PLANNING_SQL,
                    "正在生成 SQL" if call_index == 1 else f"查询失败，正在修正 SQL（第 {call_index} 次尝试）",
                )
                decision = self._validated_decision(system, payload, tool_names)
                action = str(decision["action"])

                if action == "clarify":
                    clarification = decision.get("clarification")
                    if not isinstance(clarification, dict) or len(
                        clarification.get("options") or []
                    ) < 2:
                        raise ValueError("智能体返回的澄清信息不完整")
                    return {
                        "action": "clarify",
                        "clarification": clarification,
                        "tool_trace": tool_trace,
                    }

                if action != "call_tool":
                    raise ValueError("智能体必须返回call_tool或clarify")

                tool_name = str(decision["tool_name"])
                arguments = decision["arguments"]

                if tool_name == database_tool:
                    sql = str(arguments.get("sql") or "").strip()
                    previous_sql = {
                        str(item.get("arguments", {}).get("sql") or "").strip()
                        for item in tool_trace
                    }
                    if sql in previous_sql:
                        observations.append({
                            "tool": tool_name,
                            "result": {
                                "success": False,
                                "error": "相同SQL已经失败，禁止原样重试",
                            },
                            "instruction": (
                                "不得重复失败SQL。只使用schema_text中明确列出的字段，"
                                "根据上一条数据库错误实质修正字段名后再调用。"
                            ),
                        })
                        continue

                if tool_name == database_tool:
                    notify(
                        STAGE_SQL_READY,
                        f"SQL 已生成（第 {call_index} 次尝试）",
                        str(arguments.get("sql") or "").strip(),
                    )
                    notify(STAGE_EXECUTING, "正在执行查询")

                tool_result = mcp_client.call_tool(tool_name, arguments)
                trace = {
                    "call_index": call_index,
                    "tool": tool_name,
                    "arguments": arguments,
                    "query_contract": decision.get("query_contract", {}),
                    "result": tool_result,
                    "reason": str(decision.get("reason") or ""),
                }
                tool_trace.append(trace)

                if tool_name == database_tool:
                    if not bool(tool_result.get("success")) and call_index < self.max_tool_calls:
                        retry_after_failure = True
                        observations.append({
                            "tool": tool_name,
                            "query_contract": decision.get("query_contract", {}),
                            "result": tool_result,
                            "instruction": (
                                "上一条SQL执行失败。只根据数据库错误、原问题和Schema修正SQL，"
                                "不得改变查询口径，不得猜测Schema之外的字段，也不得原样重复失败SQL，"
                                "不得引入原问题未要求的表、行业或其他维度；保持查询契约的业务范围，"
                                "然后重新调用同一个数据库工具。"
                            ),
                        })
                        continue
                    return {
                        "action": "executed",
                        "execution": tool_result,
                        "tool_trace": tool_trace,
                        "source": "model_mcp",
                    }

                observations.append({"tool": tool_name, "result": tool_result})

            raise ValueError(f"MCP工具调用超过上限：{self.max_tool_calls}")
        except PipelineStageError:
            raise
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            raise PipelineStageError("single_database_agent", str(exc)) from exc

    @staticmethod
    def _retry_payload(
        base_payload: dict[str, Any],
        observations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """SQL 修正调用的精简上下文：去掉工具目录等冗余信息。"""
        retrieval = base_payload.get("retrieval") or {}
        return {
            "query": base_payload.get("query"),
            "original_query": base_payload.get("original_query"),
            "database": base_payload.get("database"),
            "schema_graph": base_payload.get("schema_graph", {}),
            "schema_text": base_payload.get("schema_text"),
            "confirmed_fields": base_payload.get("confirmed_fields", []),
            "confirmed_parameters": base_payload.get("confirmed_parameters", {}),
            # selected_fields 供显式枚举值校验继续使用。
            "retrieval": {"selected_fields": retrieval.get("selected_fields", [])},
            "tool_results": observations,
        }

    def _validated_decision(
        self,
        system: str,
        payload: dict[str, Any],
        tool_names: set[str],
    ) -> dict[str, Any]:
        """结构化结果不完整时让模型最多修正两次，不执行不完整的工具调用。"""
        validation_error = ""
        previous_decision: dict[str, Any] | None = None
        for attempt in range(3):
            request_payload = dict(payload)
            if validation_error:
                request_payload["previous_invalid_output"] = previous_decision
                request_payload["output_validation_error"] = validation_error
                request_payload["output_validation_instruction"] = self._validation_instruction(
                    validation_error,
                )
            decision = self.model_client.chat_json(
                system,
                json.dumps(request_payload, ensure_ascii=False),
            )
            previous_decision = decision
            validation_error = self._decision_error(decision, tool_names)
            if not validation_error:
                validation_error = self._explicit_filter_error(decision, payload)
            if not validation_error:
                validation_error = self._schema_reference_error(decision, payload)
            if not validation_error:
                validation_error = self._semantic_query_error(decision, payload)
            if not validation_error:
                return decision
            if attempt == 2:
                repaired = self._repair_simple_recent_period_query(decision, payload)
                if repaired is not None:
                    repaired_error = self._decision_error(repaired, tool_names)
                    if not repaired_error:
                        repaired_error = self._explicit_filter_error(repaired, payload)
                    if not repaired_error:
                        repaired_error = self._schema_reference_error(repaired, payload)
                    if not repaired_error:
                        repaired_error = self._semantic_query_error(repaired, payload)
                    if not repaired_error:
                        return repaired
                raise ValueError(validation_error)
        raise ValueError(validation_error)

    @staticmethod
    def _validation_instruction(validation_error: str) -> str:
        instruction = (
            "上一次输出未通过调用前校验。根据错误修正JSON字段或SQL，"
            "保持原查询口径并重新输出完整对象。"
        )
        if "最近" in validation_error and "report_date DESC" in validation_error:
            instruction += (
                " 最近N个报告期且最终升序时，必须使用这一层级："
                "SELECT ... FROM (SELECT ... FROM financial_period WHERE ... "
                "QUALIFY ROW_NUMBER() OVER (PARTITION BY report_date "
                "ORDER BY publish_date DESC) = 1 ORDER BY report_date DESC LIMIT N) recent "
                "ORDER BY report_date ASC。不要在最外层直接ASC LIMIT N。"
            )
        elif "外层查询必须ORDER BY report_date ASC" in validation_error:
            instruction += (
                " 最近N期已经在内层截取后，最外层SELECT末尾必须补充"
                "ORDER BY report_date ASC；不要改动内层的DESC LIMIT N。"
            )
        return instruction

    @classmethod
    def _repair_simple_recent_period_query(
        cls,
        decision: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """最后一次重试仍为简单ASC LIMIT时，确定性修正最近报告期语义。"""
        query = str(payload.get("original_query") or payload.get("query") or "")
        match = re.search(r"最近\s*(\d+)\s*个[^，。；]*报告期", query)
        if not match or not (
            "按报告期升序" in query or "报告期升序排列" in query
        ):
            return None
        period_count = int(match.group(1))
        sql = str((decision.get("arguments") or {}).get("sql") or "").strip()
        try:
            statement = sqlglot.parse_one(sql, read="duckdb")
        except (ParseError, ValueError):
            return None
        if not isinstance(statement, exp.Select):
            return None
        if cls._has_recent_period_core(statement, period_count):
            output_names = [projection.alias_or_name for projection in statement.expressions]
            if (
                not output_names
                or any(not name or name == "*" for name in output_names)
            ):
                return None
            report_order_name = "report_date"
            for projection in statement.expressions:
                source = projection.this if isinstance(projection, exp.Alias) else projection
                if isinstance(source, exp.Column) and source.name.casefold() == "report_date":
                    report_order_name = projection.alias_or_name
                    break
            repaired_statement = statement.copy()
            if cls._limit_value(repaired_statement) == period_count:
                repaired_statement = (
                    exp.select(*(exp.column(name) for name in output_names))
                    .from_(repaired_statement.subquery("recent"))
                )
            repaired_statement.set(
                "order",
                exp.Order(
                    expressions=[
                        exp.Ordered(this=exp.column(report_order_name), desc=False),
                    ],
                ),
            )
            repaired = dict(decision)
            repaired["arguments"] = dict(decision.get("arguments") or {})
            repaired["arguments"]["sql"] = repaired_statement.sql(dialect="duckdb")
            repaired["reason"] = (
                str(decision.get("reason") or "")
                + "；系统已补全最近报告期结果的最终升序展示"
            ).lstrip("；")
            return repaired

        tables = [table for table in statement.find_all(exp.Table)]
        if len(tables) != 1 or tables[0].name != "financial_period":
            return None
        if (
            statement.args.get("joins")
            or statement.args.get("group")
            or statement.args.get("having")
            or statement.args.get("qualify")
            or statement.args.get("with")
            or cls._limit_value(statement) != period_count
            or not cls._orders_by(statement, "report_date", descending=False)
        ):
            return None
        output_names = [projection.alias_or_name for projection in statement.expressions]
        if not output_names or any(not name for name in output_names):
            return None

        inner = statement.copy()
        latest_publish_window = exp.Window(
            this=exp.RowNumber(),
            partition_by=[exp.column("report_date")],
            order=exp.Order(
                expressions=[
                    exp.Ordered(this=exp.column("publish_date"), desc=True),
                ],
            ),
        )
        inner.set(
            "qualify",
            exp.Qualify(
                this=exp.EQ(
                    this=latest_publish_window,
                    expression=exp.Literal.number(1),
                ),
            ),
        )
        inner.set(
            "order",
            exp.Order(
                expressions=[
                    exp.Ordered(this=exp.column("report_date"), desc=True),
                ],
            ),
        )
        repaired_statement = (
            exp.select(*(exp.column(name) for name in output_names))
            .from_(inner.subquery("recent"))
            .order_by(exp.Ordered(this=exp.column("report_date"), desc=False))
        )
        repaired = dict(decision)
        repaired["arguments"] = dict(decision.get("arguments") or {})
        repaired["arguments"]["sql"] = repaired_statement.sql(dialect="duckdb")
        repaired["reason"] = (
            str(decision.get("reason") or "")
            + "；系统已确定性修正最近报告期的截取与展示顺序"
        ).lstrip("；")
        return repaired

    @classmethod
    def _has_recent_period_core(
        cls,
        statement: exp.Expression,
        period_count: int,
    ) -> bool:
        limited_selects = [
            select
            for select in statement.find_all(exp.Select)
            if cls._limit_value(select) == period_count
        ]
        if not any(
            cls._orders_by(select, "report_date", descending=True)
            for select in limited_selects
        ):
            return False
        has_latest_version_window = any(
            isinstance(window.this, exp.RowNumber)
            and any(
                isinstance(item, exp.Column)
                and item.name.casefold() == "report_date"
                for item in (window.args.get("partition_by") or [])
            )
            and isinstance(window.args.get("order"), exp.Order)
            and any(
                isinstance(item.this, exp.Column)
                and item.this.name.casefold() == "publish_date"
                and bool(item.args.get("desc"))
                for item in window.args["order"].expressions
            )
            for window in statement.find_all(exp.Window)
        )
        return has_latest_version_window and any(statement.find_all(exp.Qualify))

    def _decision_error(self, decision: dict[str, Any], tool_names: set[str]) -> str:
        action = str(decision.get("action") or "")
        if action not in self.skill.output_actions:
            return f"Skill不允许输出动作：{action}"
        if action == "clarify":
            clarification = decision.get("clarification")
            if not isinstance(clarification, dict) or len(clarification.get("options") or []) < 2:
                return "智能体返回的澄清信息不完整"
            return ""
        if action != "call_tool":
            return "智能体必须返回call_tool或clarify"
        tool_name = str(decision.get("tool_name") or "")
        if tool_name not in tool_names:
            return f"智能体选择了未提供的MCP工具：{tool_name}"
        if not isinstance(decision.get("arguments"), dict):
            return "MCP工具参数必须是JSON对象"
        if tool_name.startswith("query_"):
            contract = decision.get("query_contract")
            if not isinstance(contract, dict):
                return "数据库工具调用必须包含query_contract"
            required = ("grain", "source_tables", "filters", "metrics", "output_columns")
            missing = [key for key in required if key not in contract]
            if missing:
                return "query_contract缺少字段：" + "、".join(missing)
            if not isinstance(contract.get("source_tables"), list):
                return "query_contract.source_tables必须是数组"
            if not isinstance(contract.get("filters"), list):
                return "query_contract.filters必须是数组"
            if not isinstance(contract.get("metrics"), list):
                return "query_contract.metrics必须是数组"
            if not isinstance(contract.get("output_columns"), list):
                return "query_contract.output_columns必须是数组"
        return ""

    @staticmethod
    def _schema_reference_error(
        decision: dict[str, Any],
        payload: dict[str, Any],
    ) -> str:
        """调用数据库前限制表范围，并按完整注册Schema核验字段和代码格式。"""
        if decision.get("action") != "call_tool":
            return ""
        if not str(decision.get("tool_name") or "").startswith("query_"):
            return ""
        graph = payload.get("schema_graph") or {}
        graph_tables = list(graph.get("tables") or [])
        graph_fields = list(graph.get("fields") or [])
        if not graph_tables:
            return ""

        table_fields: dict[str, set[str]] = {}
        table_id_to_name: dict[str, str] = {}
        catalog_by_id = {str(table.get("id") or ""): table for table in SCHEMA}
        catalog_by_name = {physical_table_name(table): table for table in SCHEMA}
        for table in graph_tables:
            table_id = str(table.get("id") or "")
            table_name = str(table.get("name") or table_id.rsplit(".", 1)[-1])
            table_id_to_name[table_id] = table_name
            definition = catalog_by_id.get(table_id) or catalog_by_name.get(table_name)
            table_fields[table_name] = {
                str(field.get("name") or "")
                for field in (definition or {}).get("fields", [])
                if field.get("name")
            }
        for field in graph_fields:
            table_id = str(field.get("table_id") or "")
            table_name = str(
                field.get("table_name")
                or table_id_to_name.get(table_id)
                or table_id.rsplit(".", 1)[-1]
            )
            field_name = str(field.get("name") or field.get("field_name") or "")
            if field_name:
                table_fields.setdefault(table_name, set()).add(field_name)

        sql = str((decision.get("arguments") or {}).get("sql") or "").strip()
        try:
            statement = sqlglot.parse_one(sql, read="duckdb")
        except (ParseError, ValueError) as exc:
            return f"SQL无法解析，不能核验Schema引用：{exc}"

        cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
        table_aliases: dict[str, str] = {}
        referenced_tables: set[str] = set()
        for table in statement.find_all(exp.Table):
            if table.name in cte_names:
                continue
            referenced_tables.add(table.name)
            table_aliases[table.alias_or_name] = table.name
            table_aliases[table.name] = table.name
        unknown_tables = sorted(referenced_tables - set(table_fields))
        if unknown_tables:
            return "SQL引用了本轮Schema图之外的数据表：" + "、".join(unknown_tables)

        projection_aliases = {
            str(projection.alias)
            for select in statement.find_all(exp.Select)
            for projection in select.expressions
            if projection.alias
        }
        unknown_fields: set[str] = set()
        for column in statement.find_all(exp.Column):
            name = column.name
            if name in projection_aliases:
                continue
            qualifier = column.table
            if qualifier:
                table_name = table_aliases.get(qualifier)
                if table_name and name not in table_fields.get(table_name, set()):
                    unknown_fields.add(f"{qualifier}.{name}")
                continue
            if len(referenced_tables) == 1:
                table_name = next(iter(referenced_tables))
                if name not in table_fields.get(table_name, set()):
                    unknown_fields.add(name)
            elif referenced_tables and not any(
                name in table_fields.get(table_name, set())
                for table_name in referenced_tables
            ):
                unknown_fields.add(name)
        if unknown_fields:
            return "SQL引用了注册Schema中不存在的字段：" + "、".join(sorted(unknown_fields))

        for equality in statement.find_all(exp.EQ):
            pairs = (
                (equality.this, equality.expression),
                (equality.expression, equality.this),
            )
            for field, value in pairs:
                if not isinstance(field, exp.Column) or field.name.casefold() != "symbol":
                    continue
                if not isinstance(value, exp.Literal) or not value.is_string:
                    continue
                symbol = str(value.this)
                if not re.fullmatch(r"(?:sh|sz|bj)\d{6}", symbol):
                    return (
                        f"股票代码格式不符合本地Schema：{symbol}；"
                        "应使用sh600519、sz000001或bj920000形式"
                    )
        return ""

    @classmethod
    def _semantic_query_error(
        cls,
        decision: dict[str, Any],
        payload: dict[str, Any],
    ) -> str:
        """校验可确定的显式业务条件，防止合法SQL遗漏用户语义。"""
        if decision.get("action") != "call_tool":
            return ""
        if not str(decision.get("tool_name") or "").startswith("query_"):
            return ""

        # 独立问题由预处理模型改写，显式限制必须以原始用户问题为准。
        query = str(payload.get("original_query") or payload.get("query") or "")
        latest_phrases = (
            "最新交易日",
            "最近交易日",
            "最新一个交易日",
            "最近一个交易日",
        )
        requires_latest_trade_date = any(phrase in query for phrase in latest_phrases)
        requires_general_enterprise = "一般企业" in query
        recent_period_match = re.search(
            r"最近\s*(\d+)\s*个[^，。；]*报告期",
            query,
        )
        if (
            not requires_latest_trade_date
            and not requires_general_enterprise
            and not recent_period_match
        ):
            return ""

        sql = str((decision.get("arguments") or {}).get("sql") or "").strip()
        try:
            statement = sqlglot.parse_one(sql, read="duckdb")
        except (ParseError, ValueError) as exc:
            return f"SQL无法解析，不能核验显式业务条件：{exc}"

        filters = list((decision.get("query_contract") or {}).get("filters") or [])
        if requires_latest_trade_date:
            if not cls._contract_has_filter(filters, "trade_date", latest_phrases):
                return (
                    "query_contract遗漏“最新交易日”的"
                    "trade_date = MAX(trade_date)全局最大值条件"
                )
            if not cls._has_global_latest_trade_date_filter(statement):
                return (
                    "SQL遗漏“最新交易日”条件：全市场横截面必须按来源表的"
                    "MAX(trade_date)过滤，ORDER BY trade_date DESC不能替代该条件"
                )

        if requires_general_enterprise:
            if not cls._contract_has_filter(filters, "statement_format", ("一般企业",)):
                return "query_contract遗漏statement_format=一般企业条件"
            if not cls._has_literal_filter(statement, "statement_format", "一般企业"):
                return "SQL遗漏用户明确要求的statement_format='一般企业'条件"

        if recent_period_match:
            period_count = int(recent_period_match.group(1))
            period_error = cls._recent_financial_period_error(
                statement,
                period_count,
                require_final_ascending=(
                    "按报告期升序" in query or "报告期升序排列" in query
                ),
            )
            if period_error:
                return period_error
        return ""

    @classmethod
    def _recent_financial_period_error(
        cls,
        statement: exp.Expression,
        period_count: int,
        *,
        require_final_ascending: bool,
    ) -> str:
        """核验最近N个报告期的版本去重、截取方向和最终展示顺序。"""
        limited_selects = [
            select
            for select in statement.find_all(exp.Select)
            if cls._limit_value(select) == period_count
        ]
        if not any(
            cls._orders_by(select, "report_date", descending=True)
            for select in limited_selects
        ):
            return (
                f"“最近{period_count}个报告期”必须先按report_date DESC "
                f"LIMIT {period_count}截取，不能直接升序LIMIT"
            )

        has_latest_version_window = False
        for window in statement.find_all(exp.Window):
            if not isinstance(window.this, exp.RowNumber):
                continue
            partitions = list(window.args.get("partition_by") or [])
            if not any(
                isinstance(item, exp.Column)
                and item.name.casefold() == "report_date"
                for item in partitions
            ):
                continue
            order = window.args.get("order")
            if isinstance(order, exp.Order) and any(
                isinstance(item.this, exp.Column)
                and item.this.name.casefold() == "publish_date"
                and bool(item.args.get("desc"))
                for item in order.expressions
            ):
                has_latest_version_window = True
                break
        if not has_latest_version_window:
            return (
                "financial_period同一报告期可能有多个披露版本；必须按report_date分区，"
                "以publish_date DESC选择最新版本"
            )
        if not any(statement.find_all(exp.Qualify)):
            return "报告期版本窗口必须通过QUALIFY筛选为每期一条记录"

        if require_final_ascending:
            outer_select = statement if isinstance(statement, exp.Select) else statement.find(exp.Select)
            if not isinstance(outer_select, exp.Select) or not cls._orders_by(
                outer_select,
                "report_date",
                descending=False,
            ):
                return "用户要求最终按报告期升序展示，外层查询必须ORDER BY report_date ASC"
        return ""

    @staticmethod
    def _limit_value(select: exp.Select) -> int | None:
        limit = select.args.get("limit")
        value = limit.expression if isinstance(limit, exp.Limit) else None
        if isinstance(value, exp.Literal) and not value.is_string:
            try:
                return int(value.this)
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _orders_by(
        select: exp.Select,
        field_name: str,
        *,
        descending: bool,
    ) -> bool:
        order = select.args.get("order")
        if not isinstance(order, exp.Order):
            return False
        target = field_name.casefold()
        equivalent_names = {target}
        target_positions: set[int] = set()
        for index, projection in enumerate(select.expressions, start=1):
            source = projection.this if isinstance(projection, exp.Alias) else projection
            if isinstance(source, exp.Column) and source.name.casefold() == target:
                target_positions.add(index)
                if projection.alias:
                    equivalent_names.add(str(projection.alias).casefold())
        for item in order.expressions:
            if bool(item.args.get("desc")) is not descending:
                continue
            expression = item.this
            if (
                isinstance(expression, exp.Column)
                and expression.name.casefold() in equivalent_names
            ):
                return True
            if isinstance(expression, exp.Literal) and not expression.is_string:
                try:
                    if int(expression.this) in target_positions:
                        return True
                except (TypeError, ValueError):
                    pass
        return False

    @staticmethod
    def _contract_has_filter(
        filters: list[Any],
        field_name: str,
        expected_terms: tuple[str, ...],
    ) -> bool:
        for item in filters:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "").casefold().split(".")[-1]
            if field != field_name.casefold():
                continue
            text = " ".join(
                str(item.get(key) or "")
                for key in ("phrase", "operator", "value")
            )
            if field_name == "trade_date":
                return "max" in text.casefold() or "最大" in text
            if any(term.casefold() in text.casefold() for term in expected_terms):
                return True
        return False

    @staticmethod
    def _has_global_latest_trade_date_filter(statement: exp.Expression) -> bool:
        def is_trade_date(node: exp.Expression | None) -> bool:
            return isinstance(node, exp.Column) and node.name.casefold() == "trade_date"

        def contains_trade_date_max(node: exp.Expression | None) -> bool:
            if node is None:
                return False
            candidates = [node] if isinstance(node, exp.Max) else list(node.find_all(exp.Max))
            return any(
                isinstance(maximum.this, exp.Column)
                and maximum.this.name.casefold() == "trade_date"
                for maximum in candidates
            )

        for equality in statement.find_all(exp.EQ):
            if not SingleDatabaseAgent._is_filter_expression(equality):
                continue
            if (
                is_trade_date(equality.this)
                and contains_trade_date_max(equality.expression)
            ) or (
                is_trade_date(equality.expression)
                and contains_trade_date_max(equality.this)
            ):
                return True
        for membership in statement.find_all(exp.In):
            if (
                SingleDatabaseAgent._is_filter_expression(membership)
                and is_trade_date(membership.this)
                and contains_trade_date_max(membership)
            ):
                return True
        return False

    @staticmethod
    def _has_literal_filter(
        statement: exp.Expression,
        field_name: str,
        expected_value: str,
    ) -> bool:
        def is_field(node: exp.Expression | None) -> bool:
            return isinstance(node, exp.Column) and node.name.casefold() == field_name.casefold()

        def is_value(node: exp.Expression | None) -> bool:
            return isinstance(node, exp.Literal) and str(node.this) == expected_value

        for equality in statement.find_all(exp.EQ):
            if not SingleDatabaseAgent._is_filter_expression(equality):
                continue
            if (
                is_field(equality.this) and is_value(equality.expression)
            ) or (
                is_field(equality.expression) and is_value(equality.this)
            ):
                return True
        for membership in statement.find_all(exp.In):
            if (
                SingleDatabaseAgent._is_filter_expression(membership)
                and is_field(membership.this)
                and any(is_value(item) for item in membership.expressions)
            ):
                return True
        return False

    @staticmethod
    def _is_filter_expression(node: exp.Expression) -> bool:
        parent = node.parent
        while parent is not None:
            if isinstance(parent, (exp.Where, exp.Qualify, exp.Join, exp.Having)):
                return True
            parent = parent.parent
        return False

    @staticmethod
    def _explicit_filter_error(
        decision: dict[str, Any],
        payload: dict[str, Any],
    ) -> str:
        """用户明确写出Schema样例值时，SQL必须使用该值。"""
        if decision.get("action") != "call_tool":
            return ""
        if not str(decision.get("tool_name") or "").startswith("query_"):
            return ""
        sql = str((decision.get("arguments") or {}).get("sql") or "")
        if not sql:
            return "数据库工具调用缺少SQL参数"
        query = str(payload.get("query") or "")
        selected_fields = (
            (payload.get("retrieval") or {}).get("selected_fields") or []
        )
        matched_samples: list[tuple[str, str, str, bool]] = []
        for field in selected_fields:
            field_identity = " ".join(
                str(field.get(key) or "")
                for key in ("field_name", "field_label", "field_type")
            ).casefold()
            if any(
                token in field_identity
                for token in ("date", "time", "month", "year", "日期", "时间", "月份", "年度")
            ):
                continue
            samples = list(field.get("samples") or [])
            if len(samples) > 20:
                continue
            for sample in samples:
                value = str(sample).strip()
                if len(value) < 2:
                    continue
                if isinstance(sample, (int, float)) and not isinstance(sample, bool):
                    query_pattern = rf"(?<![\d.]){re.escape(value)}(?![\d.])"
                    if not re.search(query_pattern, query):
                        continue
                    pattern = rf"(?<![\w.]){re.escape(value)}(?![\w.])"
                else:
                    if value.casefold() not in query.casefold():
                        continue
                    escaped = re.escape(value.replace("'", "''"))
                    pattern = rf"'\s*{escaped}\s*'"
                matched_samples.append(
                    (
                        str(field.get("field_name") or ""),
                        value,
                        pattern,
                        not isinstance(sample, (int, float)) or isinstance(sample, bool),
                    )
                )

        # 同一段文本可能同时命中“侵权”和“侵权搬运”等重叠枚举，
        # 此时只校验信息更完整的最长值，避免把正确SQL误判为缺少短枚举。
        precise_samples: list[tuple[str, str, str, bool]] = []
        for candidate in matched_samples:
            _, value, _, is_text = candidate
            if is_text and any(
                other_is_text
                and len(other_value) > len(value)
                and value.casefold() in other_value.casefold()
                for _, other_value, _, other_is_text in matched_samples
            ):
                continue
            precise_samples.append(candidate)

        missing = [
            f"{field_name}={value}"
            for field_name, value, pattern, _ in precise_samples
            if not re.search(pattern, sql, flags=re.IGNORECASE)
        ]
        if missing:
            return "SQL遗漏用户明确给出的Schema取值：" + "、".join(dict.fromkeys(missing))
        return ""
