from __future__ import annotations

import logging
import subprocess
import unittest
from pathlib import Path

from scripts.update_curated_data import PipelineJob, load_jobs, run_updates


class DataUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger(f"test.data_update.{id(self)}")
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())

    def test_default_config_loads_all_registered_sources(self) -> None:
        backend_dir = Path(__file__).resolve().parent.parent
        jobs = load_jobs(
            backend_dir / "scripts" / "data_update_jobs.json",
            Path("D:/raw"),
            Path("D:/curated"),
        )
        self.assertEqual(
            [job.name for job in jobs],
            ["stock_daily", "index_daily", "stock_fin_data_xbx"],
        )
        self.assertEqual(jobs[0].source, Path("D:/raw/stock-trading-data-pro"))
        self.assertEqual(jobs[1].output, Path("D:/curated/trade_data"))
        self.assertEqual(jobs[2].source, Path("D:/raw/stock-fin-data-xbx"))

    def test_failed_validation_skips_compact_but_continues_next_job(self) -> None:
        existing_source = Path(__file__).parent
        jobs = [
            PipelineJob("first", existing_source / "first.py", existing_source, existing_source),
            PipelineJob("second", existing_source / "second.py", existing_source, existing_source),
        ]
        calls: list[tuple[str, str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            job = Path(command[1]).stem
            step = command[2]
            calls.append((job, step))
            return subprocess.CompletedProcess(
                command,
                1 if job == "first" and step == "validate" else 0,
                stdout="",
                stderr="validation failed" if step == "validate" else "",
            )

        self.assertFalse(run_updates(jobs, self.logger, runner))
        self.assertEqual(
            calls,
            [
                ("first", "convert"),
                ("first", "validate"),
                ("second", "convert"),
                ("second", "validate"),
                ("second", "compact"),
            ],
        )

    def test_missing_source_is_reported_without_running_commands(self) -> None:
        job = PipelineJob(
            "missing",
            Path(__file__),
            Path("Z:/definitely-missing-finquery-source"),
            Path("D:/curated"),
        )
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        self.assertFalse(run_updates([job], self.logger, runner))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
