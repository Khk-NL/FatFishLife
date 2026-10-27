"""脱敏观察：迁移后出问题时能查，但日志里不能有凭据和隐私。

三类处理：
- 凭据（key/token/cookie/密码）：只留长度和前缀，其余掩码
- 号码（QQ 号、UID）：中间四位掩码，保留两端便于对账
- 路径：保留末两段，前面的目录名替换为 ~

只写本地文件，不发送、不采集环境变量全量内容。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

DEFAULT_LOG = Path(os.environ.get("FATFISH_LOG_FILE") or "logs/fatfish-runtime.jsonl")

# key=value / "key": "value" / Bearer xxx
_SECRET_KEYS = r"(?:api[_-]?key|token|secret|password|passwd|cookie|authorization|refresh[_-]?token|access[_-]?token|client[_-]?secret)"
_SECRET_PATTERNS = [
    re.compile(rf"(?i)({_SECRET_KEYS})(\s*[=:]\s*)([^\s,;&\"'}}]+)"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]{8,})"),
    re.compile(r"(sk-[A-Za-z0-9]{4})[A-Za-z0-9]{10,}"),
]
# 键名本身就是凭据，整段掩码，不做局部保留；兼容 key=value 和 "key": "value"
_SECRET_FIELD = re.compile(
    r"(?i)(api[_-]?key|apikey|token|secret|password|passwd|cookie|authorization|"
    r"refresh[_-]?token|access[_-]?token|client[_-]?secret|key)(\"?\s*[=:]\s*\"?)([^\s,;&\"'}]+)"
)
# Authorization: Bearer xxx 单独处理，避免只掩到 Bearer 就停
_BEARER = re.compile(r"(?i)(authorization\s*[=:]\s*\"?\s*bearer\s+)([A-Za-z0-9._\-]{8,})")
_QQ = re.compile(r"\b([1-9][0-9]{3})([0-9]{3,7})([0-9]{3})\b")
_WIN_PATH = re.compile(r"([A-Za-z]:\\(?:[^\\\s\"']+\\+)+)([^\\\s\"']+)")
_PHONE = re.compile(r"\b(1[3-9][0-9])[0-9]{4}([0-9]{4})\b")
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-]{2})[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def redact(value, *, keep_numbers: bool = False) -> str:
    """把一段文本里的凭据、号码、路径掩码。keep_numbers 用于测试对账。"""
    text = str(value or "")

    # Authorization 先处理，否则会被 _SECRET_FIELD 抢先只掩到 Bearer
    text = _BEARER.sub(lambda m: f"{m.group(1)}***{len(m.group(2))}", text)

    # 再按「键=值」整段掩码，键名本身是凭据时一个字符都不保留
    text = _SECRET_FIELD.sub(
        lambda m: f"{m.group(1)}{m.group(2)}***{len(m.group(3))}", text
    )

    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}***{len(m.group(3))}", text)
        else:
            text = pattern.sub(lambda m: f"{m.group(1)}***{len(m.group(2))}", text)

    if not keep_numbers:
        text = _QQ.sub(lambda m: f"{m.group(1)}***{m.group(3)}", text)
        text = _PHONE.sub(lambda m: f"{m.group(1)}****{m.group(2)}", text)
        text = _EMAIL.sub(lambda m: f"{m.group(1)}***{m.group(2)}", text)

    # 路径只留最后两段，避免暴露用户名和目录结构
    def shorten(match: re.Match) -> str:
        parts = [p for p in match.group(0).split("\\") if p]
        tail = "\\".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        return "~\\" + tail

    text = _WIN_PATH.sub(shorten, text)
    return text


def event(name: str, **fields) -> None:
    """写一行脱敏后的结构化日志；失败不影响主流程。"""
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": name}
    for key, value in fields.items():
        if key.lower() in ("api_key", "apikey", "token", "secret", "password", "cookie", "key", "auth"):
            record[key] = f"***{len(str(value))}"
        else:
            record[key] = redact(value) if isinstance(value, str) else value
    try:
        path = Path(os.environ.get("FATFISH_LOG_FILE") or DEFAULT_LOG)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def summary(path: str | Path | None = None) -> dict:
    """给验收用：统计日志条数，确认没有未脱敏的凭据。"""
    target = Path(path or os.environ.get("FATFISH_LOG_FILE") or DEFAULT_LOG)
    if not target.is_file():
        return {"exists": False, "lines": 0, "leaks": 0}
    leaks = 0
    lines = 0
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            lines += 1
            if re.search(rf"(?i){_SECRET_KEYS}\s*[=:]\s*[A-Za-z0-9_\-]{{12,}}", line):
                leaks += 1
    return {"exists": True, "lines": lines, "leaks": leaks}
