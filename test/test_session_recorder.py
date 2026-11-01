"""Offline diagnostic recording tests. Every keyboard send is mocked."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from src.engine.MonsterDetector import MonsterDetector
from src.input.KeyBoardController import KeyBoardController
from src.launcher_settings import ROOT, load_settings, build_settings, save_settings
from src.utils.session_recorder import SessionRecorder
from test.test_launcher import valid_form


class SessionRecorderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "screenshot")
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_settings(ROOT / "config" / "no-saved-settings.yaml")
        self.cfg["recording"] = dict(enable=True, directory=self.tmp.name, fps=30,
                                     max_seconds=600, max_mb=5)
        self.image = np.zeros((240, 320, 3), dtype=np.uint8)

    def recorder(self):
        r = SessionRecorder.from_config(self.cfg)
        self.assertIsNotNone(r)
        self.addCleanup(r.close)
        return r

    def events(self, r):
        return [json.loads(line) for line in (r.directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]

    def keyboard(self, r):
        with patch("src.input.KeyBoardController.threading.Thread.start"):
            return KeyBoardController(self.cfg, recorder=r)

    def detector(self, r):
        self.cfg["disable_viz"] = True
        self.cfg["bot"].update(mode="hunt", enable_route=False)
        self.cfg["player_identity"]["enable"] = False
        self.cfg["stuck_recovery"] = {"enable": False}
        self.cfg["monster_detect"]["detection_interval"] = 1
        d = MonsterDetector(self.cfg, recorder=r)
        d.loc_player = (160, 120)
        d.get_img_frame = Mock(return_value=self.image)
        d._detect_minimap = Mock(return_value=None)
        d._detect_player_by_title = Mock()
        d.get_monsters_in_range = Mock(return_value=[
            {"name": "hou_zi", "position": (190, 70), "size": (50, 40), "score": np.float32(.02)}])
        d._kb = self.keyboard(r)
        return d

    def test_disabled_creates_no_session(self):
        self.cfg["recording"]["enable"] = False
        self.assertIsNone(SessionRecorder.from_config(self.cfg))
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_frames_snapshot_and_offline_replay_are_readable(self):
        r = self.recorder()
        did = r.decision(self.image, frame=1, command="none none attack", score=np.float32(.1),
                         missing=float("inf"), timings_ms={"analysis_ms": 42.5, "capture_ms": None})
        self.image[:] = 255  # Producer may reuse/mutate its frame immediately.
        r.close()
        events = self.events(r)
        saved = next(e for e in events if e["event"] == "frame_saved")
        self.assertEqual(saved["decision_id"], did)
        img = cv2.imread(str(r.directory / saved["path"]))
        self.assertEqual(img.shape, self.image.shape)
        self.assertLess(img.mean(), 1)
        self.assertIsNone(next(e for e in events if e["id"] == did)["missing"])
        payload = (r.directory / "data.js").read_text(encoding="utf-8")
        self.assertEqual(json.loads(payload.removeprefix("window.RECORDING=").removesuffix(";")), events)
        self.assertEqual(json.loads((r.directory / "config.json").read_text(encoding="utf-8"))["key"], self.cfg["key"])
        self.assertTrue((r.directory / "replay.html").is_file())
        summary = json.loads((r.directory / "latency_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["metrics"]["analysis_ms"]["p95"], 42.5)
        self.assertNotIn("capture_ms", summary["metrics"])
        r.close()  # Idempotent.

    def test_detection_and_actual_attack_are_joined_even_if_command_changes_during_send(self):
        r = self.recorder()
        d = self.detector(r)
        d.run_once()
        did = d._kb._decision_id
        def fake_send(*args):
            d._kb.set_command("none none none", decision_id=999)
            return False
        with patch("src.input.KeyBoardController.press_key", side_effect=fake_send) as send:
            d._kb._apply_action()
        send.assert_called_once()
        r.close()
        output = next(e for e in self.events(r) if e["event"] == "attack_output")
        self.assertEqual((output["decision_id"], output["action"], output["result"]), (did, "attack", "failed"))
        decision = next(e for e in self.events(r) if e["id"] == did)
        self.assertEqual(decision["reason"], "target")
        self.assertTrue(decision["detection_updated"])
        self.assertLessEqual(decision["capture_elapsed_ms"], decision["elapsed_ms"])

    def test_wait_reasons_do_not_claim_attack_was_sent(self):
        r = self.recorder()
        kb = self.keyboard(r)
        kb.set_command("none none attack", decision_id=2)
        with patch("src.input.KeyBoardController.press_key") as send:
            kb._face_direction_until = time.time() + 10
            kb._apply_action()
            kb._apply_action()
            kb._face_direction_until = 0
            kb._attack_pause_until = time.time() + 10
            kb._apply_action()
            kb._attack_pause_until = 0
            kb._t_last_attack = time.time()
            kb._apply_action()
            send.assert_not_called()
        r.close()
        waits = [e["reason"] for e in self.events(r) if e["event"] == "attack_wait"]
        self.assertEqual(waits, ["turn_wait", "potion_or_buff_pause", "cooldown"])
        self.assertFalse(any(e["event"] == "attack_output" for e in self.events(r)))

    def test_reused_detection_and_capture_failure_are_explicit(self):
        r = self.recorder()
        d = self.detector(r)
        d.run_once()
        self.cfg["bot"]["mode"] = "detect"
        self.cfg["monster_detect"]["detection_interval"] = 3
        d.run_once()
        d.get_img_frame.return_value = None
        d.run_once()
        r.close()
        decisions = [e for e in self.events(r) if e["event"] == "decision"]
        self.assertEqual([e["detection_updated"] for e in decisions], [True, False])
        self.assertEqual(d._kb.cmd_action, "none")
        self.assertTrue(any(e["event"] == "capture_failed" for e in self.events(r)))

    def test_duration_limit_stops_recording_and_retains_replay(self):
        r = self.recorder()
        r._start -= 601
        self.assertIsNone(r.event("test"))
        r.close()
        self.assertEqual(r.stop_reason, "duration_limit")
        self.assertTrue((r.directory / "data.js").exists())

    def test_size_limit_does_not_exceed_budget(self):
        self.cfg["recording"]["max_mb"] = 1
        r = self.recorder()
        while r.active:
            r.event("bulk", text="x" * 10000)
        r.close()
        self.assertEqual(r.stop_reason, "size_limit")
        self.assertLessEqual(sum(p.stat().st_size for p in r.directory.rglob("*") if p.is_file()), r.max_bytes)

    def test_disk_failure_disables_recorder_without_raising(self):
        r = self.recorder()
        with patch.object(r, "_stream") as stream:
            stream.write.side_effect = OSError("disk full")
            self.assertIsNone(r.event("test"))
        self.assertFalse(r.active)
        self.assertEqual(r.stop_reason, "write_error")
        r.close()

    def test_queue_overflow_is_reported_and_decision_remains(self):
        r = self.recorder()
        with patch.object(r._queue, "put_nowait", side_effect=__import__("queue").Full):
            did = r.decision(self.image, frame=1)
        r.close()
        dropped = next(e for e in self.events(r) if e["event"] == "frame_dropped")
        self.assertEqual(dropped["decision_id"], did)

    def test_recording_setting_survives_save_and_restart(self):
        path = Path(self.tmp.name) / "settings.yaml"
        for enabled in (True, False):
            cfg = build_settings(self.cfg, {**valid_form(), "recording_enable": enabled})
            save_settings(cfg, path)
            self.assertEqual(load_settings(path)["recording"]["enable"], enabled)

    def test_invalid_output_location_does_not_abort_engine(self):
        path = Path(self.tmp.name) / "file"
        path.write_text("occupied", encoding="utf-8")
        self.cfg["recording"]["directory"] = str(path)
        self.assertIsNone(SessionRecorder.from_config(self.cfg))

    def test_rebuild_accepts_interrupted_final_event(self):
        from tools.rebuild_recording import rebuild
        r = self.recorder()
        r.decision(self.image, frame=1)
        r.close()
        with (r.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write('{"event":"partial')
        (r.directory / "data.js").unlink()
        self.assertTrue(rebuild(r.directory).is_file())
        payload = (r.directory / "data.js").read_text(encoding="utf-8")
        self.assertTrue(json.loads(payload.removeprefix("window.RECORDING=").removesuffix(";")))


if __name__ == "__main__":
    unittest.main()
