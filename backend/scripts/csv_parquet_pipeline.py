from __future__ import annotations

import csv
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb


@dataclass(frozen=True)
class ColumnSpec:
    source: str
    target: str
    kind: str


@dataclass(frozen=True)
class DatasetSpec:
    dataset: str
    database: str
    table: str
    encoding: str
    skip_rows: int
    columns: tuple[ColumnSpec, ...]
    key_fields: tuple[str, ...]
    identity_field: str
    recursive: bool = False
    identity_from_parent: bool = False
    shard_from_parent: bool = False
    allow_extra_columns: bool = False

    @property
    def expected_header(self) -> tuple[str, ...]:
        return tuple(column.source for column in self.columns)

    @property
    def target_header(self) -> tuple[str, ...]:
        return tuple(column.target for column in self.columns)

    @property
    def manifest_name(self) -> str:
        return f"_pipeline_manifest.{self.table}.json"


def _safe_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _header_error(spec: DatasetSpec, header: tuple[str, ...]) -> str | None:
    expected = spec.expected_header
    if not spec.allow_extra_columns and len(header) != len(expected):
        return f"expected {len(expected)} columns, found {len(header)}"
    if len(set(header)) != len(header):
        return "duplicate column names"
    missing = sorted(set(expected) - set(header))
    extra = [] if spec.allow_extra_columns else sorted(set(header) - set(expected))
    if missing or extra:
        return f"missing={missing}, extra={extra}"
    return None


def _read_header(spec: DatasetSpec, path: Path) -> tuple[str, ...]:
    with path.open("r", encoding=spec.encoding, newline="") as handle:
        reader = csv.reader(handle)
        for _ in range(spec.skip_rows):
            next(reader, None)
        return tuple(next(reader, ()))


def _source_files(spec: DatasetSpec, source: Path) -> list[Path]:
    pattern = "**/*.csv" if spec.recursive else "*.csv"
    return sorted(source.glob(pattern))


def _source_key(source_root: Path, path: Path) -> str:
    return path.relative_to(source_root).as_posix()


def _shard_stem(spec: DatasetSpec, path: Path) -> str:
    return path.parent.name if spec.shard_from_parent else path.stem


def _expected_identity(spec: DatasetSpec, path: Path) -> str:
    return path.parent.name if spec.identity_from_parent else path.stem


def _header_is_reordered(spec: DatasetSpec, header: tuple[str, ...]) -> bool:
    if not spec.allow_extra_columns:
        return header != spec.expected_header
    expected = set(spec.expected_header)
    return tuple(column for column in header if column in expected) != spec.expected_header


def inventory(spec: DatasetSpec, source: Path) -> dict[str, Any]:
    if not source.is_dir():
        raise FileNotFoundError(f"source directory does not exist: {source}")
    files = _source_files(spec, source)
    if not files:
        raise ValueError(f"source directory has no CSV files: {source}")

    invalid_headers: list[dict[str, Any]] = []
    reordered_headers: list[str] = []
    shard_sources: dict[str, list[str]] = {}
    total_bytes = 0
    latest_mtime_ns = 0
    for path in files:
        shard_sources.setdefault(_shard_stem(spec, path), []).append(
            _source_key(source, path)
        )
        stat = path.stat()
        total_bytes += stat.st_size
        latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
        header = _read_header(spec, path)
        error = _header_error(spec, header)
        if error:
            invalid_headers.append(
                {
                    "file": _source_key(source, path),
                    "error": error,
                    "column_count": len(header),
                    "columns": list(header),
                }
            )
        elif _header_is_reordered(spec, header):
            reordered_headers.append(_source_key(source, path))

    duplicate_shards = {
        shard: paths for shard, paths in shard_sources.items() if len(paths) > 1
    }
    identity_count = len({_expected_identity(spec, path) for path in files})
    return {
        "dataset": spec.dataset,
        "database": spec.database,
        "table": spec.table,
        "encoding": spec.encoding,
        "file_count": len(files),
        "identity_count": identity_count,
        "total_bytes": total_bytes,
        "latest_mtime_ns": latest_mtime_ns,
        "expected_column_count": len(spec.expected_header),
        "invalid_header_count": len(invalid_headers),
        "invalid_headers": invalid_headers[:100],
        "reordered_header_count": len(reordered_headers),
        "reordered_header_examples": reordered_headers[:100],
        "duplicate_shard_count": len(duplicate_shards),
        "duplicate_shards": dict(list(duplicate_shards.items())[:100]),
    }


def write_inventory(
    spec: DatasetSpec, source: Path, destination: Path
) -> dict[str, Any]:
    result = inventory(spec, source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(destination, result)
    return result


def _projection_sql(spec: DatasetSpec) -> str:
    expressions: list[str] = []
    for column in spec.columns:
        quoted = f'"{column.target}"'
        if column.kind == "text":
            expression = f"NULLIF(TRIM({quoted}), '')::VARCHAR"
        elif column.kind == "date":
            expression = f"CAST(NULLIF({quoted}, '') AS DATE)"
        elif column.kind == "compact_date":
            expression = (
                f"CAST(STRPTIME(NULLIF({quoted}, ''), '%Y%m%d') AS DATE)"
            )
        elif column.kind == "number":
            expression = f"CAST(NULLIF({quoted}, '') AS DOUBLE)"
        elif column.kind == "boolean":
            expression = (
                f"CASE WHEN UPPER(TRIM({quoted})) = 'Y' THEN TRUE "
                f"WHEN NULLIF(TRIM({quoted}), '') IS NULL THEN FALSE "
                f"ELSE CAST({quoted} AS BOOLEAN) END"
            )
        else:
            raise ValueError(f"unknown column kind: {column.kind}")
        expressions.append(f'{expression} AS "{column.target}"')
    return ",\n            ".join(expressions)


def _normalize_csv(spec: DatasetSpec, source: Path, destination: Path) -> int:
    row_count = 0
    with source.open("r", encoding=spec.encoding, newline="") as input_handle:
        for _ in range(spec.skip_rows):
            next(input_handle, None)
        reader = csv.DictReader(input_handle)
        header = tuple(reader.fieldnames or ())
        error = _header_error(spec, header)
        if error:
            raise ValueError(f"{source.name} header mismatch: {error}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as output_handle:
            writer = csv.writer(output_handle)
            writer.writerow(spec.target_header)
            for line_number, row in enumerate(reader, start=spec.skip_rows + 2):
                if None in row:
                    raise ValueError(
                        f"{source.name}:{line_number} has values beyond the header"
                    )
                values = [str(row.get(column.source) or "") for column in spec.columns]
                if not any(value.strip() for value in values):
                    continue
                identity_index = spec.target_header.index(spec.identity_field)
                expected_identity = _expected_identity(spec, source)
                if values[identity_index].strip() != expected_identity:
                    raise ValueError(
                        f"{source.name}:{line_number} identity does not match filename"
                    )
                writer.writerow(values)
                row_count += 1
    if row_count == 0:
        raise ValueError(f"{source.name} has no data rows")
    return row_count


def _convert_file(
    spec: DatasetSpec,
    connection: duckdb.DuckDBPyConnection,
    source: Path,
    staging_dir: Path,
    table_dir: Path,
) -> dict[str, Any]:
    shard_stem = _shard_stem(spec, source)
    normalized_csv = staging_dir / f"{shard_stem}.csv"
    temporary_parquet = staging_dir / f"{shard_stem}.parquet"
    final_parquet = table_dir / f"{shard_stem}.parquet"
    normalized_rows = _normalize_csv(spec, source, normalized_csv)
    try:
        connection.execute(
            f"""
            COPY (
                SELECT {_projection_sql(spec)}
                FROM read_csv(
                    '{_safe_path(normalized_csv)}',
                    header=true,
                    all_varchar=true,
                    strict_mode=true
                )
            ) TO '{_safe_path(temporary_parquet)}'
            (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        key_sql = ", ".join(f'"{field}"' for field in spec.key_fields)
        row_count, null_keys, distinct_keys = connection.execute(
            f"""
            SELECT
                COUNT(*),
                COUNT(*) FILTER (WHERE {' OR '.join(f'"{field}" IS NULL' for field in spec.key_fields)}),
                COUNT(DISTINCT ({key_sql}))
            FROM read_parquet('{_safe_path(temporary_parquet)}')
            """
        ).fetchone()
        if row_count != normalized_rows:
            raise ValueError(
                f"{source.name} row count changed: {normalized_rows} != {row_count}"
            )
        if null_keys or distinct_keys != row_count:
            raise ValueError(f"{source.name} contains null or duplicate keys")
        os.replace(temporary_parquet, final_parquet)
        stat = source.stat()
        return {
            "source_size": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "rows": row_count,
            "parquet": f"{spec.table}/{final_parquet.name}",
        }
    finally:
        normalized_csv.unlink(missing_ok=True)
        temporary_parquet.unlink(missing_ok=True)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _load_manifest(spec: DatasetSpec, path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"database": spec.database, "table": spec.table, "files": {}}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("database") != spec.database or manifest.get("table") != spec.table:
        raise ValueError(f"manifest belongs to another dataset: {path}")
    return manifest


def convert_dataset(
    spec: DatasetSpec,
    source: Path,
    output: Path,
    *,
    force: bool = False,
    workers: int = 1,
    progress: bool = False,
) -> dict[str, Any]:
    report = inventory(spec, source)
    if report["invalid_header_count"]:
        raise ValueError(f"{report['invalid_header_count']} source files have invalid headers")
    if report["duplicate_shard_count"]:
        raise ValueError(
            f"{report['duplicate_shard_count']} shard names map to multiple source files"
        )
    if workers < 1:
        raise ValueError("workers must be greater than zero")

    output.mkdir(parents=True, exist_ok=True)
    table_dir = output / spec.table
    staging_dir = output / f".staging.{spec.table}"
    table_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output / spec.manifest_name
    manifest = _load_manifest(spec, manifest_path)
    records: dict[str, dict[str, Any]] = manifest.setdefault("files", {})
    pending: list[Path] = []
    skipped = 0
    for path in _source_files(spec, source):
        stat = path.stat()
        source_key = _source_key(source, path)
        existing = records.get(source_key)
        final_path = table_dir / f"{_shard_stem(spec, path)}.parquet"
        unchanged = (
            existing
            and existing.get("source_size") == stat.st_size
            and existing.get("source_mtime_ns") == stat.st_mtime_ns
            and final_path.exists()
        )
        if unchanged and not force:
            skipped += 1
        else:
            pending.append(path)

    converted = 0

    def convert_one(path: Path) -> tuple[Path, dict[str, Any]]:
        connection = duckdb.connect(":memory:")
        try:
            return path, _convert_file(spec, connection, path, staging_dir, table_dir)
        finally:
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for path, result in executor.map(convert_one, pending):
                records[_source_key(source, path)] = result
                converted += 1
                if progress:
                    print(f"converted={converted}/{len(pending)} skipped={skipped}", flush=True)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    manifest.update(
        {
            "database": spec.database,
            "table": spec.table,
            "source_encoding": spec.encoding,
            "file_count": len(records),
            "identity_count": report["identity_count"],
            "row_count": sum(int(item.get("rows", 0)) for item in records.values()),
            "converted_this_run": converted,
            "skipped_this_run": skipped,
            "files": records,
        }
    )
    _write_json_atomic(manifest_path, manifest)
    return manifest


def validate_dataset(spec: DatasetSpec, output: Path) -> dict[str, Any]:
    manifest_path = output / spec.manifest_name
    table_dir = output / spec.table
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest does not exist: {manifest_path}")
    parquet_files = sorted(table_dir.glob("*.parquet"))
    if not parquet_files:
        raise ValueError(f"no Parquet shards found: {table_dir}")
    manifest = _load_manifest(spec, manifest_path)
    parquet_glob = _safe_path(table_dir / "*.parquet")
    key_sql = ", ".join(f'"{field}"' for field in spec.key_fields)
    connection = duckdb.connect(":memory:")
    try:
        row_count, identity_count, null_key_count = connection.execute(
            f"""
            SELECT
                COUNT(*),
                COUNT(DISTINCT "{spec.identity_field}"),
                COUNT(*) FILTER (WHERE {' OR '.join(f'"{field}" IS NULL' for field in spec.key_fields)})
            FROM read_parquet('{parquet_glob}', union_by_name=true)
            """
        ).fetchone()
        duplicate_key_groups = connection.execute(
            f"""
            SELECT COUNT(*) FROM (
                SELECT {key_sql}, COUNT(*) AS n
                FROM read_parquet('{parquet_glob}', union_by_name=true)
                GROUP BY {key_sql} HAVING n > 1
            )
            """
        ).fetchone()[0]
        date_field = next(
            (
                column.target
                for column in spec.columns
                if column.kind in {"date", "compact_date"}
            ),
            None,
        )
        min_date = max_date = None
        if date_field:
            min_date, max_date = connection.execute(
                f'SELECT MIN("{date_field}"), MAX("{date_field}") '
                f"FROM read_parquet('{parquet_glob}', union_by_name=true)"
            ).fetchone()
    finally:
        connection.close()

    errors: list[str] = []
    if len(parquet_files) != int(manifest.get("file_count", -1)):
        errors.append("Parquet shard count does not match manifest")
    if row_count != int(manifest.get("row_count", -1)):
        errors.append("Parquet row count does not match manifest")
    expected_identity_count = int(
        manifest.get("identity_count", manifest.get("file_count", -1))
    )
    if identity_count != expected_identity_count:
        errors.append("identity count does not match manifest")
    if null_key_count:
        errors.append(f"{null_key_count} rows have null keys")
    if duplicate_key_groups:
        errors.append(f"{duplicate_key_groups} duplicate key groups")
    return {
        "database": spec.database,
        "table": spec.table,
        "parquet_files": len(parquet_files),
        "row_count": row_count,
        "identity_count": identity_count,
        "min_date": min_date.isoformat() if min_date else None,
        "max_date": max_date.isoformat() if max_date else None,
        "null_key_count": null_key_count,
        "duplicate_key_groups": duplicate_key_groups,
        "errors": errors,
    }


def compact_dataset(spec: DatasetSpec, output: Path) -> dict[str, Any]:
    manifest = _load_manifest(spec, output / spec.manifest_name)
    table_dir = output / spec.table
    parquet_files = sorted(table_dir.glob("*.parquet"))
    if not parquet_files:
        raise ValueError(f"no Parquet shards found: {table_dir}")
    destination = output / f"{spec.table}.parquet"
    temporary = output / f".{spec.table}.compacting.parquet"
    temporary.unlink(missing_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            f"""
            COPY (
                SELECT * FROM read_parquet(
                    '{_safe_path(table_dir / '*.parquet')}', union_by_name=true
                )
            ) TO '{_safe_path(temporary)}'
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)
            """
        )
        row_count = connection.execute(
            f"SELECT COUNT(*) FROM read_parquet('{_safe_path(temporary)}')"
        ).fetchone()[0]
    finally:
        connection.close()
    expected_rows = int(manifest.get("row_count", -1))
    if row_count != expected_rows:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"compaction row count changed: {expected_rows} != {row_count}")
    os.replace(temporary, destination)
    return {
        "database": spec.database,
        "table": spec.table,
        "source_files": len(parquet_files),
        "row_count": row_count,
        "compact_file": destination.name,
        "compact_bytes": destination.stat().st_size,
    }
