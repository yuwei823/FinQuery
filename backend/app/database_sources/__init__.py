from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .trade_data import DATABASE_ID as TRADE_DATA_ID
from .trade_data import SYNONYMS as TRADE_DATA_SYNONYMS


@dataclass(frozen=True)
class DatabaseSource:
    """一个可由 DATABASE_SWITCHES 启用的本地 CSV 数据库来源。"""

    database_id: str
    folder: Path
    synonyms: dict[str, list[str]]
    data_folder: Path | None = None

    @property
    def schema_path(self) -> Path:
        return self.folder / "_schema.json"

    @property
    def query_folder(self) -> Path:
        return self.data_folder or self.folder


def source_registry(
    database_root: Path,
    curated_data_root: Path | None = None,
) -> dict[str, DatabaseSource]:
    """返回所有受支持的数据源；启用状态由调用方负责筛选。"""
    return {
        TRADE_DATA_ID: DatabaseSource(
            database_id=TRADE_DATA_ID,
            folder=database_root / TRADE_DATA_ID,
            synonyms=TRADE_DATA_SYNONYMS,
            data_folder=(
                curated_data_root / TRADE_DATA_ID
                if curated_data_root is not None
                else database_root / TRADE_DATA_ID
            ),
        ),
    }


__all__ = ["DatabaseSource", "source_registry"]
