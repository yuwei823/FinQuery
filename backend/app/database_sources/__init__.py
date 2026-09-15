from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .short_video_ops import DATABASE_ID as SHORT_VIDEO_OPS_ID
from .short_video_ops import SYNONYMS as SHORT_VIDEO_OPS_SYNONYMS


@dataclass(frozen=True)
class DatabaseSource:
    """一个可由 DATABASE_SWITCHES 启用的本地 CSV 数据库来源。"""

    database_id: str
    folder: Path
    synonyms: dict[str, list[str]]

    @property
    def schema_path(self) -> Path:
        return self.folder / "_schema.json"


def source_registry(database_root: Path) -> dict[str, DatabaseSource]:
    """返回所有受支持的数据源；启用状态由调用方负责筛选。"""
    return {
        SHORT_VIDEO_OPS_ID: DatabaseSource(
            database_id=SHORT_VIDEO_OPS_ID,
            folder=database_root / SHORT_VIDEO_OPS_ID,
            synonyms=SHORT_VIDEO_OPS_SYNONYMS,
        ),
    }


__all__ = ["DatabaseSource", "source_registry"]
