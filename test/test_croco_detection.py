"""Exercise real sprites and cropped search bounds without game capture or input."""
import unittest

import cv2
import numpy as np

from src.engine.MonsterDetector import MonsterDetector
from src.launcher_settings import ROOT
from src.utils.common import load_yaml, override_cfg


class CrocoDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = override_cfg(load_yaml(str(ROOT / "config/config_default.yaml")),
                           load_yaml(str(ROOT / "config/config_croco.yaml")))
        cls.detector = MonsterDetector(cfg)
        assert cls.detector.load_monster_images()
        cls.detector.loc_player = (-1000, -1000)

    def sprite(self, path, flip=False):
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        h, w = image.shape[:2]
        image = cv2.resize(image, (int(w * 1.4), int(h * 1.4)), interpolation=cv2.INTER_NEAREST)
        return cv2.flip(image, 1) if flip else image

    def paste(self, image, x, y):
        h, w = image.shape[:2]
        patch = self.detector.img_frame[y:y+h, x:x+w]
        mask = image[:, :, 3] > 128
        patch[mask] = image[:, :, :3][mask]

    def detect(self, top_left=(0, 0), bottom_right=(700, 400)):
        return self.detector.get_monsters_in_range(top_left, bottom_right)

    def has_match(self, matches, x, y):
        return any(abs(m["position"][0] - x) <= 2 and abs(m["position"][1] - y) <= 2
                   for m in matches)

    def test_all_poses_and_directions_in_large_color_search(self):
        paths = sorted((ROOT / "monster/hei_e_yu").glob("*.png"))
        self.assertEqual(len(paths), 8)
        self.assertTrue(any(p.name == "hit1_0.png" for p in paths))
        for path in paths:
            for flip in (False, True):
                with self.subTest(pose=path.name, flip=flip):
                    self.detector.img_frame = np.full((400, 700, 3), (110, 155, 95), dtype=np.uint8)
                    self.paste(self.sprite(path, flip), 283, 171)
                    self.assertTrue(self.has_match(self.detect(), 283, 171))

    def test_sprite_crossing_each_search_edge_is_detected_but_outside_sprite_is_excluded(self):
        sprite = self.sprite(ROOT / "monster/hei_e_yu/stand_0.png")
        h, w = sprite.shape[:2]
        x, y = 283, 171
        bounds = [((x + w // 2, y - 10), (x + w + 20, y + h + 10)),
                  ((x - 20, y - 10), (x + w // 2, y + h + 10)),
                  ((x - 20, y + h // 2), (x + w + 20, y + h + 10)),
                  ((x - 20, y - 10), (x + w + 20, y + h // 2))]
        self.detector.img_frame = np.full((400, 700, 3), (110, 155, 95), dtype=np.uint8)
        self.paste(sprite, x, y)
        self.paste(sprite, 40, y)
        for top_left, bottom_right in bounds:
            with self.subTest(bounds=(top_left, bottom_right)):
                matches = self.detect(top_left, bottom_right)
                self.assertTrue(self.has_match(matches, x, y))
                self.assertFalse(self.has_match(matches, 40, y))

    def test_plain_backgrounds_do_not_trigger_color_proposals(self):
        for color in (0, 150, 255):
            self.detector.img_frame = np.full((400, 700, 3), color, dtype=np.uint8)
            self.assertEqual(self.detect(), [])


if __name__ == "__main__":
    unittest.main()
