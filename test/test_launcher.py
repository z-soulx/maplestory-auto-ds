import copy
import io
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
import uuid

import numpy as np

from src.launcher import Launcher
from src.launcher_settings import ROOT, build_settings, load_settings, save_settings
from src.input.KeyBoardController import KeyBoardController
from src.engine.MonsterDetector import MonsterDetector
from src.utils.common import get_game_window_title_by_token


def valid_form():
    return dict(mode="detect", window_title="冒险岛怀旧服", exact_match=True,
                attack_style="directional", warning=False,
                directional_attack="x", aoe_skill="a", jump="alt", teleport="e",
                pickup="z", add_hp="end", add_mp="home", return_home="insert",
                jump_up="0", range_x="300", range_y="70", attack_cd="0.9", aoe_count="3",
                pickup_enable=False, buffs="2:120,3:180", scales="1.4", threshold="0.28",
                display_scale="0.65", health_enable=False, hp_enable=True, mp_enable=True,
                hp_percent="50", mp_percent="10", hp_rect="", mp_rect="",
                route_enable=False, map_name="", title_enable=True)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.base = load_settings(ROOT / ".venv" / "no-saved-settings.yaml")

    def test_explicit_hunt_keeps_calibration_and_key_bindings(self):
        form = valid_form()
        form["mode"] = "hunt"
        cfg = build_settings(self.base, form)
        self.assertEqual(cfg["bot"]["mode"], "hunt")
        self.assertTrue(cfg["bot"]["require_foreground"])
        self.assertEqual(cfg["key"]["directional_attack"], "x")
        self.assertEqual(cfg["buff_skill"]["cooldown"], [120, 180])
        self.assertEqual(cfg["monster_detect"]["monsters"]["feng_du_yan_shou"]["scales"], [1.4])
        self.assertEqual(cfg["title"]["template"], "character/player_title_current.png")
        self.assertEqual(self.base["bot"]["mode"], "detect")

    def test_saved_keys_survive_restart_but_hunt_requires_new_start(self):
        form = valid_form()
        form["mode"] = "hunt"
        cfg = build_settings(self.base, form)
        with tempfile.TemporaryDirectory(dir=ROOT / ".venv") as directory:
            path = Path(directory) / "settings.yaml"
            save_settings(cfg, path)
            restored = load_settings(path)
        self.assertEqual(restored["key"]["directional_attack"], "x")
        self.assertEqual(restored["bot"]["mode"], "detect")

    def test_invalid_values_do_not_modify_source(self):
        for changes in ({"threshold": "nan"}, {"buffs": "2,3"},
                        {"hp_rect": "1,2,3,4"}, {"route_enable": True, "map_name": "missing"},
                        {"directional_attack": "f1"}):
            with self.subTest(changes=changes):
                source = copy.deepcopy(self.base)
                with self.assertRaises(ValueError):
                    build_settings(self.base, {**valid_form(), **changes})
                self.assertEqual(self.base, source)

    def test_monkey_selection_survives_restart_without_readding_curse_eye(self):
        cfg = build_settings(self.base, {**valid_form(), "monsters": ["hou_zi", "jiang_shi_hou_zi"]})
        with tempfile.TemporaryDirectory(dir=ROOT / ".venv") as directory:
            path = Path(directory) / "settings.yaml"
            save_settings(cfg, path)
            restored = load_settings(path)
        self.assertEqual(set(restored["monster_detect"]["monsters"]), {"hou_zi", "jiang_shi_hou_zi"})
        self.assertEqual(restored["key"]["directional_attack"], "x")
        self.assertEqual(restored["title"], self.base["title"])
        self.assertEqual(restored["bot"]["mode"], "detect")

    def test_invalid_monster_selection_is_rejected(self):
        for monsters in ([], ["missing"], [".."], ["../hou_zi"], "hou_zi"):
            with self.subTest(monsters=monsters), self.assertRaises(ValueError):
                build_settings(self.base, {**valid_form(), "monsters": monsters})

    def test_search_attack_checkbox_and_melee_range_are_saved_separately(self):
        for checked in (False, True):
            with self.subTest(checked=checked):
                cfg = build_settings(self.base, {**valid_form(), "search_attack": checked,
                                                "attack_range_x": "90", "attack_range_y": "30"})
                attack = cfg["directional_attack"]
                self.assertEqual(attack["search_attack_while_move"], checked)
                self.assertEqual((attack["range_x"], attack["attack_range_x"], attack["attack_range_y"]),
                                 (300, 90, 30))
                with tempfile.TemporaryDirectory(dir=ROOT / ".venv") as directory:
                    path = Path(directory) / "settings.yaml"
                    save_settings(cfg, path)
                    restored = load_settings(path)["directional_attack"]
                self.assertEqual(restored["search_attack_while_move"], checked)
                self.assertEqual(restored["attack_range_x"], 90)

    def test_invalid_melee_ranges_are_rejected(self):
        for values in ({"attack_range_x": "0"}, {"attack_range_y": "nan"},
                       {"attack_range_x": "301"}, {"attack_range_y": "71"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                build_settings(self.base, {**valid_form(), **values})

    def test_name_only_hunt_does_not_require_title_or_appearance(self):
        cfg = build_settings(self.base, {**valid_form(), "mode": "hunt", "title_enable": False,
                                        "verify_medal": False, "verify_appearance": False})
        self.assertTrue(cfg["player_identity"]["enable"])
        self.assertFalse(cfg["title"]["enable"])
        self.assertFalse(cfg["player_identity"]["require_medal"])
        self.assertFalse(cfg["player_identity"]["require_appearance"])

    def test_all_nonempty_source_combinations_and_policies_are_saved(self):
        for mask in range(1, 8):
            selected = [source for index, source in enumerate(("name", "medal", "appearance"))
                        if mask & (1 << index)]
            for policy in ("any", "all"):
                with self.subTest(selected=selected, policy=policy):
                    cfg = build_settings(self.base, {**valid_form(), "mode": "hunt",
                        "locate_name": "name" in selected, "verify_medal": "medal" in selected,
                        "verify_appearance": "appearance" in selected, "identity_policy": policy})
                    self.assertEqual(cfg["player_identity"]["sources"], selected)
                    self.assertEqual(cfg["player_identity"]["match_policy"], policy)
                    self.assertEqual(cfg["title"]["enable"], "medal" in selected)
                    self.assertEqual(cfg["appearance"]["enable"], "appearance" in selected)

    def test_no_sources_invalid_policy_and_missing_selected_template_are_rejected(self):
        for form in ({"locate_name": False, "verify_medal": False, "verify_appearance": False},
                     {"locate_name": True, "identity_policy": "invalid"}):
            with self.subTest(form=form), self.assertRaises(ValueError):
                build_settings(self.base, {**valid_form(), **form})
        base = copy.deepcopy(self.base)
        base["title"]["template"] = "character/missing-medal.png"
        with self.assertRaisesRegex(ValueError, "勋章"):
            build_settings(base, {**valid_form(), "locate_name": False, "verify_medal": True})

    def test_auxiliary_checkboxes_survive_restart(self):
        cfg = build_settings(self.base, {**valid_form(), "verify_medal": True,
                                        "verify_appearance": True, "partial_name": False})
        with tempfile.TemporaryDirectory(dir=ROOT / ".venv") as directory:
            path = Path(directory) / "settings.yaml"
            save_settings(cfg, path)
            restored = load_settings(path)
        self.assertTrue(restored["player_identity"]["require_medal"])
        self.assertTrue(restored["player_identity"]["require_appearance"])
        self.assertFalse(restored["player_identity"]["allow_partial_name"])


class WindowSelectionTests(unittest.TestCase):
    def select(self, titles, token, exact=False):
        def enumerate_windows(callback, _):
            for index in range(len(titles)):
                callback(index, None)
        with patch("win32gui.EnumWindows", side_effect=enumerate_windows), \
                patch("win32gui.IsWindowVisible", return_value=True), \
                patch("win32gui.GetWindowText", side_effect=lambda index: titles[index]):
            return get_game_window_title_by_token(token, exact_match=exact)

    def test_game_beats_browser_regardless_of_enumeration_order(self):
        browser = "积分商城 - 冒险岛怀旧服家族 — Mozilla Firefox"
        for titles in (["冒险岛怀旧服", browser], [browser, "冒险岛怀旧服"]):
            self.assertEqual(self.select(titles, "冒险岛怀旧服"), "冒险岛怀旧服")

    def test_exact_match_never_falls_back_to_browser(self):
        self.assertEqual(self.select(["冒险岛怀旧服家族 — Mozilla Firefox"], "冒险岛怀旧服", True), "")

    def test_ambiguous_partial_matches_are_rejected(self):
        self.assertEqual(self.select(["Maple Game", "Maple Website"], "Maple"), "")
        self.assertEqual(self.select(["Maple Game"], "maple"), "Maple Game")


class FocusTests(unittest.TestCase):
    def test_detect_mode_cannot_move_from_stuck_recovery(self):
        cfg = load_settings(ROOT / ".venv" / "no-saved-settings.yaml")
        cfg["disable_viz"] = True
        cfg["monster_detect"]["detection_interval"] = 1
        cfg["stuck_recovery"] = {"enable": True, "timeout_seconds": 1}
        detector = MonsterDetector(cfg)
        detector.get_img_frame = Mock(return_value=np.zeros((240, 320, 3), dtype=np.uint8))
        detector._detect_minimap = Mock(return_value=None)
        detector._detect_player_by_title = Mock()
        detector.get_monsters_in_range = Mock(return_value=[])
        detector.loc_player_minimap = (10, 10)
        detector._stuck_last_move_time = time.time() - 10
        detector._kb = Mock()
        detector.run_once()
        detector._kb.set_command.assert_called_once_with("none none none")

    def test_lost_focus_releases_keys_and_skips_input(self):
        kb = KeyBoardController.__new__(KeyBoardController)
        kb.is_terminated, kb.is_enable, kb._had_focus = False, True, True
        kb._game_has_focus = Mock(return_value=False)
        kb.release_all = Mock()
        for name in ("_apply_movement", "_apply_action", "_apply_pickup", "_apply_buff"):
            setattr(kb, name, Mock())
        kb._limit_fps = Mock(side_effect=lambda: setattr(kb, "is_terminated", True))
        kb._run()
        kb.release_all.assert_called_once()
        kb._apply_action.assert_not_called()
        kb._apply_movement.assert_not_called()

    def test_matching_browser_title_is_not_game_focus(self):
        kb = KeyBoardController.__new__(KeyBoardController)
        kb.cfg = {"bot": {"require_foreground": True},
                  "game_window": {"title": "冒险岛怀旧服", "exact_match": True}}
        with patch("win32gui.GetForegroundWindow", return_value=1), \
                patch("win32gui.GetWindowText", return_value="冒险岛怀旧服家族 — Mozilla Firefox"):
            self.assertFalse(kb._game_has_focus())


class LauncherUiTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "config" / f"config_gui_test_{uuid.uuid4().hex}.yaml"
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = Launcher(self.root, self.path)
        permission_check = patch("src.launcher.game_input_permission_issue", return_value=None)
        self.permission_check = permission_check.start()
        self.addCleanup(permission_check.stop)

    def tearDown(self):
        self.app.process = None
        if self.app.stop_file:
            self.app.stop_file.unlink(missing_ok=True)
        self.root.destroy()
        self.path.unlink(missing_ok=True)

    def test_opening_and_saving_never_starts_engine(self):
        with patch("src.launcher.subprocess.Popen") as launch:
            self.assertEqual(self.app.form()["mode"], "detect")
            self.app.fields["directional_attack"].set("x")
            cfg = self.app.save()
            self.assertEqual(cfg["key"]["directional_attack"], "x")
            self.assertTrue(self.path.is_file())
            launch.assert_not_called()

    def test_start_uses_saved_profile_and_stop_is_cooperative(self):
        child = Mock()
        child.stdout = io.StringIO("")
        child.poll.return_value = None
        with patch("src.launcher.subprocess.Popen", return_value=child) as launch:
            self.app.start()
            args = launch.call_args.args[0]
            self.assertIn(self.path.stem.removeprefix("config_"), args)
            self.assertIn("--stop_file", args)
            self.app.stop()
            self.assertTrue(self.app.stop_file.is_file())
            child.poll.return_value = 0
            child.returncode = 0
            self.app.poll()
            self.assertIsNone(self.app.process)
            self.assertFalse(self.app.stop_file.exists())

    def test_monkey_checkboxes_are_saved(self):
        for name, variable in self.app.monster_fields.items():
            variable.set(name in ("hou_zi", "jiang_shi_hou_zi"))
        cfg = self.app.save()
        self.assertEqual(set(cfg["monster_detect"]["monsters"]), {"hou_zi", "jiang_shi_hou_zi"})
        self.assertEqual(set(load_settings(self.path)["monster_detect"]["monsters"]),
                         {"hou_zi", "jiang_shi_hou_zi"})

    def test_search_attack_checkbox_defaults_off_and_can_be_enabled(self):
        self.assertFalse(self.app.fields["search_attack"].get())
        self.app.fields["search_attack"].set(True)
        self.app.fields["attack_range_x"].set("90")
        cfg = self.app.save()
        self.assertTrue(cfg["directional_attack"]["search_attack_while_move"])
        self.assertEqual(cfg["directional_attack"]["attack_range_x"], 90)

    def test_recording_checkbox_is_saved_and_defaults_off(self):
        self.assertFalse(self.app.fields["recording_enable"].get())
        self.app.fields["recording_enable"].set(True)
        cfg = self.app.save()
        self.assertTrue(cfg["recording"]["enable"])
        self.assertTrue(load_settings(self.path)["recording"]["enable"])

    def test_localization_sources_and_policy_are_independent(self):
        self.assertNotIn("title_enable", self.app.fields)
        self.assertTrue(self.app.fields["locate_name"].get())
        self.assertFalse(self.app.fields["verify_medal"].get())
        self.assertFalse(self.app.fields["verify_appearance"].get())
        self.app.fields["verify_medal"].set(True)
        self.app.fields["partial_name"].set(False)
        cfg = self.app.save()
        self.assertTrue(cfg["player_identity"]["enable"])
        self.assertEqual(cfg["player_identity"]["sources"], ["name", "medal"])
        self.assertEqual(cfg["player_identity"]["match_policy"], "any")
        self.assertFalse(cfg["player_identity"]["allow_partial_name"])

    def test_medal_only_and_combined_strict_choices_survive_restart(self):
        self.app.fields["locate_name"].set(False)
        self.app.fields["verify_medal"].set(True)
        self.app.save()
        restored = load_settings(self.path)
        self.assertEqual(restored["player_identity"]["sources"], ["medal"])
        self.assertTrue(restored["title"]["enable"])
        self.app.fields["locate_name"].set(True)
        self.app.fields["identity_policy"].set("全部匹配才定位（联合核对）")
        self.app.save()
        restored = load_settings(self.path)
        self.assertEqual(restored["player_identity"]["sources"], ["name", "medal"])
        self.assertEqual(restored["player_identity"]["match_policy"], "all")

    def test_footer_stays_visible_and_settings_can_scroll(self):
        self.root.deiconify()
        for geometry in ("860x720", "800x670"):
            self.root.geometry(geometry)
            for index in range(4):
                with self.subTest(geometry=geometry, tab=index):
                    self.app.notebook.select(index)
                    self.root.update()
                    for widget in (self.app.start_button, self.app.stop_button,
                                   self.app.save_button, self.app.log):
                        self.assertTrue(widget.winfo_ismapped())
                        x = widget.winfo_rootx() - self.root.winfo_rootx()
                        y = widget.winfo_rooty() - self.root.winfo_rooty()
                        self.assertGreaterEqual(x, 0)
                        self.assertGreaterEqual(y, 0)
                        self.assertLessEqual(x + widget.winfo_width(), self.root.winfo_width())
                        self.assertLessEqual(y + widget.winfo_height(), self.root.winfo_height())
        self.app.notebook.select(2)
        self.root.update()
        canvas = self.app.tab_canvases[self.app.notebook.select()]
        self.assertGreater(canvas.bbox("all")[3], canvas.winfo_height())
        canvas.yview_moveto(1)
        self.root.update()
        self.assertAlmostEqual(canvas.yview()[1], 1.0, places=2)

    def test_permission_mismatch_saves_settings_but_blocks_hunt(self):
        self.app.fields["mode"].set("自动打怪")
        self.permission_check.return_value = "游戏与脚本权限不一致"
        with patch("src.launcher.subprocess.Popen") as launch, \
                patch("src.launcher.messagebox.showerror") as error:
            self.app.start()
            launch.assert_not_called()
            error.assert_called_once()
            self.assertTrue(self.path.is_file())
            self.assertIsNone(self.app.process)

    def test_permission_mismatch_still_allows_detection_without_medicine(self):
        self.permission_check.return_value = "游戏与脚本权限不一致"
        child = Mock()
        child.stdout = io.StringIO("")
        with patch("src.launcher.subprocess.Popen", return_value=child) as launch:
            self.app.start()
            launch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
