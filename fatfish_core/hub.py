"""FatFish 中枢：把心情、知识图谱、日记和聊天统计收成纯函数。

MCP 服务与命令行共用这一层，不重复实现存储逻辑：
- 心情沿用 ``fatfish_core.mood.MoodStore``（0-100，50 中性，按小时回归）。
- 知识沿用 ``fatfish_core.knowledge_graph.KnowledgeGraph``（只读公开集合）。
- 日记直接读写记忆库现有 ``journals`` 表（同一天同一来源覆盖更新）。
- 说话习惯沿用 ``fatfish_core.learning.extract_terms``（本地 n-gram，不调模型）。

约束：
- 数据库路径只从 ``FATFISH_MEMORY_DB`` 取，知识集合从 ``FATFISH_LORE_COLLECTION`` 取。
- 读函数返回 JSON 可序列化的 dict；数据库缺失或损坏时带 ``error`` 字段，不抛异常。
- 写函数在数据库缺失时抛 ``FileNotFoundError``，参数非法时抛 ``ValueError``，
  由 MCP 服务或命令行转成错误 JSON。
- 文件与输出一律 UTF-8，避免 Windows 默认 GBK 控制台把中文打成乱码。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .knowledge_graph import KnowledgeGraph
from .learning import extract_terms
from .mood import NEUTRAL, MoodStore, label_for

DEFAULT_COLLECTION = "lore"
MAX_REASON_CHARS = 80
MAX_JOURNAL_CHARS = 8000
MAX_SAMPLES = 5
MAX_SAMPLE_CHARS = 80
MAX_SCOPE_CHARS = 40
MAX_SOURCE_CHARS = 40
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---- 路径与通用小工具 ---------------------------------------------------------


def memory_db_path() -> Path | None:
    """从环境变量取记忆库路径；未配置时返回 None。"""
    raw = os.environ.get("FATFISH_MEMORY_DB", "").strip()
    return Path(raw).expanduser() if raw else None


def lore_collection() -> str:
    return os.environ.get("FATFISH_LORE_COLLECTION", DEFAULT_COLLECTION).strip() or DEFAULT_COLLECTION


def _require_db() -> Path:
    """写入口用：路径未配置或文件不存在都明确报错，不顺手创建空库。"""
    path = memory_db_path()
    if path is None:
        raise FileNotFoundError("FATFISH_MEMORY_DB 未设置")
    if not path.is_file():
        raise FileNotFoundError(f"记忆库文件不存在：{path}")
    return path


def _today() -> str:
    return date.today().isoformat()


def _clamp_int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _error_text(error: BaseException) -> str:
    text = str(error).strip()
    if isinstance(error, FileNotFoundError):
        return text or "记忆库不存在"
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


def _with_error(payload: dict, error: BaseException) -> dict:
    result = dict(payload)
    result["error"] = _error_text(error)
    return result


def _check_day(day: str) -> str:
    """校验 YYYY-MM-DD；只有参数校验允许抛 ValueError。"""
    value = str(day or "").strip()
    if not DAY_RE.match(value):
        raise ValueError("day 必须是 YYYY-MM-DD（例如 2026-10-30）")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"day 不是有效日期：{value}") from error
    return value


def _ranked(counter: Counter) -> dict[str, int]:
    """按次数倒序、同次数按名称排序，保证输出稳定。"""
    return {key: count for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))}


def _empty_mood(scope: str) -> dict:
    label = label_for(NEUTRAL)
    return {
        "scope": scope,
        "value": NEUTRAL,
        "label": label,
        "reason": "",
        "updated_at": None,
        "description": f"现在心情：{label}",
    }


# ---- 心情 ---------------------------------------------------------------------
#
# 心情只留一份真源：``dsh-feiyu-mood`` 的 ``~/.dsh/feiyu-mood/state.json``。
# 它每轮用模型判一次、在设置页看得见、还会按小时自己平复；hub 的 MoodStore
# 是 AstrBot 时代留下的第二份。两边各判一次就会出现「她此刻到底什么心情」
# 两个答案，所以这里定死一条规则：
#   · 读 → 先看 feiyu-mood，读得到就用它（带 source 标记）
#   · 写 → 两边都写：MoodStore 保留历史，feiyu 那份同步，避免页面和工具打架
FEIYU_STATE = Path.home() / ".dsh" / "feiyu-mood" / "state.json"
MOOD_PENDING = Path(__file__).resolve().parents[1] / "data" / "dsh" / "mood-pending.json"


def _feiyu_path() -> Path:
    """feiyu-mood 状态文件位置；测试用 FATFISH_FEIYU_STATE 指到临时目录。"""
    override = os.environ.get("FATFISH_FEIYU_STATE")
    return Path(override) if override else FEIYU_STATE


def _mood_pending_path() -> Path:
    override = os.environ.get("FATFISH_MOOD_PENDING")
    return Path(override) if override else MOOD_PENDING


def _feiyu_store() -> tuple[dict, str] | None:
    """读 feiyu-mood 的那一份心情；文件没有/格式不对就返回 None（不抛异常）。"""
    try:
        raw = json.loads(_feiyu_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 数据层不能因为另一个插件没装就报错
        return None
    moods = raw.get("moods")
    if not isinstance(moods, dict) or not moods:
        return None
    key = raw.get("lastActive")
    if not isinstance(key, str) or key not in moods:
        key = next(iter(moods))
    state = moods.get(key)
    return (state, key) if isinstance(state, dict) else None


def _mood_queue(value: float, reason: str) -> None:
    """把一次调整排进待办，交给宿主里的 node 落进 feiyu-mood。

    沙盒里的 python 没有 ``~/.dsh/feiyu-mood`` 的写权限（新建和覆盖都是
    PermissionError），所以这里只写自己写得了的 ``data/dsh/mood-pending.json``，
    由 ``dsh/control/moodsync.mjs`` 在每个 tick 合并进真源后删除。
    """
    path = _mood_pending_path()
    try:
        entries: list[dict] = []
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                entries = [item for item in loaded if isinstance(item, dict)]
        entries.append({"value": round(float(value), 2), "reason": reason[:120], "at": int(time.time() * 1000)})
        del entries[:-50]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 - 排不进队列只影响页面数字，不影响工具本身
        return


def _mood_updated_at(db: Path, scope: str) -> float | None:
    with closing(sqlite3.connect(db, timeout=10)) as conn:
        row = conn.execute("SELECT updated_at FROM mood WHERE scope=?", (scope,)).fetchone()
    return float(row[0]) if row else None


def mood_get(scope: str = "global") -> dict:
    """读当前心情；feiyu-mood 在就用它，缺失的资料库降级成中性心情并附 error。"""
    scope = str(scope or "").strip()[:MAX_SCOPE_CHARS] or "global"
    feiyu = _feiyu_store()
    if feiyu is not None:
        state, key = feiyu
        try:
            value = float(state.get("mood", NEUTRAL))
        except (TypeError, ValueError):
            value = NEUTRAL
        moment = state.get("updatedAt")
        return {
            "scope": scope,
            "value": value,
            "label": label_for(value),
            "reason": str(state.get("lastReason") or ""),
            "updated_at": float(moment) / 1000 if isinstance(moment, (int, float)) else None,
            "description": f"现在心情：{label_for(value)}",
            "source": f"feiyu-mood:{key}",
        }
    try:
        db = _require_db()
        store = MoodStore(db)
        state = store.get(scope)
    except Exception as error:  # noqa: BLE001 - 读接口不能把异常抛给 MCP
        return _with_error(_empty_mood(scope), error)
    return {
        "scope": scope,
        "value": state["value"],
        "label": state["label"],
        "reason": state["reason"],
        "updated_at": _mood_updated_at(db, scope),
        "description": store.describe(scope),
        "source": "fatfish-memory",
    }


def mood_nudge(delta: float, reason: str = "", scope: str = "global") -> dict:
    """调整心情：delta 限制在 [-1,1]，reason 截断 80 字；写库失败会抛异常。"""
    try:
        step = float(delta)
    except (TypeError, ValueError) as error:
        raise ValueError(f"delta 必须是数字：{delta!r}") from error
    if step != step:  # NaN
        raise ValueError("delta 不能是 NaN")
    step = max(-1.0, min(1.0, step))
    scope = str(scope or "").strip()[:MAX_SCOPE_CHARS] or "global"
    note = str(reason or "").strip()[:MAX_REASON_CHARS]
    store = MoodStore(_require_db())
    # 以「统一后的当前心情」为基准算目标值：feiyu-mood 在就用它，
    # 否则用 MoodStore。这样 delta 不会因为两边基线不同（70 vs 50）而漂。
    try:
        base = float(mood_get(scope).get("value", NEUTRAL))
    except (TypeError, ValueError):
        base = NEUTRAL
    target = max(0.0, min(100.0, base + step))
    current = float(store.get(scope)["value"])
    store.nudge(target - current, reason=note, scope=scope)
    # 沙盒里的 python 写不了 feiyu-mood 的状态文件，排进待办让宿主里的
    # dsh/control/moodsync.mjs 落盘，保证设置页与工具读到同一个数。
    _mood_queue(target, note)
    return mood_get(scope)


# ---- 知识图谱 -----------------------------------------------------------------


def _document_digests(db: Path, collection: str, sources: set[str]) -> dict[str, str]:
    sources = {source for source in sources if source}
    if not sources:
        return {}
    marks = ",".join("?" for _ in sources)
    with closing(sqlite3.connect(db, timeout=10)) as conn:
        rows = conn.execute(
            f"SELECT source,digest FROM graph_documents WHERE collection=? AND source IN ({marks})",
            (collection, *sorted(sources)),
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def lore_search(query: str, limit: int = 5) -> dict:
    """按知识图谱关系检索，按来源文档去重后返回出处与摘要指纹。

    ``limit`` 是来源文档数；图谱关系可能多条指向同一份文档，所以先多取关系
    （KnowledgeGraph.query 单次最多 30 条），去重后再截到 limit，尽量凑满。
    """
    term = str(query or "").strip()
    fallback = {"count": 0, "items": []}
    if not term:
        return fallback
    per = _clamp_int(limit, 5, 1, 30)
    collection = lore_collection()
    try:
        db = _require_db()
        rows = KnowledgeGraph(db).query(term, collection=collection, limit=30)
        digests = _document_digests(db, collection, {row.get("source") or "" for row in rows})
        items: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            source = row.get("source") or ""
            if source in seen:
                continue
            seen.add(source)
            items.append({
                "title": row.get("title") or "",
                "digest": digests.get(source, ""),
                "source": source,
                "source_url": row.get("source_url") or "",
                "collection": collection,
            })
            if len(items) >= per:
                break
        return {"count": len(items), "items": items}
    except Exception as error:  # noqa: BLE001 - 读接口不能把异常抛给 MCP
        return _with_error(fallback, error)


def lore_context(query: str, max_chars: int = 1200) -> dict:
    """取知识图谱证据文本（带来源），最多 max_chars 字。"""
    term = str(query or "").strip()
    fallback = {"query": term, "context": ""}
    if not term:
        return fallback
    chars = _clamp_int(max_chars, 1200, 1, 8000)
    try:
        context = KnowledgeGraph(_require_db()).context(term, collection=lore_collection(), max_chars=chars)
        return {"query": term, "context": context}
    except Exception as error:  # noqa: BLE001
        return _with_error(fallback, error)


# ---- 日记 ---------------------------------------------------------------------


def journal_write(day: str, content: str, source: str = "dsh") -> dict:
    """写日记：同一天同一来源覆盖更新，不产生重复行；content 上限 8000 字。"""
    value = _check_day(day)
    body = str(content or "").strip()
    if not body:
        raise ValueError("content 不能为空")
    body = body[:MAX_JOURNAL_CHARS]
    label = str(source or "").strip()[:MAX_SOURCE_CHARS] or "dsh"
    db = _require_db()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(sqlite3.connect(db, timeout=10)) as conn, conn:
        row = conn.execute(
            "SELECT id FROM journals WHERE day=? AND source=? ORDER BY id LIMIT 1", (value, label)
        ).fetchone()
        if row:
            conn.execute("UPDATE journals SET content=?, created_at=? WHERE id=?", (body, stamp, row[0]))
            row_id = int(row[0])
        else:
            row_id = int(conn.execute(
                "INSERT INTO journals(day,content,source,created_at) VALUES(?,?,?,?)",
                (value, body, label, stamp),
            ).lastrowid)
    return {"ok": True, "day": value, "id": row_id}


def journal_recent(days: int = 7) -> dict:
    """读最近 days 天（含今天）的日记，按 day 倒序。"""
    span = _clamp_int(days, 7, 1, 3650)
    fallback = {"count": 0, "items": []}
    try:
        db = _require_db()
        cutoff = (date.fromisoformat(_today()) - timedelta(days=span - 1)).isoformat()
        with closing(sqlite3.connect(db, timeout=10)) as conn:
            rows = conn.execute(
                "SELECT day,content,source FROM journals WHERE day >= ?"
                " ORDER BY day DESC, created_at DESC, id DESC",
                (cutoff,),
            ).fetchall()
        items = [{"day": row[0], "content": row[1], "source": row[2] or ""} for row in rows]
        return {"count": len(items), "items": items}
    except Exception as error:  # noqa: BLE001
        return _with_error(fallback, error)


# ---- 当天统计与说话习惯 -------------------------------------------------------


def day_digest(day: str) -> dict:
    """统计某天的事件条数、范围、类型和内容片段（按 created_at 的日期部分）。"""
    value = _check_day(day)
    fallback = {"day": value, "events": 0, "scopes": {}, "kinds": {}, "samples": []}
    try:
        db = _require_db()
        with closing(sqlite3.connect(db, timeout=10)) as conn:
            rows = conn.execute(
                "SELECT scope,kind,content FROM events WHERE substr(created_at,1,10)=? ORDER BY id",
                (value,),
            ).fetchall()
        scopes = Counter(row[0] or "" for row in rows)
        kinds = Counter(row[1] or "" for row in rows)
        samples = [
            str(row[2] or "").strip()[:MAX_SAMPLE_CHARS]
            for row in rows
            if str(row[2] or "").strip()
        ][:MAX_SAMPLES]
        return {
            "day": value,
            "events": len(rows),
            "scopes": _ranked(scopes),
            "kinds": _ranked(kinds),
            "samples": samples,
        }
    except Exception as error:  # noqa: BLE001
        return _with_error(fallback, error)


def style_terms(days: int = 7, limit: int = 12) -> dict:
    """从今天之前 days 天的聊天里抽高频说法（本地 n-gram，不调模型）。"""
    span = _clamp_int(days, 7, 1, 365)
    top = _clamp_int(limit, 12, 1, 50)
    fallback = {"count": 0, "terms": []}
    try:
        db = _require_db()
        end = date.fromisoformat(_today())
        start = (end - timedelta(days=span)).isoformat()
        with closing(sqlite3.connect(db, timeout=10)) as conn:
            rows = conn.execute(
                "SELECT content FROM events WHERE substr(created_at,1,10) >= ?"
                " AND substr(created_at,1,10) < ?",
                (start, end.isoformat()),
            ).fetchall()
        terms = extract_terms([str(row[0] or "") for row in rows], max_terms=top)
        return {"count": len(terms), "terms": terms}
    except Exception as error:  # noqa: BLE001
        return _with_error(fallback, error)
