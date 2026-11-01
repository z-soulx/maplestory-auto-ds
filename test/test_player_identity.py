"""Name localization is independent of the optional medal and appearance checks."""
import time
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

from src.engine.MonsterDetector import MonsterDetector
from src.launcher_settings import ROOT, load_settings


class PlayerIdentityTests(unittest.TestCase):
    def setUp(self):
        cfg = load_settings(ROOT / "config" / "no-saved-settings.yaml")
        cfg["disable_viz"] = True
        cfg["bot"]["mode"] = "hunt"
        self.detector = MonsterDetector(cfg)
        self.frame = np.full((400, 750, 3), (70, 100, 50), dtype=np.uint8)

    def paste(self, image, x, y):
        h, w = image.shape[:2]
        self.frame[y:y+h, x:x+w] = image

    def character(self, feet, name=True, pet=False):
        d = self.detector
        th, tw = d.img_title.shape[:2]
        ox, oy = d.cfg["title"]["offset"]
        self.paste(d.img_title, feet[0] - tw // 2 - ox, feet[1] - th // 2 - oy)
        if name:
            image, options = d._identity_templates[0]
            h, w = image.shape[:2]
            dx, dy = options["offset"]
            x, y = feet[0] - w // 2 - dx, feet[1] - h // 2 - dy
            self.paste(image, x, y)
            if pet:
                self.frame[y:y+h, x:x+31] = (210, 220, 230)

    def locate(self):
        d = self.detector
        d.img_frame = self.frame
        d.img_frame_gray = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
        d._detect_player_by_title()

    def test_name_selects_me_even_when_another_medal_is_at_frame_center(self):
        self.character((190, 160))
        self.character((520, 160), name=False)
        self.locate()
        self.assertTrue(self.detector._identity_valid)
        self.assertEqual(self.detector.loc_player, (190, 160))

    def test_pet_can_cover_left_name_but_right_name_and_medal_must_agree(self):
        self.character((190, 160), pet=True)
        self.character((520, 160), name=False)
        self.locate()
        self.assertTrue(self.detector._identity_valid)
        self.assertEqual(self.detector.loc_player, (190, 160))

    def test_shared_medal_without_my_name_does_not_fall_back_to_center(self):
        self.character((520, 160), name=False)
        self.locate()
        self.assertFalse(self.detector._identity_valid)
        self.assertEqual(self.detector.loc_player, (0, 0))

    def test_local_search_requires_current_name_and_can_reacquire_far_away(self):
        self.character((190, 160))
        self.locate()
        self.assertEqual(self.detector._identity_search_center, (190, 160))
        self.frame[:] = (70, 100, 50)
        self.locate()
        self.assertFalse(self.detector._identity_valid)
        self.assertEqual(self.detector.loc_player, (0, 0))
        self.character((520, 160))
        self.locate()
        self.assertTrue(self.detector._identity_valid)
        self.assertEqual(self.detector.loc_player, (520, 160))

    def test_local_search_returns_global_coordinates_and_honors_auxiliary_check(self):
        self.character((520, 160))
        self.locate()
        self.locate()  # This match uses an ROI with a nonzero horizontal origin.
        self.assertEqual(self.detector.loc_player, (520, 160))
        self.detector.cfg["player_identity"]["require_medal"] = True
        self.frame[235:265, 430:610] = (70, 100, 50)
        self.locate()
        self.assertFalse(self.detector._identity_valid)

    def test_name_at_another_position_cannot_validate_a_medal(self):
        self.detector.cfg["player_identity"]["require_medal"] = True
        self.character((520, 160), name=False)
        self.paste(self.detector._identity_templates[0][0], 120, 100)
        self.locate()
        self.assertFalse(self.detector._identity_valid)

    def test_name_alone_works_without_any_medal_or_appearance_template(self):
        self.character((190, 160))
        self.frame[235:265, 100:280] = (70, 100, 50)
        self.detector.img_title = self.detector.img_title_gray = None
        self.detector.img_appearance = None
        self.locate()
        self.assertTrue(self.detector._identity_valid)
        self.assertEqual(self.detector.loc_player, (190, 160))

    def test_medal_check_is_required_only_when_selected(self):
        self.character((190, 160))
        self.frame[235:265, 100:280] = (70, 100, 50)
        self.locate()
        self.assertTrue(self.detector._identity_valid)
        self.detector.cfg["player_identity"]["require_medal"] = True
        self.locate()
        self.assertFalse(self.detector._identity_valid)
        self.character((190, 160))
        self.locate()
        self.assertTrue(self.detector._identity_valid)

    def test_partial_name_can_be_disabled(self):
        self.character((190, 160), pet=True)
        self.locate()
        self.assertTrue(self.detector._identity_valid)
        self.detector.cfg["player_identity"]["allow_partial_name"] = False
        self.locate()
        self.assertFalse(self.detector._identity_valid)

    def test_medal_alone_works_without_name_templates(self):
        self.detector.cfg["player_identity"].update(sources=["medal"], match_policy="any")
        self.character((190, 160), name=False)
        self.detector._identity_templates = []
        self.locate()
        self.assertTrue(self.detector._identity_valid)
        self.assertEqual(self.detector.loc_player, (190, 160))
        self.assertEqual(self.detector._identity_used_sources, ["medal"])

    def test_old_launcher_config_uses_medal_when_name_is_completely_hidden(self):
        # Reproduce the user's actual file, rewritten without sources/policy.
        cfg = load_settings(ROOT / "config" / "no-saved-settings.yaml")
        cfg["player_identity"].update(require_medal=True, allow_partial_name=False)
        cfg["player_identity"].pop("sources", None)
        cfg["player_identity"].pop("match_policy", None)
        self.detector = MonsterDetector(cfg)
        self.character((190, 160), name=False)
        self.locate()
        self.assertEqual(cfg["player_identity"]["sources"], ["name", "medal"])
        self.assertEqual(cfg["player_identity"]["match_policy"], "any")
        self.assertTrue(self.detector._identity_valid)
        self.assertEqual(self.detector._identity_used_sources, ["medal"])

    def test_explicit_all_policy_is_not_changed_by_legacy_compatibility(self):
        cfg = load_settings(ROOT / "config" / "no-saved-settings.yaml")
        cfg["player_identity"].update(sources=["name", "medal"], match_policy="all", require_medal=True)
        self.detector = MonsterDetector(cfg)
        self.character((190, 160), name=False)
        self.locate()
        self.assertFalse(self.detector._identity_valid)
        self.assertEqual(cfg["player_identity"]["match_policy"], "all")

    def test_any_policy_uses_medal_when_name_is_covered_and_stops_when_both_disappear(self):
        d = self.detector
        d.cfg["player_identity"].update(sources=["name", "medal"], match_policy="any")
        self.character((190, 160))
        self.locate()
        self.assertEqual(d._identity_used_sources, ["name"])
        self.frame[:] = (70, 100, 50)
        self.character((190, 160), name=False)
        self.locate()
        self.assertTrue(d._identity_valid)
        self.assertEqual(d.loc_player, (190, 160))
        self.assertEqual(d._identity_used_sources, ["medal"])
        self.frame[:] = (70, 100, 50)
        self.locate()
        self.assertFalse(d._identity_valid)
        self.assertEqual(d.loc_player, (0, 0))

    def test_all_policy_requires_name_and_medal_at_the_same_position(self):
        d = self.detector
        d.cfg["player_identity"].update(sources=["name", "medal"], match_policy="all")
        self.character((190, 160))
        self.character((520, 160), name=False)
        self.locate()
        self.assertTrue(d._identity_valid)
        self.assertEqual(d.loc_player, (190, 160))
        self.assertEqual(d._identity_used_sources, ["name", "medal"])
        self.frame[235:265, 100:280] = (70, 100, 50)
        self.locate()
        self.assertFalse(d._identity_valid)

    def test_appearance_alone_supports_both_directions_without_name_or_medal(self):
        d = self.detector
        d.cfg["player_identity"].update(sources=["appearance"], match_policy="any")
        d.cfg["appearance"].update(feet_offset=[0, 0], match_threshold=0.99)
        template = np.random.default_rng(9).integers(30, 240, (20, 16, 3), dtype=np.uint8)
        d.img_appearance = template
        d.img_appearance_mask = np.full((20, 16), 255, dtype=np.uint8)
        d.img_title_gray = None
        d._identity_templates = []
        for flip in (False, True):
            with self.subTest(flip=flip):
                self.frame[:] = (70, 100, 50)
                self.paste(cv2.flip(template, 1) if flip else template, 182, 140)
                self.locate()
                self.assertTrue(d._identity_valid)
                self.assertEqual(d.loc_player, (190, 160))
                self.assertEqual(d._identity_used_sources, ["appearance"])

    def test_all_three_sources_must_align(self):
        d = self.detector
        d.cfg["player_identity"].update(sources=["name", "medal", "appearance"], match_policy="all")
        d.cfg["appearance"].update(feet_offset=[0, 0], match_threshold=0.99)
        template = np.random.default_rng(11).integers(30, 240, (20, 16, 3), dtype=np.uint8)
        d.img_appearance = template
        d.img_appearance_mask = np.full((20, 16), 255, dtype=np.uint8)
        self.character((190, 160))
        self.paste(template, 182, 140)
        self.locate()
        self.assertTrue(d._identity_valid)
        self.frame[140:160, 182:198] = (70, 100, 50)
        self.paste(template, 382, 140)
        self.locate()
        self.assertFalse(d._identity_valid)

    def test_explicit_empty_or_unknown_sources_never_use_legacy_fallback(self):
        self.character((190, 160))
        for sources in ([], ["unknown"], "name"):
            self.detector.cfg["player_identity"].update(sources=sources, match_policy="any")
            self.locate()
            self.assertFalse(self.detector._identity_valid)
            self.assertEqual(self.detector.loc_player, (0, 0))

    def test_reacquired_name_detects_and_attacks_without_waiting_for_skip_interval(self):
        d = self.detector
        d.cfg["monster_detect"]["detection_interval"] = 2
        d._detect_minimap = Mock(return_value=None)
        d._kb = Mock()
        d.get_img_frame = Mock(side_effect=lambda: self.frame.copy())
        d.get_monsters_in_range = Mock(return_value=[
            {"name": "hou_zi", "position": (220, 110), "size": (50, 40), "score": 0.02}])
        self.character((190, 160))
        d.frame_count = 0
        d.run_once()  # Odd frame, immediately after first acquisition.
        self.assertTrue(d._identity_valid)
        d.get_monsters_in_range.assert_called_once()
        self.assertEqual(d._kb.set_command.call_args.args[0], "face_right none attack")
        self.frame[:] = (70, 100, 50)
        d.run_once()  # Name lost, targets cleared.
        self.assertFalse(d._identity_valid)
        self.assertEqual(d.monsters, [])
        self.character((190, 160))
        d.get_monsters_in_range.reset_mock()
        d.run_once()  # Odd frame again, immediately after reacquisition.
        d.get_monsters_in_range.assert_called_once()
        self.assertEqual(d._kb.set_command.call_args.args[0], "face_right none attack")

    def test_failed_identity_reports_name_or_selected_medal_component(self):
        self.locate()
        self.assertEqual(self.detector._identity_reason, "name_mismatch")
        self.assertIn("full", self.detector._identity_scores)
        self.character((190, 160))
        self.detector.cfg["player_identity"]["require_medal"] = True
        self.detector.img_title_gray = None
        self.locate()
        self.assertEqual(self.detector._identity_reason, "medal_mismatch")

    def test_appearance_check_is_optional_and_confirms_name_position(self):
        self.character((190, 160))
        self.detector.img_appearance = None
        self.locate()
        self.assertTrue(self.detector._identity_valid)
        self.detector.cfg["player_identity"]["require_appearance"] = True
        self.locate()
        self.assertFalse(self.detector._identity_valid)
        rng = np.random.default_rng(7)
        template = rng.integers(30, 240, (20, 16, 3), dtype=np.uint8)
        self.detector.img_appearance = template
        self.detector.img_appearance_mask = np.full((20, 16), 255, dtype=np.uint8)
        self.detector.cfg["appearance"].update(feet_offset=[0, 0], match_threshold=0.99)
        self.paste(template, 182, 140)
        self.locate()
        self.assertTrue(self.detector._identity_valid)
        self.assertEqual(self.detector.loc_player, (190, 160))

    def test_f12_cannot_freeze_a_position_in_name_verification_mode(self):
        self.assertFalse(self.detector.toggle_title_fixed())
        self.assertFalse(self.detector._title_fixed)

    def test_lost_identity_clears_cached_targets_and_stops_hunt_and_recovery(self):
        self.character((190, 160))
        self.locate()
        d = self.detector
        self.assertTrue(d._identity_valid)
        d.monsters = [{"name": "stale target"}]
        d.get_img_frame = Mock(return_value=np.full_like(self.frame, 100))
        d._detect_minimap = Mock(return_value=None)
        d.get_monsters_in_range = Mock()
        d.cfg["directional_attack"]["attack_in_place"] = True
        d._unstick_until = time.time() + 10
        d._unstick_dir = "right"
        d._kb = Mock()
        d.run_once()
        self.assertFalse(d._identity_valid)
        self.assertEqual(d.monsters, [])
        d.get_monsters_in_range.assert_not_called()
        d._kb.set_command.assert_called_once_with("none none none")


if __name__ == "__main__":
    unittest.main()
