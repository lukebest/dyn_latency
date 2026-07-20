import math
import unittest

from dynlat.system_model import (
    AFDTeProfile,
    Sys1Config,
    Sys2Config,
    Sys3Config,
    afd_ideal_step_time_us,
    afd_masking_conditions,
    simulate_sys1,
    simulate_sys2,
    simulate_sys3,
)


class SerialModelTests(unittest.TestCase):
    def test_zero_network(self) -> None:
        result = simulate_sys1(
            Sys1Config(
                layers=2,
                batch_size=12,
                ta_us=10.0,
                te_us=20.0,
                dispatch_us=0.0,
                combine_us=0.0,
            )
        )
        self.assertEqual(result.step_time_us, 60.0)
        self.assertEqual(result.per_device_throughput_tokens_s, 200_000.0)

    def test_zero_compute(self) -> None:
        result = simulate_sys1(
            Sys1Config(
                layers=3,
                batch_size=3,
                ta_us=0.0,
                te_us=0.0,
                dispatch_us=2.0,
                combine_us=3.0,
            )
        )
        self.assertEqual(result.step_time_us, 15.0)
        self.assertEqual(result.per_device_throughput_tokens_s, 200_000.0)

    def test_all_zero_has_infinite_nonzero_batch_throughput(self) -> None:
        result = simulate_sys1(
            Sys1Config(
                layers=1,
                batch_size=1,
                ta_us=0.0,
                te_us=0.0,
                dispatch_us=0.0,
                combine_us=0.0,
            )
        )
        self.assertEqual(result.step_time_us, 0.0)
        self.assertTrue(math.isinf(result.per_device_throughput_tokens_s))

    def test_seeded_sampling_is_deterministic(self) -> None:
        config = Sys1Config(layers=5, seed=20260719)
        first = simulate_sys1(config)
        second = simulate_sys1(config)
        other = simulate_sys1(Sys1Config(layers=5, seed=20260720))

        self.assertEqual(first, second)
        self.assertNotEqual(
            [layer.ta_us for layer in first.layer_results],
            [layer.ta_us for layer in other.layer_results],
        )
        for layer in first.layer_results:
            self.assertGreaterEqual(layer.ta_us, 75.0)
            self.assertLessEqual(layer.ta_us, 90.0)
            self.assertGreaterEqual(layer.te_us, 75.0)
            self.assertLessEqual(layer.te_us, 90.0)


class TBOModelTests(unittest.TestCase):
    def test_one_microbatch_exactly_degenerates_to_serial(self) -> None:
        serial = simulate_sys1(
            Sys1Config(
                layers=4,
                batch_size=16,
                dispatch_us=[3.0, 4.0, 5.0, 6.0],
                combine_us=[7.0, 8.0, 9.0, 10.0],
                seed=123,
            )
        )
        tbo = simulate_sys2(
            Sys2Config(
                layers=4,
                microbatches=1,
                batch_size=16,
                dispatch_us=[3.0, 4.0, 5.0, 6.0],
                combine_us=[7.0, 8.0, 9.0, 10.0],
                seed=123,
            )
        )

        self.assertEqual(tbo.step_time_us, serial.step_time_us)
        self.assertEqual(
            tbo.per_device_throughput_tokens_s,
            serial.per_device_throughput_tokens_s,
        )
        self.assertEqual(len(tbo.events), 4 * 4)

    def test_two_resources_overlap_without_self_overlap(self) -> None:
        result = simulate_sys2(
            Sys2Config(
                layers=1,
                microbatches=2,
                batch_size=2,
                ta_us=10.0,
                te_us=10.0,
                dispatch_us=10.0,
                combine_us=10.0,
            )
        )

        self.assertLess(result.step_time_us, 80.0)
        self.assertEqual(result.compute_busy_us, 40.0)
        self.assertEqual(result.communication_busy_us, 40.0)
        self.assertTrue(
            any(
                compute.start_us < communication.end_us
                and communication.start_us < compute.end_us
                for compute in result.events
                if compute.resource == "compute"
                for communication in result.events
                if communication.resource == "communication"
            )
        )
        for resource in ("compute", "communication"):
            events = sorted(
                (event for event in result.events if event.resource == resource),
                key=lambda event: event.start_us,
            )
            for previous, current in zip(events, events[1:]):
                self.assertLessEqual(previous.end_us, current.start_us)

    def test_tbo_sampling_is_deterministic(self) -> None:
        config = Sys2Config(layers=3, microbatches=2, batch_size=8, seed=99)
        self.assertEqual(simulate_sys2(config), simulate_sys2(config))


class AFDModelTests(unittest.TestCase):
    def test_profiles_and_ideal_formula(self) -> None:
        expected_ratios = {
            AFDTeProfile.HIDDEN: 0.7,
            AFDTeProfile.BALANCE: 1.0,
            AFDTeProfile.EXPOSED: 1.3,
        }
        for profile, ratio in expected_ratios.items():
            with self.subTest(profile=profile):
                result = simulate_sys3(
                    Sys3Config(
                        layers=3,
                        microbatches=2,
                        batch_size=16,
                        attention_devices=7,
                        ffn_devices=1,
                        ta_us=80.0,
                        tc_us=10.0,
                        te_profile=profile,
                    )
                )
                expected_te = ratio * 80.0
                expected_step = (
                    80.0
                    + expected_te
                    + 2.0 * 10.0
                    + max(80.0, expected_te) * (2 * 3 - 1)
                )
                self.assertEqual(result.te_us, expected_te)
                self.assertEqual(result.step_time_us, expected_step)
                self.assertEqual(
                    result.step_time_us,
                    afd_ideal_step_time_us(
                        80.0, expected_te, 10.0, layers=3, microbatches=2
                    ),
                )
                expected_per_device = (7 * 16 / 8) * 1_000_000.0 / expected_step
                self.assertAlmostEqual(
                    result.per_device_throughput_tokens_s,
                    expected_per_device,
                )

    def test_masking_boundaries(self) -> None:
        fully_hidden = afd_masking_conditions(80.0, 56.0, 10.0, microbatches=3)
        self.assertTrue(fully_hidden.ffn_not_exposed)
        self.assertTrue(fully_hidden.single_direction_hidden)
        self.assertTrue(fully_hidden.bidirectional_hidden)
        self.assertTrue(fully_hidden.fully_hidden)

        too_few_microbatches = afd_masking_conditions(
            80.0, 56.0, 10.0, microbatches=2
        )
        self.assertFalse(too_few_microbatches.bidirectional_hidden)

        communication_exposed = afd_masking_conditions(
            80.0, 56.0, 80.0, microbatches=4
        )
        self.assertFalse(communication_exposed.single_direction_hidden)
        self.assertFalse(communication_exposed.fully_hidden)

        ffn_exposed = afd_masking_conditions(
            80.0, 104.0, 10.0, microbatches=3
        )
        self.assertFalse(ffn_exposed.ffn_not_exposed)
        self.assertFalse(ffn_exposed.fully_hidden)

    def test_seeded_afd_attention_is_deterministic(self) -> None:
        config = Sys3Config(
            layers=2,
            microbatches=2,
            batch_size=4,
            attention_devices=3,
            ffn_devices=1,
            seed=7,
        )
        self.assertEqual(simulate_sys3(config), simulate_sys3(config))


if __name__ == "__main__":
    unittest.main()
