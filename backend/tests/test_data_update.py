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
            [
                "stock_daily",
                "index_daily",
                "stock_fin_data_xbx",
                "financial_period",
                "stock_financial_daily",
                "stock_etf_trading_data",
            ],
        )
        self.assertEqual(jobs[0].source, Path("D:/raw/stock-trading-data-pro"))
        self.assertEqual(jobs[1].output, Path("D:/curated/trade_data"))
        self.assertEqual(jobs[2].source, Path("D:/raw/stock-fin-data-xbx"))
        self.assertIsNone(jobs[3].source)
        self.assertEqual(jobs[3].steps, ("build", "validate"))
        self.assertEqual(jobs[3].depends_on, ("stock_fin_data_xbx",))
        self.assertIsNone(jobs[4].source)
        self.assertEqual(jobs[4].steps, ("build", "validate"))
        self.assertEqual(jobs[4].depends_on, ("stock_daily", "financial_period"))

    def test_derived_job_runs_without_a_raw_source(self) -> None:
        output = Path(__file__).parent
        job = PipelineJob(
            "derived",
            Path(__file__),
            None,
            output,
            ("build", "validate"),
        )
        calls: list[tuple[str, list[str]]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append((command[2], command[3:]))
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        self.assertTrue(run_updates([job], self.logger, runner))
        self.assertEqual(
            calls,
            [
                ("build", ["--output", str(output)]),
                ("validate", ["--output", str(output)]),
            ],
        )

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

    def test_failed_dependency_skips_derived_job(self) -> None:
        existing_source = Path(__file__).parent
        jobs = [
            PipelineJob("source", Path(__file__), existing_source, existing_source),
            PipelineJob(
                "derived",
                Path(__file__),
                None,
                existing_source,
                ("build", "validate"),
                ("source",),
            ),
        ]
        calls: list[tuple[str, str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append((Path(command[1]).stem, command[2]))
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

        self.assertFalse(run_updates(jobs, self.logger, runner))
        self.assertEqual(calls, [(Path(__file__).stem, "convert")])


if __name__ == "__main__":
    unittest.main()
