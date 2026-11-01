"""Matching accuracy, crowded candidates and turn timing without game input."""
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from src.engine.MonsterDetector import MonsterDetector
from src.input.KeyBoardController import KeyBoardController
from src.launcher_settings import ROOT, load_settings
from src.utils.common import get_iou, nms


class DetectionOptimizationTests(unittest.TestCase):
    def test_fast_masked_scores_agree_with_opencv_and_handle_empty_energy(self):
        rng = np.random.default_rng(910)
        for shape in ((23, 30), (90, 130)):
            image = rng.integers(0, 256, (*shape, 3), dtype=np.uint8)
            template = image[5:17, 6:22].copy()
            mask = rng.choice(np.array([0, 255], dtype=np.uint8), size=template.shape[:2])
            expected = cv2.matchTemplate(image, template, cv2.TM_SQDIFF_NORMED, mask=mask)
            actual = MonsterDetector._match_masked_color(image, template, mask)
            np.testing.assert_allclose(actual, expected, atol=2e-6, rtol=2e-6)
        for mask in (np.zeros((12, 16), np.uint8), np.full((12, 16), 255, np.uint8)):
            result = MonsterDetector._match_masked_color(np.zeros((23, 30, 3), np.uint8),
                                                        np.zeros((12, 16, 3), np.uint8), mask)
            self.assertTrue(np.isfinite(result).all())
            self.assertTrue((result == 1).all())

    def test_repeated_offsets_do_not_hide_a_monster_later_in_the_image(self):
        cfg = load_settings(ROOT / "config/no-saved-settings.yaml")
        detector = MonsterDetector(cfg)
        detector.monster_cfg = {"fixture": {"scales": [1.0], "diff_thres": .28}}
        scores = np.ones((41, 91), np.float32)
        scores[1:9, 1:9] = .15  # More than 50 offsets from the same upper sprite.
        scores[30:34, 80:84] = .05
        with patch("src.engine.MonsterDetector.cv2.matchTemplate", return_value=scores):
            matches = detector._match_template(np.zeros((80, 130, 3), np.uint8),
                                                np.zeros((40, 40, 3), np.uint8), None,
                                                0, 0, "fixture", "grayscale", 0, 0, 0, 0)
        result = nms(matches, .4)
        self.assertEqual(len(result), 2)
        self.assertTrue(any(m["position"] == (80, 30) for m in result))

    def test_vectorized_nms_preserves_greedy_results_for_crowded_and_overlapping_boxes(self):
        rng = np.random.default_rng(36)
        boxes = [{"position": tuple(map(int, rng.integers(0, 200, 2))),
                  "size": tuple(map(int, rng.integers(10, 80, 2))), "score": i / 1000}
                 for i in range(220)]
        def rectangle(m):
            x, y = m["position"]
            h, w = m["size"]
            return x, y, x + w, y + h
        reference = []
        for m in boxes:
            if all(get_iou(rectangle(m), rectangle(other)) < .4 for other in reference):
                reference.append(m)
        self.assertEqual(nms(boxes, .4), reference)

    def test_turn_wait_starts_after_tap_and_does_not_repeat_for_same_direction(self):
        cfg = load_settings(ROOT / "config/no-saved-settings.yaml")
        with patch("src.input.KeyBoardController.threading.Thread.start"):
            keyboard = KeyBoardController(cfg)
        clock = [100.0]
        def tap(key, duration):
            clock[0] += duration
            return True
        keyboard._tap_direction = Mock(side_effect=tap)
        keyboard._press_key_serialized = Mock(return_value=True)
        keyboard.set_command("face_right none attack")
        with patch("src.input.KeyBoardController.time.time", side_effect=lambda: clock[0]):
            keyboard._apply_movement()
            keyboard._apply_action()
            keyboard._press_key_serialized.assert_not_called()
            self.assertAlmostEqual(keyboard._face_direction_until, 100.13)
            clock[0] += .081
            keyboard._apply_movement()
            keyboard._apply_action()
        keyboard._tap_direction.assert_called_once()
        keyboard._press_key_serialized.assert_called_once()


if __name__ == "__main__":
    unittest.main()
