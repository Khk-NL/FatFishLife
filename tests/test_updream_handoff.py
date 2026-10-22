from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fatfish_video.project import load_project
from fatfish_video.renderer import RenderError, find_tools
from scripts.updream_handoff import export_storyboard, verify_export

ROOT = Path(__file__).resolve().parent.parent


class UpdreamHandoffTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_export_contains_portable_assets_and_exact_timeline(self):
        source = ROOT / "examples/single.json"
        project = load_project(source)
        destination = self.root / "handoff"
        result = export_storyboard(source, destination)
        self.assertEqual(result["status"], "prepared_for_updream")
        self.assertFalse(result["uploaded"])
        manifest = json.loads((destination / "handoff.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["duration"], project.duration)
        self.assertAlmostEqual(sum(scene["duration"] for scene in manifest["scenes"]), project.duration)
        self.assertFalse(manifest["rights_confirmed"])
        for key, asset in project.assets.items():
            copied = destination / manifest["assets"][key]["path"]
            self.assertEqual(copied.read_bytes(), asset.path.read_bytes())
        self.assertIn(project.scenes[0].captions[0].text, (destination / "storyboard.md").read_text(encoding="utf-8"))

    def test_export_does_not_overwrite_existing_directory(self):
        destination = self.root / "existing"
        destination.mkdir()
        marker = destination / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            export_storyboard(ROOT / "examples/single.json", destination)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_export_works_when_directory_rename_is_not_permitted(self):
        destination = self.root / "handoff"
        with patch.object(Path, "rename", side_effect=PermissionError("directory rename denied")):
            result = export_storyboard(ROOT / "examples/single.json", destination)
        self.assertEqual(result["status"], "prepared_for_updream")
        manifest = json.loads((destination / "handoff.json").read_text(encoding="utf-8"))
        for asset in manifest["assets"].values():
            self.assertTrue((destination / asset["path"]).is_file())

    def test_invalid_video_does_not_leave_validated_report(self):
        source = self.root / "invalid.mp4"
        source.write_text("not a video", encoding="utf-8")
        report = self.root / "invalid.json"
        with self.assertRaises(RenderError):
            verify_export(source, report)
        self.assertFalse(report.exists())

    def test_exported_video_is_fully_decoded_without_publishing(self):
        ffmpeg, _ = find_tools()
        source = self.root / "export.mp4"
        subprocess.run([str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=0.2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True)
        report = self.root / "verified.json"
        result = verify_export(source, report)
        self.assertEqual(result["status"], "validated")
        self.assertTrue(result["fully_decoded"])
        self.assertFalse(result["published"])
        self.assertEqual((result["width"], result["height"]), (320, 180))
        self.assertAlmostEqual(result["duration"], 0.2, places=2)
        original = report.read_bytes()
        with self.assertRaises(FileExistsError):
            verify_export(source, report)
        self.assertEqual(report.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
