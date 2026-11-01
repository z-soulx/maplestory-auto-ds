"""Regression checks for capture thread ownership and startup failures."""
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from src.input.GameWindowCapturor import GameWindowCapturor


class CaptureStartupTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"game_window": {"title": "TestGame"},
                    "system": {"fps_limit_window_capturor": 100}}

    def test_native_capture_resources_stay_on_worker_thread(self):
        owners = []

        class ThreadBoundCapture:
            def __init__(self):
                self.owner = threading.get_ident()
                owners.append(self.owner)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def grab(self, region):
                if threading.get_ident() != self.owner:
                    raise RuntimeError("Capture used from the wrong thread")
                return np.zeros((region["height"], region["width"], 4), dtype=np.uint8)

        window_api = Mock()
        window_api.FindWindow.return_value = 1
        window_api.GetWindowRect.return_value = (10, 20, 74, 68)
        with patch("src.input.GameWindowCapturor.get_game_window_title_by_token", return_value="TestGame"), \
                patch("win32gui.FindWindow", window_api.FindWindow), \
                patch("win32gui.GetWindowRect", window_api.GetWindowRect), \
                patch("src.input.GameWindowCapturor.mss.mss", ThreadBoundCapture):
            capturer = GameWindowCapturor(self.cfg)
            try:
                self.assertEqual(capturer.get_frame().shape, (48, 64, 3))
                self.assertEqual(len(owners), 1)
                self.assertNotEqual(owners[0], threading.get_ident())
            finally:
                capturer.stop()
                capturer._thread.join(timeout=1)
                self.assertFalse(capturer._thread.is_alive())

    def test_capture_initialization_failure_is_reported(self):
        with patch("src.input.GameWindowCapturor.get_game_window_title_by_token", return_value="TestGame"), \
                patch("src.input.GameWindowCapturor.mss.mss", side_effect=RuntimeError("capture unavailable")):
            with self.assertRaisesRegex(RuntimeError, "capture unavailable"):
                GameWindowCapturor(self.cfg)

    def test_missing_window_is_reported(self):
        with patch("src.input.GameWindowCapturor.get_game_window_title_by_token", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "Game window not found"):
                GameWindowCapturor(self.cfg)


if __name__ == "__main__":
    unittest.main()
