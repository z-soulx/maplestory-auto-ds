"""Controlled-clock latency tests; no screen capture or real key input."""
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from src.engine.MonsterDetector import MonsterDetector
from src.input.GameWindowCapturor import GameWindowCapturor
from src.input.KeyBoardController import KeyBoardController
from src.launcher_settings import ROOT, load_settings
from src.utils.latency import summarize, recording_summary


class FakeClock:
    def __init__(self, value=100):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds, result=None):
        self.value += seconds
        return result


class CaptureTimingTests(unittest.TestCase):
    def test_timestamps_and_sequence_belong_to_exact_returned_frame(self):
        clock = FakeClock()
        cfg = {"game_window": {"title_bar_height": 0}}
        with patch("src.input.GameWindowCapturor.load_image", return_value=np.zeros((4, 6, 3), np.uint8)):
            c = GameWindowCapturor(cfg, test_image_path="offline.png")
        c.frame_metadata = {"source": "live", "sequence": 0}
        c.region = dict(left=0, top=0, width=6, height=4)
        c.capture = Mock()
        c.capture.grab.side_effect = lambda region: clock.advance(.012, np.zeros((4, 6, 4), np.uint8))
        with patch("src.input.GameWindowCapturor.time.perf_counter", clock):
            c.capture_frame()
            clock.value = 100.050
            image, first = c.get_frame_with_metadata()
            self.assertEqual(image.shape, (4, 6, 3))
            self.assertEqual(first["sequence"], 1)
            self.assertAlmostEqual(first["capture_ms"], 12)
            self.assertAlmostEqual((first["read_monotonic"] - first["capture_end_monotonic"]) * 1000, 38)
            c.capture_frame()
            _, second = c.get_frame_with_metadata()
            self.assertEqual(second["sequence"], 2)
            self.assertAlmostEqual(second["capture_interval_ms"], 50)
            self.assertEqual(first["sequence"], 1)
            c.capture.grab.side_effect = OSError("mock capture failed")
            c.capture_frame()
            _, failed = c.get_frame_with_metadata()
            self.assertEqual(failed["sequence"], 2)
            self.assertEqual(failed["capture_failures"], 1)

    def test_static_image_has_no_live_capture_timestamp(self):
        with patch("src.input.GameWindowCapturor.load_image", return_value=np.zeros((4, 6, 3), np.uint8)):
            c = GameWindowCapturor({"game_window": {}}, test_image_path="offline.png")
        _, meta = c.get_frame_with_metadata()
        self.assertEqual(meta["source"], "offline")
        self.assertNotIn("capture_start_monotonic", meta)


class PipelineTimingTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_settings(ROOT / "config" / "no-saved-settings.yaml")
        self.cfg["disable_viz"] = True
        self.cfg["bot"].update(mode="hunt", enable_route=False)
        self.cfg["player_identity"]["enable"] = False
        self.cfg["stuck_recovery"] = {"enable": False}

    def test_stage_timings_and_repeated_frames_use_capture_clock(self):
        clock = FakeClock(100.050)
        recorder = Mock()
        recorder.decision.return_value = 17
        d = MonsterDetector(self.cfg, recorder=recorder)
        d.loc_player = (160, 120)
        d._kb = Mock(is_enable=True, _had_focus=True)
        sequence = [7]
        def frame():
            d._capture_metadata = dict(source="live", sequence=sequence[0],
                                       capture_start_monotonic=100., capture_end_monotonic=100.010,
                                       capture_ms=10., capture_interval_ms=33., read_monotonic=clock())
            return clock.advance(.005, np.zeros((240, 320, 3), np.uint8))
        d.get_img_frame = frame
        d._detect_minimap = lambda: clock.advance(.007)
        d._detect_player_by_title = lambda: clock.advance(.020)
        d.get_monsters_in_range = lambda *args: clock.advance(.030, [])
        with patch("src.engine.MonsterDetector.time.perf_counter", clock):
            d.run_once()
            data = recorder.decision.call_args.kwargs
            timing = data["timings_ms"]
            for key, expected in dict(capture_ms=10, frame_wait_ms=40, get_frame_ms=5,
                                       preprocess_ms=7, identity_ms=20, monster_ms=30,
                                       analysis_ms=57, frame_age_at_decision_ms=102,
                                       frame_to_decision_ms=112).items():
                self.assertAlmostEqual(timing[key], expected, places=2, msg=key)
            self.assertFalse(data["capture"]["reused_frame"])
            d.run_once()
            self.assertTrue(recorder.decision.call_args.kwargs["capture"]["reused_frame"])
            sequence[0] = 10
            d.run_once()
            self.assertEqual(recorder.decision.call_args.kwargs["capture"]["skipped_frames"], 2)

    def test_attack_latency_keeps_send_lock_wait_separate_from_key_duration(self):
        clock = FakeClock(102.)
        recorder = Mock()
        recorder.elapsed_ms.return_value = 2000.
        with patch("src.input.KeyBoardController.threading.Thread.start"):
            kb = KeyBoardController(self.cfg, recorder=recorder)
        class DelayedLock:
            def __enter__(self):
                clock.advance(.025)
            def __exit__(self, *args):
                pass
        kb._send_lock = DelayedLock()
        with patch("src.input.KeyBoardController.time.perf_counter", clock):
            kb.set_command("none none attack", decision_id=8,
                           timing_origin={"capture_start_monotonic": 100.,
                                          "capture_end_monotonic": 100.01,
                                          "decision_ready_monotonic": 101.})
            with patch("src.input.KeyBoardController.press_key", side_effect=lambda *args: clock.advance(.050, True)):
                kb._apply_action()
        output = next(call.kwargs for call in recorder.event.call_args_list if call.args[0] == "attack_output")
        t = output["latency_ms"]
        self.assertEqual(output["decision_id"], 8)
        self.assertEqual(output["request_elapsed_ms"], 2000.)
        self.assertAlmostEqual(output["start_elapsed_ms"], 2025.)
        self.assertAlmostEqual(t["send_lock_wait_ms"], 25)
        self.assertAlmostEqual(t["send_ms"], 50)
        self.assertAlmostEqual(t["frame_to_send_ms"], 2025)
        self.assertAlmostEqual(t["frame_to_send_complete_ms"], 2075)
        self.assertAlmostEqual(t["command_to_send_ms"], 25)
        self.assertAlmostEqual(t["decision_to_send_ms"], 1025)

    def test_dispatch_wait_is_measured_before_lock_acquisition(self):
        clock = FakeClock(100.)
        recorder = Mock()
        recorder.elapsed_ms.return_value = 0.
        with patch("src.input.KeyBoardController.threading.Thread.start"):
            kb = KeyBoardController(self.cfg, recorder=recorder)
        class DelayedLock:
            def __enter__(self):
                clock.advance(.040)
            def __exit__(self, *args):
                pass
        kb._command_lock = DelayedLock()
        with patch("src.input.KeyBoardController.time.perf_counter", clock):
            kb.set_command("none none attack", decision_id=5,
                           timing_origin={"decision_ready_monotonic": 99.9})
        fields = recorder.event.call_args.kwargs["latency_ms"]
        self.assertAlmostEqual(fields["dispatch_lock_wait_ms"], 40)
        self.assertAlmostEqual(fields["decision_to_command_ms"], 140)

    def test_summary_handles_missing_offline_and_old_session_metrics(self):
        events = [{"event": "decision", "timings_ms": {"analysis_ms": 10, "capture_ms": None}},
                  {"event": "decision", "timings_ms": {"analysis_ms": 30}},
                  {"event": "attack_output", "latency_ms": {"send_ms": 50}},
                  {"event": "key_output", "latency_ms": {"send_ms": 50}},
                  {"event": "decision"}]
        summary = recording_summary(events)
        analysis = summary["metrics"]["analysis_ms"]
        self.assertEqual(analysis, dict(count=2, mean=20, p50=20, p95=29, max=30))
        self.assertNotIn("capture_ms", summary["metrics"])
        self.assertEqual(summary["metrics"]["send_ms"]["count"], 1)
        self.assertEqual(summarize([]), {})


if __name__ == "__main__":
    unittest.main()
