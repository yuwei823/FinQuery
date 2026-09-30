from __future__ import annotations

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from ..database import DEFAULT_DATABASE, SCHEMA, physical_table_name
from ..querying.duckdb_engine import DuckDbEngine
from ..security import AccessController, AccessScope
from .tools import (
    build_area_chart,
    build_bar_chart,
    build_candlestick_chart,
    build_database_query_tool,
    build_heatmap,
    build_line_chart,
    build_pie_chart,
    build_scatter_chart,
    current_datetime,
    resolve_date_range,
)


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_local_mcp_server(
    engine: DuckDbEngine | None = None,
    access_scope: AccessScope | None = None,
) -> MCPServer:
    """创建与FastAPI运行在同一进程中的MCP服务。"""
    database_engine = engine or DuckDbEngine()
    scope = access_scope or AccessController().resolve(None)
    server = MCPServer(
        name="finquery-local-tools",
        title="FinQuery本地工具服务",
        description="提供本地数据库只读查询和基础时间计算工具。",
        instructions="调用数据库工具前先根据Schema图生成一条只读DuckDB SQL。",
    )

    server.tool(
        name="current_datetime",
        title="获取当前日期时间",
        description="获取Asia/Shanghai或UTC时区的当前日期与时间。",
        annotations=READ_ONLY,
    )(current_datetime)
    server.tool(
        name="resolve_date_range",
        title="解析相对日期范围",
        description="将今天、昨天、本周、上周、本月、上月或今年转换为明确起止日期。",
        annotations=READ_ONLY,
    )(resolve_date_range)
    server.tool(
        name="build_bar_chart",
        title="生成柱状图配置",
        description=(
            "基于一张已有查询结果生成前端柱状图配置。"
            "适合比较不同类别的数值，不读取数据库，也不生成模拟数据。"
        ),
        annotations=READ_ONLY,
    )(build_bar_chart)
    server.tool(
        name="build_pie_chart",
        title="生成饼图配置",
        description=(
            "基于一张已有查询结果生成前端饼图配置。"
            "只适合类别较少的占比分析，不读取数据库，也不生成模拟数据。"
        ),
        annotations=READ_ONLY,
    )(build_pie_chart)
    server.tool(
        name="build_line_chart",
        title="生成折线图配置",
        description=(
            "基于一张已有查询结果生成前端折线图配置。"
            "适合指标随日期等有序序列的变化趋势，不读取数据库，也不生成模拟数据。"
        ),
        annotations=READ_ONLY,
    )(build_line_chart)
    server.tool(
        name="build_area_chart",
        title="生成面积图配置",
        description=(
            "基于一张已有查询结果生成前端面积图配置。"
            "适合强调单序列总量随有序序列的变化，不读取数据库，也不生成模拟数据。"
        ),
        annotations=READ_ONLY,
    )(build_area_chart)
    server.tool(
        name="build_scatter_chart",
        title="生成散点图配置",
        description=(
            "基于一张已有查询结果生成前端散点图配置。"
            "适合观察两个数值维度之间的关系，不读取数据库，也不生成模拟数据。"
        ),
        annotations=READ_ONLY,
    )(build_scatter_chart)
    server.tool(
        name="build_heatmap",
        title="生成热力图配置",
        description=(
            "基于一张已有查询结果生成前端热力图配置。"
            "适合展示两个离散维度交叉后的数值大小，不读取数据库，也不生成模拟数据。"
        ),
        annotations=READ_ONLY,
    )(build_heatmap)
    server.tool(
        name="build_candlestick_chart",
        title="生成K线图配置",
        description=(
            "基于一张已有查询结果生成前端K线图配置。"
            "适合展示OHLC四值行情，不读取数据库，也不生成模拟数据。"
        ),
        annotations=READ_ONLY,
    )(build_candlestick_chart)

    databases = sorted({str(table.get("database") or DEFAULT_DATABASE) for table in SCHEMA})
    for database in databases:
        if not scope.allows_database(database):
            continue
        tables = [
            physical_table_name(table)
            for table in SCHEMA
            if table.get("database") == database
            and scope.allows_table(database, table["id"])
        ]
        handler = build_database_query_tool(database, database_engine, scope)
        server.tool(
            name=f"query_{database}",
            title=f"查询数据库 {database}",
            description=(
                f"在数据库{database}中执行一条只读DuckDB SQL。"
                f"可用表：{', '.join(tables)}。每次调用最多返回200行。"
            ),
            annotations=READ_ONLY,
        )(handler)
    return server
