import unittest
from unittest.mock import Mock, patch

import pywintypes

from src.utils.input_permissions import game_input_permission_issue, process_is_elevated


class InputPermissionsTests(unittest.TestCase):
    def test_only_confirmed_game_elevation_mismatch_is_reported(self):
        with patch("src.utils.common.get_game_window_title_by_token", return_value="Game"), \
                patch("win32gui.FindWindow", return_value=10), \
                patch("win32process.GetWindowThreadProcessId", return_value=(1, 2)):
            for game, script, blocked in ((True, False, True), (True, True, False),
                                           (False, False, False), (None, False, False),
                                           (True, None, False)):
                with self.subTest(game=game, script=script), patch(
                        "src.utils.input_permissions.process_is_elevated",
                        side_effect=[game, script]):
                    issue = game_input_permission_issue({"game_window": {"title": "Game"}})
                    self.assertEqual(bool(issue), blocked)

    def test_missing_window_does_not_query_a_process(self):
        with patch("src.utils.common.get_game_window_title_by_token", return_value=""), \
                patch("src.utils.input_permissions.process_is_elevated") as query:
            self.assertIsNone(game_input_permission_issue({}))
            query.assert_not_called()

    def test_query_failure_is_unknown_and_closes_open_handle(self):
        process = Mock()
        with patch("win32api.OpenProcess", return_value=process), \
                patch("win32security.OpenProcessToken", side_effect=pywintypes.error(5, "OpenProcessToken", "denied")):
            self.assertIsNone(process_is_elevated(42))
            process.Close.assert_called_once()

    def test_success_closes_both_handles(self):
        process, token = Mock(), Mock()
        with patch("win32api.OpenProcess", return_value=process), \
                patch("win32security.OpenProcessToken", return_value=token), \
                patch("win32security.GetTokenInformation", return_value=1):
            self.assertTrue(process_is_elevated(42))
            token.Close.assert_called_once()
            process.Close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
