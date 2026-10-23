import tempfile
import unittest
from pathlib import Path

from fatfish_core.mood import NEUTRAL, MoodStore, label_for, react_to


class MoodTest(unittest.TestCase):
    def test_default_is_neutral(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MoodStore(Path(tmp) / "mood.db")
            self.assertEqual(store.get()["value"], NEUTRAL)

    def test_nudge_changes_value_and_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MoodStore(Path(tmp) / "mood.db")
            store.nudge(-30, "被呛了")
            state = store.get()
            self.assertLess(state["value"], NEUTRAL)
            self.assertEqual(state["label"], "蔫蔫的")

    def test_nudge_is_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MoodStore(Path(tmp) / "mood.db")
            store.nudge(200)
            self.assertEqual(store.get()["value"], 100.0)
            store.nudge(-500)
            self.assertEqual(store.get()["value"], 0.0)

    def test_react_positive_and_negative(self):
        self.assertGreater(react_to("苹果乐真可爱", addressed=True), 0)
        self.assertLess(react_to("滚开", addressed=True), 0)

    def test_label_thresholds(self):
        self.assertEqual(label_for(90), "很兴奋")
        self.assertEqual(label_for(10), "蔫蔫的")


if __name__ == "__main__":
    unittest.main()
