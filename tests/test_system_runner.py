import itertools
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_ub_rg_system_experiments as runner


def signature(job):
    return (
        job.scenario,
        job.scheme,
        job.batch,
        job.zipf_s,
        job.ep_size,
        job.layers,
        job.microbatches,
        job.m_attn,
        job.n_ffn,
        job.te_profile,
        job.placement,
    )


class MatrixCoverageTests(unittest.TestCase):
    def test_exact_plan_sizes_and_unique_run_ids(self):
        jobs = runner.build_plan()
        self.assertEqual(len(jobs), 134)
        self.assertEqual(
            {exp: sum(job.exp == exp for job in jobs) for exp in ("sys1", "sys2", "sys3")},
            {"sys1": 48, "sys2": 42, "sys3": 44},
        )
        self.assertEqual(
            {tier: sum(job.tier == tier for job in jobs) for tier in ("main", "controls")},
            {"main": 54, "controls": 80},
        )
        run_ids = [job.run_id for job in jobs]
        self.assertEqual(len(run_ids), len(set(run_ids)))

    def test_sys1_exact_main_and_controls(self):
        jobs = runner.build_plan(exp="sys1")
        main = {signature(job) for job in jobs if job.tier == "main"}
        expected_main = {
            (
                scenario,
                scheme,
                256,
                zipf_s,
                runner.FULL_EP[scenario],
                60,
                1,
                0,
                0,
                "hidden",
                "role_packed",
            )
            for scenario, scheme, zipf_s in itertools.product(
                runner.SCENARIOS, runner.SCHEMES, (0.0, 0.5, 0.9)
            )
        }
        self.assertEqual(main, expected_main)

        controls = {signature(job) for job in jobs if job.tier == "controls"}
        expected_controls = set()
        for scenario, scheme in itertools.product(runner.SCENARIOS, runner.SCHEMES):
            for batch in (16, 64):
                expected_controls.add(
                    (
                        scenario,
                        scheme,
                        batch,
                        0.5,
                        runner.FULL_EP[scenario],
                        60,
                        1,
                        0,
                        0,
                        "hidden",
                        "role_packed",
                    )
                )
            expected_controls.add(
                (
                    scenario,
                    scheme,
                    256,
                    0.5,
                    runner.REDUCED_EP[scenario],
                    60,
                    1,
                    0,
                    0,
                    "hidden",
                    "role_packed",
                )
            )
            for layers in (32, 94):
                expected_controls.add(
                    (
                        scenario,
                        scheme,
                        256,
                        0.5,
                        runner.FULL_EP[scenario],
                        layers,
                        1,
                        0,
                        0,
                        "hidden",
                        "role_packed",
                    )
                )
        self.assertEqual(controls, expected_controls)

    def test_sys2_exact_main_and_controls(self):
        jobs = runner.build_plan(exp="sys2")
        main = {signature(job) for job in jobs if job.tier == "main"}
        expected_main = {
            (
                scenario,
                scheme,
                256,
                zipf_s,
                runner.FULL_EP[scenario],
                60,
                2,
                0,
                0,
                "hidden",
                "role_packed",
            )
            for scenario, scheme, zipf_s in itertools.product(
                runner.SCENARIOS, runner.SCHEMES, (0.0, 0.5, 0.9)
            )
        }
        self.assertEqual(main, expected_main)

        controls = {signature(job) for job in jobs if job.tier == "controls"}
        expected_controls = {
            (
                scenario,
                scheme,
                256,
                zipf_s,
                runner.FULL_EP[scenario],
                60,
                microbatches,
                0,
                0,
                "hidden",
                "role_packed",
            )
            for scenario, scheme, microbatches, zipf_s in itertools.product(
                runner.SCENARIOS, runner.SCHEMES, (1, 4), (0.5, 0.9)
            )
        }
        self.assertEqual(controls, expected_controls)

    def test_sys3_exact_main_and_control_axes(self):
        jobs = runner.build_plan(exp="sys3")
        main = [job for job in jobs if job.tier == "main"]
        self.assertEqual(len(main), 18)
        for job in main:
            expected_ratio = (112, 16) if job.scenario == 1 else (896, 128)
            self.assertEqual((job.m_attn, job.n_ffn), expected_ratio)
            self.assertEqual(job.batch, 256)
            self.assertIn(job.zipf_s, (0.0, 0.5, 1.0))
            self.assertEqual(job.microbatches, 2)
            self.assertEqual(job.te_profile, "hidden")
            self.assertEqual(
                job.placement,
                "plane_striped" if job.scenario == 3 else "role_packed",
            )

        controls = [job for job in jobs if job.tier == "controls"]
        self.assertEqual(len(controls), 26)
        for scenario, scheme in itertools.product(runner.SCENARIOS, runner.SCHEMES):
            points = [
                job
                for job in controls
                if job.scenario == scenario and job.scheme == scheme
            ]
            one_to_one = runner._afd_ratio(scenario, "1:1")
            thirty_one = runner._afd_ratio(scenario, "31:1")
            seven_one = runner._afd_ratio(scenario, "7:1")
            self.assertTrue(
                any((job.m_attn, job.n_ffn) == one_to_one for job in points)
            )
            self.assertTrue(
                any(
                    (job.m_attn, job.n_ffn) == thirty_one
                    and job.te_profile == "exposed"
                    for job in points
                )
            )
            self.assertEqual(
                {
                    job.microbatches
                    for job in points
                    if (job.m_attn, job.n_ffn) == seven_one
                },
                {1, 2, 4} if scenario == 3 else {1, 4},
            )
            if scenario == 3:
                self.assertTrue(
                    any(
                        (job.m_attn, job.n_ffn) == seven_one
                        and job.microbatches == 2
                        and job.placement == "role_packed"
                        for job in points
                    )
                )

    def test_filters_preserve_requested_slice(self):
        jobs = runner.build_plan(tier="controls", exp="sys2", scenario=2)
        self.assertEqual(len(jobs), 8)
        self.assertTrue(
            all(
                job.tier == "controls" and job.exp == "sys2" and job.scenario == 2
                for job in jobs
            )
        )


class PacketPlanTests(unittest.TestCase):
    def test_find_binary_prefers_release_over_debug(self):
        with tempfile.TemporaryDirectory() as temporary:
            ns3 = Path(temporary)
            build = ns3 / "build" / "scratch"
            build.mkdir(parents=True)
            release = build / "ns3.44-ub_rg-packet-experiment"
            debug = build / "ns3.44-ub_rg-packet-experiment-debug"
            release.touch()
            debug.touch()
            with mock.patch.object(runner, "NS3", ns3):
                self.assertEqual(runner.find_binary(), release.resolve())

    def test_network_keys_use_actual_microbatch_batch(self):
        for job in runner.build_plan():
            expected = job.batch if job.exp == "sys1" else job.batch // job.microbatches
            self.assertEqual(job.mb_batch, expected)
            for key in job.network_keys:
                self.assertEqual(key.batch, expected)
                self.assertIn(f"--batch={expected}", key.command("/tmp/packet"))

    def test_every_job_has_two_packet_modes(self):
        expected = {
            "sys1": {"dispatch", "combine"},
            "sys2": {"dispatch", "combine"},
            "sys3": {"afd_m2n", "afd_n2m"},
        }
        for job in runner.build_plan():
            self.assertEqual({key.mode for key in job.network_keys}, expected[job.exp])

    def test_runner_exposes_no_engine_selection_path(self):
        parser = runner.make_parser()
        self.assertNotIn("engine", {action.dest for action in parser._actions})

    def test_non_packet_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary = Path(temporary) / "summary.json"
            summary.write_text(
                json.dumps({"engine": "not-packet", "cct_us": 1.0}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "not a packet-engine summary"):
                runner._load_packet_summary(summary)

    def test_afd_tc_uses_direction_cct_not_token_p99(self):
        with tempfile.TemporaryDirectory() as temporary:
            results = Path(temporary) / "results"
            network = results / "network"
            job = runner.SystemJob(
                exp="sys3",
                tier="main",
                scenario=1,
                scheme="ub_rg",
                batch=16,
                zipf_s=0.5,
                ep_size=16,
                microbatches=2,
                m_attn=12,
                n_ffn=4,
            )
            with (
                mock.patch.object(runner, "RESULTS_ROOT", results),
                mock.patch.object(runner, "NETWORK_ROOT", network),
            ):
                first, second = job.network_keys
                for key, cct, p99 in ((first, 20.0, 2.0), (second, 30.0, 3.0)):
                    key.summary_path.parent.mkdir(parents=True, exist_ok=True)
                    key.summary_path.write_text(
                        json.dumps(
                            {
                                "engine": "packet",
                                "cct_us": cct,
                                "latency_all": {"p99_us": p99},
                            }
                        ),
                        encoding="utf-8",
                    )
                runner.synthesize_system_job(job, force=True)
                summary = json.loads(job.summary_path.read_text(encoding="utf-8"))
                self.assertEqual(summary["network_inputs"]["tc_us"], 30.0)
                self.assertEqual(
                    summary["network_inputs"]["tc_definition"],
                    "max(m2n_cct_us,n2m_cct_us)",
                )

    def test_network_plan_is_deduplicated_and_stable(self):
        jobs = runner.build_plan()
        keys = runner.network_plan(jobs)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(keys, runner.network_plan(reversed(jobs)))


if __name__ == "__main__":
    unittest.main()
