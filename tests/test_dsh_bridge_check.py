"""Tests for the QQ bridge readiness check.

The script must not let "package present" pass as "bridge working": a bundle
with no applied patch, or an empty botQQ, has to show up separately.
"""
import importlib.util
import io
import json
import os
import socket
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dsh_bridge_check", ROOT / "scripts/dsh_bridge_check.py")
bridge_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge_check)

MANAGED = """
- id: dsh-onebot
  name: 'dsh-onebot-qq'
  config:
    mode: reverse
    host: 127.0.0.1
    port: 8643
    accessToken: '10001'
    botQQ: '10001'
"""


def write_profile(home: Path, profile: str, manifest: dict, patch: str) -> Path:
    folder = home / "profiles" / profile
    folder.mkdir(parents=True)
    (folder / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "cordis.patch.yml").write_text(patch, encoding="utf-8")
    return folder


def manifest(with_bridge: bool) -> dict:
    bundles = ["@deepseek-ai/dsh-base"]
    dependencies = {}
    if with_bridge:
        bundles.append(bridge_check.BRIDGE_PACKAGE)
        dependencies[bridge_check.BRIDGE_PACKAGE] = "file:D:/x.tgz"
    return {"dependencies": dependencies, "dsh": {"profile": {"bundles": bundles}}}


def invoke(home: Path, port: int, extra_env: dict | None = None) -> tuple[int, dict]:
    buffer = io.StringIO()
    # 默认不读本机真实的 NapCat 配置，否则测试结果会随机器变化
    env = {"DSH_HOME": str(home), "FATFISH_NAPCAT_CONFIG": str(home / "no-napcat.json")}
    env.update(extra_env or {})
    with mock.patch.dict(os.environ, env, clear=False), redirect_stdout(buffer):
        code = bridge_check.run(profile="desktop", port=port)
    return code, json.loads(buffer.getvalue())


def napcat_json(url: str, token: str) -> str:
    return json.dumps({"network": {"websocketClients": [
        {"name": "dsh", "enable": True, "url": url, "token": token}]}})


class BridgeCheckTests(unittest.TestCase):
    def test_missing_bridge_fails_without_crashing(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            write_profile(home, "desktop", manifest(False), "[]\n")
            code, report = invoke(home, 8643)
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        names = {item["name"]: item["status"] for item in report["items"]}
        self.assertEqual(names["桥已安装"], "FAIL")
        self.assertEqual(names["patch 有 dsh-onebot 段"], "FAIL")

    def test_installed_but_patch_missing_is_still_a_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            write_profile(home, "desktop", manifest(True), "[]\n")
            code, report = invoke(home, 8643)
        self.assertEqual(code, 1)
        names = {item["name"]: item["status"] for item in report["items"]}
        self.assertEqual(names["桥已安装"], "PASS")
        self.assertEqual(names["patch 有 dsh-onebot 段"], "FAIL")

    def test_listening_bridge_passes_and_botqq_is_surfaced(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                write_profile(home, "desktop", manifest(True), MANAGED.replace("8643", str(port)))
                code, report = invoke(home, port)
        self.assertEqual(code, 0, report)
        names = {item["name"]: item for item in report["items"]}
        self.assertEqual(names["端口在监听"]["status"], "PASS")
        self.assertIn("10001", names["botQQ 已填写"]["detail"])

    def test_empty_botqq_warns_but_does_not_fail_alone(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                patch = MANAGED.replace("8643", str(port)).replace("'10001'", "''")
                write_profile(home, "desktop", manifest(True), patch)
                code, report = invoke(home, port)
        self.assertEqual(code, 0, report)
        names = {item["name"]: item["status"] for item in report["items"]}
        self.assertEqual(names["botQQ 已填写"], "WARN")

    def test_port_mismatch_is_reported(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                write_profile(home, "desktop", manifest(True), MANAGED)
                code, report = invoke(home, port)
        self.assertEqual(code, 1)
        names = {item["name"]: item["status"] for item in report["items"]}
        self.assertEqual(names["端口一致"], "FAIL")

    def test_entry_parser_ignores_nested_insert_block(self):
        nested = """
- insert:
    - id: dsh-onebot
      name: 'dsh-onebot-qq'
"""
        self.assertEqual(bridge_check.onebot_entry(nested), {})

    def test_entry_parser_reads_top_level_values(self):
        entry = bridge_check.onebot_entry(MANAGED)
        self.assertEqual(entry["mode"], "reverse")
        self.assertEqual(entry["port"], "8643")
        self.assertEqual(entry["botQQ"], "10001")

    def test_trace_file_is_surfaced_when_present(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                write_profile(home, "desktop", manifest(True), MANAGED.replace("8643", str(port)))
                trace = home / "media" / "onebot" / "qq-trace.jsonl"
                trace.parent.mkdir(parents=True)
                trace.write_text('{"kind":"connect","ok":true}\n', encoding="utf-8")
                code, report = invoke(home, port)
        names = {item["name"]: item for item in report["items"]}
        self.assertEqual(names["桥追踪文件"]["status"], "PASS")
        self.assertIn("connect", names["桥追踪文件"]["detail"])

    def test_missing_trace_is_a_warning_not_a_failure(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                write_profile(home, "desktop", manifest(True), MANAGED.replace("8643", str(port)))
                code, report = invoke(home, port)
        self.assertEqual(code, 0, report)
        names = {item["name"]: item["status"] for item in report["items"]}
        self.assertEqual(names["桥追踪文件"], "WARN")


if __name__ == "__main__":
    unittest.main()

class NapCatAlignmentTests(unittest.TestCase):
    """桥与 NapCat 的 token 不一致时连接被拒且两边都不报错，必须能查出来。"""

    def _profile(self, home: Path, patch_text: str) -> None:
        write_profile(home, "desktop", manifest(True), patch_text)

    def test_matching_token_and_port_pass(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                self._profile(home, MANAGED.replace("8643", str(port)))
                napcat = home / "onebot11_1.json"
                napcat.write_text(napcat_json(f"ws://127.0.0.1:{port}/ws", "10001"), encoding="utf-8")
                code, report = invoke(home, port, {"FATFISH_NAPCAT_CONFIG": str(napcat)})
        self.assertEqual(code, 0, report)
        names = {i["name"]: i["status"] for i in report["items"]}
        self.assertEqual(names["NapCat token 一致"], "PASS")
        self.assertEqual(names["NapCat 指向桥端口"], "PASS")

    def test_token_mismatch_fails_even_when_port_matches(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                self._profile(home, MANAGED.replace("8643", str(port)))
                napcat = home / "onebot11_1.json"
                napcat.write_text(napcat_json(f"ws://127.0.0.1:{port}/ws", "wrong-token"), encoding="utf-8")
                code, report = invoke(home, port, {"FATFISH_NAPCAT_CONFIG": str(napcat)})
        self.assertEqual(code, 1)
        names = {i["name"]: i["status"] for i in report["items"]}
        self.assertEqual(names["NapCat token 一致"], "FAIL")

    def test_wrong_port_fails(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                self._profile(home, MANAGED.replace("8643", str(port)))
                napcat = home / "onebot11_1.json"
                napcat.write_text(napcat_json("ws://127.0.0.1:6199/ws", "10001"), encoding="utf-8")
                code, report = invoke(home, port, {"FATFISH_NAPCAT_CONFIG": str(napcat)})
        self.assertEqual(code, 1)
        names = {i["name"]: i["status"] for i in report["items"]}
        self.assertEqual(names["NapCat 指向桥端口"], "FAIL")

    def test_missing_napcat_config_is_only_a_warning(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                self._profile(home, MANAGED.replace("8643", str(port)))
                code, report = invoke(home, port, {"FATFISH_NAPCAT_CONFIG": str(home / "nope.json")})
        self.assertEqual(code, 0, report)
        names = {i["name"]: i["status"] for i in report["items"]}
        self.assertEqual(names["NapCat 配置"], "WARN")