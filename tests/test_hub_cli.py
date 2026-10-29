"""命令行入口的写入守卫：没有 FATFISH_HUB_WRITE=1 就不许改真实记忆库。"""
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from dsh.service import fatfish_hub_cli as cli


class HubCliGuardTest(unittest.TestCase):
    def _run(self, argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        patch = mock.patch.dict(os.environ, env or {}, clear=False)
        with patch, redirect_stdout(out), redirect_stderr(err):
            os.environ.pop("FATFISH_HUB_WRITE", None) if not env else None
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_journal_write_requires_permission(self):
        with mock.patch.object(cli.hub, "journal_write") as writer:
            code, _out, err = self._run(["journal-write", "--day", "2026-10-30", "--content", "x"])
        writer.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("FATFISH_HUB_WRITE", err)

    def test_mood_nudge_requires_permission(self):
        with mock.patch.object(cli.hub, "mood_nudge") as nudge:
            code, _out, _err = self._run(["mood-nudge", "--delta", "0.1"])
        nudge.assert_not_called()
        self.assertEqual(code, 1)

    def test_write_allowed_when_env_set(self):
        with mock.patch.object(cli.hub, "journal_write", return_value={"ok": True}) as writer:
            code, out, _err = self._run(
                ["journal-write", "--day", "2026-10-30", "--content", "今天", "--source", "test"],
                env={"FATFISH_HUB_WRITE": "1"},
            )
        writer.assert_called_once()
        self.assertEqual(code, 0)
        self.assertIn("ok", out)

    def test_read_command_needs_no_permission(self):
        with mock.patch.object(cli.hub, "mood_get", return_value={"scope": "global"}) as reader:
            code, out, _err = self._run(["mood-get"])
        reader.assert_called_once()
        self.assertEqual(code, 0)
        self.assertIn("global", out)


if __name__ == "__main__":
    unittest.main()
