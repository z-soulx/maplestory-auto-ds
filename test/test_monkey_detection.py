"""Offline integration checks; no game capture or input is started."""
import unittest

import cv2
import numpy as np

from src.engine.MonsterDetector import MonsterDetector
from src.launcher_settings import ROOT
from src.utils.common import load_yaml, override_cfg


class MonkeyDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = override_cfg(load_yaml(str(ROOT / "config/config_default.yaml")),
                           load_yaml(str(ROOT / "config/config_monkeys.yaml")))
        cls.detector = MonsterDetector(cfg)
        assert cls.detector.load_monster_images()
        cls.detector.loc_player = (-1000, -1000)

    def detect(self, frame):
        self.detector.img_frame = frame
        return self.detector.get_monsters_in_range((0, 0), (frame.shape[1], frame.shape[0]))

    def test_both_species_all_frames_and_directions_at_configured_scale(self):
        for name in ("hou_zi", "jiang_shi_hou_zi"):
            self.assertEqual(len(self.detector.monsters_info[name]), 10)
            for path in sorted((ROOT / "monster" / name).glob("*.png")):
                sprite = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                h, w = sprite.shape[:2]
                sprite = cv2.resize(sprite, (int(w * 1.4), int(h * 1.4)),
                                    interpolation=cv2.INTER_NEAREST)
                for flip in (False, True):
                    with self.subTest(name=name, frame=path.name, flip=flip):
                        oriented = cv2.flip(sprite, 1) if flip else sprite
                        frame = np.full((160, 200, 3), (110, 155, 95), dtype=np.uint8)
                        h, w = oriented.shape[:2]
                        region = frame[35:35 + h, 60:60 + w]
                        mask = oriented[:, :, 3] > 128
                        region[mask] = oriented[:, :, :3][mask]
                        matches = self.detect(frame)
                        self.assertTrue(any(m["name"] == name and
                                            abs(m["position"][0] - 60) <= 2 and
                                            abs(m["position"][1] - 35) <= 2
                                            for m in matches), matches)

    def test_plain_background_is_not_a_monkey(self):
        self.assertEqual(self.detect(np.full((160, 200, 3), 150, dtype=np.uint8)), [])


if __name__ == "__main__":
    unittest.main()
