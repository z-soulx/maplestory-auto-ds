"""Combat needs a target in skill range, except explicitly enabled search attacks."""
import unittest
import time
import threading
from unittest.mock import Mock, patch

import numpy as np

from src.engine.MonsterDetector import MonsterDetector
from src.input.KeyBoardController import KeyBoardController
from src.launcher_settings import ROOT, load_settings


class AttackRequiresTargetTests(unittest.TestCase):
    def setUp(self):
        cfg = load_settings(ROOT / "config" / "no-saved-settings.yaml")
        cfg["disable_viz"] = True
        cfg["bot"].update(mode="hunt", enable_route=False)
        cfg["player_identity"]["enable"] = False
        cfg["stuck_recovery"] = {"enable": False}
        cfg["directional_attack"].update(search_trigger_frames=1,
                                        search_attack_while_move=False)
        cfg["monster_detect"]["detection_interval"] = 1
        self.d = MonsterDetector(cfg)
        self.d.loc_player = (160, 120)
        self.d.get_img_frame = Mock(return_value=np.zeros((240, 320, 3), dtype=np.uint8))
        self.d._detect_minimap = Mock(return_value=None)
        self.d._detect_player_by_title = Mock()
        self.d.get_monsters_in_range = Mock(return_value=[])
        self.d._kb = Mock()

    def test_search_does_not_attack_when_checkbox_is_off(self):
        self.d.run_once()
        self.d._kb.set_command.assert_called_once_with("left none none")

    def test_search_attack_checkbox_explicitly_allows_empty_swing(self):
        self.d.cfg["directional_attack"]["search_attack_while_move"] = True
        with patch("src.engine.MonsterDetector.logger.info") as log:
            self.d.run_once()
        self.d._kb.set_command.assert_called_once_with("left none attack")
        self.assertTrue(any("reason=search_attack_enabled" in c.args[0] for c in log.call_args_list))

    def test_search_attack_never_overrides_lost_player(self):
        self.d.cfg["directional_attack"]["search_attack_while_move"] = True
        self.d.cfg["player_identity"]["enable"] = True
        self.d._identity_valid = False
        self.d.run_once()
        self.d._kb.set_command.assert_called_once_with("none none none")

    def test_old_in_place_scout_settings_never_fire_without_monsters(self):
        self.d.cfg["directional_attack"].update(attack_in_place=True,
                                               in_place_aoe_idle_seconds=0)
        for _ in range(300):
            self.assertNotIn(self.d._get_in_place_command()[2], ("attack", "aoe", "attack_once"))

    def test_final_dispatch_blocks_all_combat_actions_from_search_and_routes(self):
        for source in ("search", "route"):
            for action in ("attack", "aoe", "attack_once"):
                with self.subTest(source=source, action=action):
                    self.d.cfg["bot"]["enable_route"] = source == "route"
                    self.d.img_route = np.zeros((5, 5, 3), dtype=np.uint8) if source == "route" else None
                    self.d.update_cmd_by_route = Mock()
                    self.d.cmd_move_x, self.d.cmd_move_y, self.d.cmd_action = "left", "none", action
                    self.d._get_hunt_search_command = Mock(return_value=("left", "none", action))
                    self.d._kb.set_command.reset_mock()
                    with patch("src.engine.MonsterDetector.logger.info") as log:
                        self.d.run_once()
                    self.d._kb.set_command.assert_called_once_with("left none none")
                    hunt_logs = [call.args[0] for call in log.call_args_list if "[Hunt]" in call.args[0]]
                    if hunt_logs:
                        self.assertIn("dispatch=(left,none,none)", hunt_logs[-1])
                        self.assertIn("reason=no_target", hunt_logs[-1])

    def test_detected_monsters_still_allow_single_and_aoe_attacks(self):
        monster = {"name": "hou_zi", "position": (190, 100), "size": (50, 40), "score": 0.02}
        for count, action in ((1, "attack"), (3, "aoe")):
            with self.subTest(count=count):
                self.d.get_monsters_in_range.return_value = [monster.copy() for _ in range(count)]
                self.d.run_once()
                self.assertEqual(self.d._kb.set_command.call_args.args[0].split()[2], action)

    def test_empty_detection_replaces_previous_attack_command(self):
        self.d.monsters = [{"name": "stale target"}]
        self.d.run_once()
        self.assertEqual(self.d.monsters, [])
        self.assertEqual(self.d._kb.set_command.call_args.args[0].split()[2], "none")

    def test_hunt_refreshes_boxes_on_skip_frames_after_player_moves(self):
        d = self.d
        d.cfg["monster_detect"]["detection_interval"] = 2
        d.frame_count = 0
        d.monsters = [{"name": "hou_zi", "position": (190, 70), "size": (50, 40), "score": 0.02}]
        d.get_monsters_in_range.return_value = [
            {"name": "hou_zi", "position": (290, 70), "size": (50, 30), "score": 0.02}]
        d.run_once()  # Odd frame; the old near box must not be reused.
        d.get_monsters_in_range.assert_called_once()
        self.assertEqual(d._kb.set_command.call_args.args[0], "right none none")

    def test_lost_target_resumes_search_without_cold_start_pause_or_empty_attack(self):
        d = self.d
        d.cfg["directional_attack"]["search_trigger_frames"] = 4
        d.get_monsters_in_range.return_value = [
            {"name": "hou_zi", "position": (190, 70), "size": (50, 40), "score": 0.02}]
        d.run_once()
        self.assertEqual(d._kb.set_command.call_args.args[0], "face_right none attack")
        d.get_monsters_in_range.return_value = []
        d.run_once()
        self.assertEqual(d._kb.set_command.call_args.args[0], "right none none")
        d.run_once()
        self.assertEqual(d._kb.set_command.call_args.args[0], "right none none")

    def test_keyboard_turn_and_attack_consume_one_command_before_stop(self):
        with patch("src.input.KeyBoardController.threading.Thread.start"):
            kb = KeyBoardController(self.d.cfg)
        kb.set_command("face_right none attack")
        started, finished = threading.Event(), threading.Event()
        observations = []

        def replace():
            started.set()
            kb.set_command("none none none")
            finished.set()

        worker = threading.Thread(target=replace)

        def movement():
            worker.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(finished.is_set())

        kb._game_has_focus = Mock(return_value=True)
        kb._apply_movement = Mock(side_effect=movement)
        kb._apply_action = Mock(side_effect=lambda: observations.append(kb.cmd_action))
        kb._apply_pickup = kb._apply_buff = Mock()
        kb._limit_fps = Mock(side_effect=lambda: setattr(kb, "is_terminated", True))
        kb._run()
        worker.join(2)
        self.assertTrue(finished.is_set())
        self.assertEqual(observations, ["attack"])
        self.assertEqual(kb.cmd_action, "none")

    def test_reachable_monster_cancels_active_stuck_recovery(self):
        self.d._unstick_until = time.time() + 10
        self.d._unstick_dir = "left"
        self.d.get_monsters_in_range.return_value = [
            {"name": "hou_zi", "position": (190, 70), "size": (50, 40), "score": 0.02}]
        self.d.run_once()
        self.assertEqual(self.d._kb.set_command.call_args.args[0], "face_right none attack")
        self.assertEqual(self.d._unstick_until, 0.0)

    def test_attack_log_distinguishes_paused_input_from_dispatch(self):
        self.d._kb.is_enable = False
        self.d.get_monsters_in_range.return_value = [
            {"name": "hou_zi", "position": (190, 70), "size": (50, 40), "score": 0.02}]
        with patch("src.engine.MonsterDetector.logger.info") as log:
            self.d.run_once()
        hunt = [c.args[0] for c in log.call_args_list if "[Hunt]" in c.args[0]][-1]
        self.assertIn("input=paused", hunt)
        self.assertIn("reason=target", hunt)
        self.assertIn("nearest_dx_dy=(30.0, 0.0)", hunt)

    def test_keyboard_reports_actual_send_success_or_failure(self):
        with patch("src.input.KeyBoardController.threading.Thread.start"):
            kb = KeyBoardController(self.d.cfg)
        kb.set_command("none none attack")
        for sent, result in ((False, "failed"), (True, "sent")):
            with self.subTest(sent=sent):
                kb._t_last_attack = 0
                kb._press_key_serialized = Mock(return_value=sent)
                with patch("src.input.KeyBoardController.logger.info") as log:
                    kb._apply_action()
                kb._press_key_serialized.assert_called_once_with(kb.key_directional_attack, 0.05)
                self.assertTrue(any(f"result={result}" in c.args[0] for c in log.call_args_list))

    def test_far_monster_is_approached_before_melee_attack(self):
        monster = {"name": "hou_zi", "position": (290, 70), "size": (50, 30), "score": 0.02}
        self.d.get_monsters_in_range.return_value = [monster]
        for option in (False, True):
            with self.subTest(search_attack=option):
                self.d.cfg["directional_attack"]["search_attack_while_move"] = option
                self.d.run_once()
                self.assertEqual(self.d._kb.set_command.call_args.args[0], "right none none")
        monster["position"] = (230, 70)
        self.d.run_once()
        self.assertEqual(self.d._kb.set_command.call_args.args[0], "face_right none attack")

    def test_monster_on_another_floor_is_not_a_melee_target(self):
        self.d.get_monsters_in_range.return_value = [
            {"name": "hou_zi", "position": (180, 5), "size": (50, 40), "score": 0.02}]
        self.d.run_once()
        self.assertEqual(self.d._kb.set_command.call_args.args[0], "left none none")
        self.assertEqual(self.d._hunt_no_monster_frames, 1)

    def test_aoe_threshold_counts_only_monsters_in_skill_range(self):
        close = {"name": "hou_zi", "position": (190, 70), "size": (50, 40), "score": 0.02}
        far = {"name": "hou_zi", "position": (290, 70), "size": (50, 30), "score": 0.02}
        self.d.get_monsters_in_range.return_value = [close, far, far]
        self.d.run_once()
        self.assertEqual(self.d._kb.set_command.call_args.args[0].split()[2], "attack")

    def test_in_place_and_route_attacks_also_require_melee_range(self):
        far = {"name": "hou_zi", "position": (290, 70), "size": (50, 30), "score": 0.02}
        self.d.monsters = [far]
        self.assertEqual(self.d._get_in_place_command()[2], "none")
        self.d.cfg["bot"]["enable_route"] = True
        self.d.img_route = np.zeros((5, 5, 3), dtype=np.uint8)
        self.d.get_monsters_in_range.return_value = [far]
        self.d.update_cmd_by_route = Mock()
        self.d.cmd_action = "attack_once"
        self.d.run_once()
        self.assertEqual(self.d._kb.set_command.call_args.args[0].split()[2], "none")

    def test_capture_failure_clears_targets_and_old_command(self):
        self.d.monsters = [{"name": "stale target"}]
        self.d.get_img_frame.return_value = None
        self.assertEqual(self.d.run_once(), -1)
        self.assertEqual(self.d.monsters, [])
        self.d._kb.set_command.assert_called_once_with("none none none")

    def test_processing_exception_stops_previous_attack(self):
        self.d.monsters = [{"name": "stale target"}]
        def fail():
            self.d.is_terminated = True
            raise RuntimeError("offline simulated frame error")
        self.d.run_once = Mock(side_effect=fail)
        self.d._process_loop()
        self.assertEqual(self.d.monsters, [])
        self.d._kb.set_command.assert_called_once_with("none none none")

    def test_keyboard_stops_repeating_after_receiving_no_attack(self):
        with patch("src.input.KeyBoardController.threading.Thread.start"):
            kb = KeyBoardController(self.d.cfg)
        kb._press_key_serialized = Mock(return_value=True)
        kb.set_command("left none attack")
        kb._apply_action()
        kb._press_key_serialized.assert_called_once()
        kb.set_command("left none none")
        kb._t_last_attack = 0
        kb._apply_action()
        kb._apply_action()
        kb._press_key_serialized.assert_called_once()


if __name__ == "__main__":
    unittest.main()
