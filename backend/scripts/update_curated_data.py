from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Callable, Iterable, Sequence


BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = Path(__file__).with_name("data_update_jobs.json")
DEFAULT_LOG_DIR = BACKEND_DIR / "logs"


@dataclass(frozen=True)
class PipelineJob:
    name: str
    script: Path
    source: Path
    output: Path


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _configured_root(
    explicit: Path | None,
    name: str,
    env_values: dict[str, str],
    fallback: str,
) -> Path:
    raw = explicit or os.getenv(name) or env_values.get(name) or fallback
    return Path(raw).expanduser().resolve()


def load_jobs(config_path: Path, raw_root: Path, curated_root: Path) -> list[PipelineJob]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    jobs: list[PipelineJob] = []
    names: set[str] = set()
    for item in payload.get("jobs", []):
        name = str(item["name"]).strip()
        if not name or name in names:
            raise ValueError(f"数据更新任务名称为空或重复：{name!r}")
        script = (BACKEND_DIR / str(item["script"])).resolve()
        if BACKEND_DIR not in script.parents or not script.is_file():
            raise ValueError(f"任务 {name} 的脚本不存在或不在 backend 目录内：{script}")
        jobs.append(
            PipelineJob(
                name=name,
                script=script,
                source=raw_root / str(item["source_subdir"]),
                output=curated_root / str(item["database"]),
            )
        )
        names.add(name)
    if not jobs:
        raise ValueError("数据更新配置至少需要包含一个任务")
    return jobs


def configure_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("finquery.data_update")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = TimedRotatingFileHandler(
        log_dir / "curated-data-update.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=BACKEND_DIR,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _run_step(
    job: PipelineJob,
    step: str,
    logger: logging.Logger,
    runner: CommandRunner,
) -> bool:
    command = [sys.executable, str(job.script), step]
    if step == "convert":
        command.extend(("--source", str(job.source), "--output", str(job.output)))
    else:
        command.extend(("--output", str(job.output)))
    logger.info("task=%s step=%s started", job.name, step)
    result = runner(command)
    if result.stdout.strip():
        for line in result.stdout.rstrip().splitlines():
            logger.info("task=%s step=%s output=%s", job.name, step, line)
    if result.stderr.strip():
        for line in result.stderr.rstrip().splitlines():
            logger.error("task=%s step=%s stderr=%s", job.name, step, line)
    if result.returncode != 0:
        logger.error(
            "task=%s step=%s failed exit_code=%s",
            job.name,
            step,
            result.returncode,
        )
        return False
    logger.info("task=%s step=%s completed", job.name, step)
    return True


def run_updates(
    jobs: Iterable[PipelineJob],
    logger: logging.Logger,
    runner: CommandRunner = _default_runner,
) -> bool:
    succeeded = True
    for job in jobs:
        logger.info("task=%s update_started source=%s output=%s", job.name, job.source, job.output)
        if not job.source.is_dir():
            logger.error("task=%s source_directory_missing path=%s", job.name, job.source)
            succeeded = False
            continue
        for step in ("convert", "validate", "compact"):
            if not _run_step(job, step, logger, runner):
                succeeded = False
                break
        else:
            logger.info("task=%s update_completed", job.name)
    return succeeded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="增量转换、验证并压实 FinQuery 的全部已注册行情数据源"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-file", type=Path, default=BACKEND_DIR / ".env")
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--curated-root", type=Path)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = configure_logging(args.log_dir.resolve())
    logger.info("daily_data_update_started")
    try:
        env_values = _read_env_file(args.env_file.resolve())
        raw_root = _configured_root(
            args.raw_root, "TRADE_DATA_ROOT", env_values, "D:/trade_data"
        )
        curated_root = _configured_root(
            args.curated_root,
            "CURATED_DATA_ROOT",
            env_values,
            "D:/trade_data_curated",
        )
        jobs = load_jobs(args.config.resolve(), raw_root, curated_root)
        success = run_updates(jobs, logger)
    except Exception:
        logger.exception("daily_data_update_failed")
        return 1
    if not success:
        logger.error("daily_data_update_finished_with_errors")
        return 1
    logger.info("daily_data_update_completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
