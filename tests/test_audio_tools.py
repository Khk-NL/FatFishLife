import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fatfish_core.audio_tools import ensure_ffmpeg_on_path
from fatfish_video.renderer import RenderError


class AudioToolsTests(unittest.TestCase):
    def test_existing_decoder_is_preserved(self):
        with patch('fatfish_core.audio_tools.shutil.which', return_value='/existing/ffmpeg'), patch.dict(os.environ, {'PATH': 'original'}):
            self.assertEqual(ensure_ffmpeg_on_path(), Path('/existing/ffmpeg'))
            self.assertEqual(os.environ['PATH'], 'original')

    def test_missing_path_reuses_bundled_tool_and_can_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'ffmpeg.exe'
            executable.touch()
            with patch('fatfish_core.audio_tools.shutil.which', side_effect=[None, str(executable)]), patch('fatfish_video.renderer._resolve_tool', return_value=executable), patch.dict(os.environ, {'PATH': 'original'}):
                self.assertEqual(ensure_ffmpeg_on_path(), executable)
                self.assertTrue(os.environ['PATH'].endswith(os.pathsep + 'original'))
                updated = os.environ['PATH']
                self.assertEqual(ensure_ffmpeg_on_path(), executable)
                self.assertEqual(os.environ['PATH'], updated)

    def test_missing_binary_keeps_path_and_reports_unavailable(self):
        with patch('fatfish_core.audio_tools.shutil.which', return_value=None), patch('fatfish_video.renderer._resolve_tool', side_effect=RenderError('missing')), patch.dict(os.environ, {'PATH': 'original'}), self.assertLogs('fatfish_core.audio_tools', level='WARNING'):
            self.assertIsNone(ensure_ffmpeg_on_path())
            self.assertEqual(os.environ['PATH'], 'original')
