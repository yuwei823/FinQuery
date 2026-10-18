from __future__ import annotations

from typing import Annotated, Callable

from pydantic import Field

from ...querying.duckdb_engine import DuckDbEngine
from ...security import AccessScope
from ..schemas import StockEntityMatch, StockEntityResolution


StockName = Annotated[
    str,
    Field(
        description="需要从本地行情数据解析为股票代码的公司名称或股票简称",
        min_length=1,
        max_length=64,
    ),
]


def build_stock_entity_resolver(
    engine: DuckDbEngine,
    access_scope: AccessScope,
) -> Callable[[StockName], StockEntityResolution]:
    """构造只从本地stock_daily解析名称的只读工具。"""

    def resolve_stock_entity(name: StockName) -> StockEntityResolution:
        normalized = name.strip()
        if not normalized:
            return StockEntityResolution(query=name, error="股票名称不能为空")
        exact = normalized.replace("'", "''")
        contains = (
            normalized.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            .replace("'", "''")
        )
        sql = f"""
SELECT symbol, stock_name, MAX(trade_date) AS latest_trade_date
FROM stock_daily
WHERE stock_name = '{exact}'
   OR stock_name LIKE '%{contains}%' ESCAPE '\\'
GROUP BY symbol, stock_name
ORDER BY CASE WHEN stock_name = '{exact}' THEN 0 ELSE 1 END,
         latest_trade_date DESC,
         symbol ASC
LIMIT 10
""".strip()
        execution = engine.execute("trade_data", sql, access_scope)
        if not execution.success:
            return StockEntityResolution(query=normalized, error=execution.error)
        return StockEntityResolution(
            query=normalized,
            matches=[StockEntityMatch.model_validate(row) for row in execution.rows],
        )

    resolve_stock_entity.__name__ = "resolve_stock_entity"
    return resolve_stock_entity
