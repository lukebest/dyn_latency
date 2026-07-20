import csv
import json
import tempfile
import unittest
from pathlib import Path

from analyze_ub_rg_system_experiments import analyze


class SystemAnalyzerTests(unittest.TestCase):
    def _write_json(self, path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_packet_inputs_generate_required_report_and_figures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results" / "ub_rg_system_packet"
            docs = root / "docs"

            self._write_json(
                results / "sys1" / "run-a" / "summary.json",
                {
                    "engine": "packet",
                    "experiment": "sys1",
                    "job": {
                        "scenario": 1,
                        "scheme": "ub_rg",
                        "batch": 64,
                        "zipf_s": 0.5,
                        "ep_size": 128,
                        "layers": 60,
                    },
                    "model": {
                        "step_time_us": 12_000.0,
                        "per_device_throughput_tokens_s": 5_333.333,
                    },
                    "step_time_us": 12_000.0,
                    "per_device_throughput_tokens_s": 5_333.333,
                    "network_inputs": {
                        "dispatch_cct_us": 18.0,
                        "combine_cct_us": 20.0,
                    },
                    "network_runs": [
                        {"summary": "packet/dispatch/summary.json"},
                        {"summary": "packet/combine/summary.json"},
                    ],
                },
            )
            self._write_json(
                results / "sys2" / "run-b" / "summary.json",
                {
                    "engine": "packet",
                    "experiment": "sys2",
                    "job": {
                        "scenario": 1,
                        "scheme": "ub_rg",
                        "batch": 64,
                        "zipf_s": 0.5,
                        "ep_size": 128,
                        "layers": 60,
                        "microbatches": 2,
                    },
                    "model": {
                        "step_time_us": 8_000.0,
                        "per_device_throughput_tokens_s": 8_000.0,
                        "events": [
                            {
                                "resource": "compute",
                                "start_us": 0.0,
                                "end_us": 10.0,
                            },
                            {
                                "resource": "communication",
                                "start_us": 5.0,
                                "end_us": 15.0,
                            },
                        ],
                    },
                    "step_time_us": 8_000.0,
                    "per_device_throughput_tokens_s": 8_000.0,
                },
            )
            self._write_json(
                results / "sys3" / "run-c" / "summary.json",
                {
                    "engine": "packet",
                    "network_engine": "packet",
                    "experiment": "sys3",
                    "job": {
                        "scenario": 3,
                        "scheme": "ub_rg",
                        "batch": 64,
                        "zipf_s": 0.5,
                        "ep_size": 128,
                        "layers": 60,
                        "microbatches": 2,
                        "m_attn": 112,
                        "n_ffn": 16,
                        "placement": "plane_striped",
                        "te_profile": "hidden",
                    },
                    "model": {
                        "tc_us": 21.5,
                        "step_time_us": 10_000.0,
                        "per_device_throughput_tokens_s": 5_600.0,
                        "masking": {"fully_hidden": True},
                    },
                },
            )
            self._write_json(
                results / "ledger.json",
                {
                    "packet_only": True,
                    "network_runs": [
                        {
                            "run_id": "failed-run",
                            "status": "failed",
                            "error": "packet simulation timeout",
                        },
                    ],
                    "system_runs": [
                        {
                            "run_id": "skipped-run",
                            "experiment": "sys3",
                            "status": "skipped",
                            "reason": "already complete",
                        },
                        {
                            "run_id": "clipped-run",
                            "experiment": "sys1",
                            "status": "clipped",
                            "reason": "matrix budget",
                        },
                    ],
                },
            )

            outputs = analyze(
                results,
                docs / "UB_RG系统实验0719报告.md",
                docs / "ub_rg_system_figures",
            )

            report = outputs.report_md.read_text(encoding="utf-8")
            for heading in (
                "方法与参数矩阵",
                "逐包证据来源与 packet 门禁",
                "Sys1：step 与 throughput",
                "Sys2：m、speedup 与掩盖",
                "Sys3：M:N、placement、Tc、mask 与 throughput",
                "跨实验锚点",
                "失败、跳过与裁剪可见性",
                "B>=1024 未纳入",
                "复现命令",
            ):
                self.assertIn(heading, report)
            self.assertIn("packet simulation timeout", report)
            self.assertIn("skipped-run", report)
            self.assertIn("clipped-run", report)
            self.assertIn("packet/dispatch/summary.json", report)
            self.assertIn("speedup", report)

            figures = sorted(outputs.figures_dir.glob("*.svg"))
            self.assertEqual(
                [path.name for path in figures],
                [
                    "cross_experiment_compare.svg",
                    "sys1_step_throughput_vs_zipf.svg",
                    "sys2_speedup_vs_m.svg",
                    "sys3_tc_throughput.svg",
                ],
            )
            html = outputs.report_html.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", html)
            self.assertIn("sys3_tc_throughput.svg", html)
            self.assertIn("<svg", html)
            self.assertIn("class='fig'", html)

            with outputs.csv_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 3)
            self.assertEqual({row["engine"] for row in rows}, {"packet"})
            sys2 = next(row for row in rows if row["experiment"] == "sys2")
            self.assertEqual(float(sys2["speedup"]), 1.5)
            self.assertEqual(float(sys2["mask_value"]), 0.5)

    def test_behavioral_summary_is_rejected_before_writing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            self._write_json(
                results / "sys1" / "behavioral" / "summary.json",
                {
                    "engine": "behavioral",
                    "experiment": "sys1",
                    "step_time_us": 1.0,
                },
            )
            report = root / "docs" / "report.md"
            figures = root / "docs" / "figures"

            with self.assertRaisesRegex(ValueError, "non-packet input rejected"):
                analyze(results, report, figures)

            self.assertFalse(report.exists())
            self.assertFalse(figures.exists())
            self.assertFalse((results / "all_summaries.csv").exists())

    def test_missing_experiment_data_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            self._write_json(
                results / "ledger.json", {"packet_only": True, "system_runs": []}
            )

            outputs = analyze(
                results,
                root / "docs" / "report.md",
                root / "docs" / "figures",
            )
            report = outputs.report_md.read_text(encoding="utf-8")
            self.assertIn("数据缺失", report)
            self.assertIn("没有可接受的逐包 summary", report)
            self.assertEqual(outputs.summary_count, 0)


if __name__ == "__main__":
    unittest.main()
