"""FatFish 记忆薄服务：stdio JSON-RPC，供 DSH(Node) 调用。

设计约束（对应迁移方案 §3.2）：
- 数据库路径只从环境变量 FATFISH_MEMORY_DB 取，请求里不能指定路径。
- 只暴露白名单方法，不接受任意 SQL、任意表名。
- 每条请求带 request_id，响应原样带回，便于宿主对账。
- 默认只读模式可启动（FATFISH_SERVICE_READONLY=1），P2 阶段先读后写。

协议：一行一个 JSON。
请求  {"id":1,"method":"recall","params":{"query":"...","scopes":["public"],"limit":5}}
响应  {"id":1,"ok":true,"result":[...]}
错误  {"id":1,"ok":false,"error":{"code":"bad_method","message":"..."}}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fatfish_core import MemoryStore  # noqa: E402
from fatfish_core.extract import extract_candidates, promote_repeated, stats as candidate_stats  # noqa: E402

MAX_LIMIT = 50


class ServiceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def db_path() -> Path:
    value = os.environ.get("FATFISH_MEMORY_DB", "").strip()
    if not value:
        raise ServiceError("no_db", "FATFISH_MEMORY_DB is not set")
    path = Path(value).expanduser()
    if not path.is_file():
        raise ServiceError("no_db", "database file missing")
    return path


def readonly() -> bool:
    return os.environ.get("FATFISH_SERVICE_READONLY", "0").strip() == "1"


def _limit(params: dict, default: int = 10) -> int:
    try:
        value = int(params.get("limit", default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(MAX_LIMIT, value))


def _scopes(params: dict) -> tuple[str, ...]:
    raw = params.get("scopes") or ["public"]
    allowed = {"public", "private"}
    scopes = tuple(str(item) for item in raw if str(item) in allowed)
    return scopes or ("public",)


def handle(method: str, params: dict, store: MemoryStore) -> object:
    if method == "recall":
        query = str(params.get("query") or "").strip()
        if not query:
            raise ServiceError("bad_params", "query is required")
        rows = store.recall(
            query,
            scopes=_scopes(params),
            limit=_limit(params),
            conversation=params.get("conversation"),
            conversation_only=bool(params.get("conversation_only")),
        )
        return [
            {"content": r["content"], "kind": r["kind"], "scope": r["scope"], "created_at": r["created_at"]}
            for r in rows
        ]

    if method == "search":
        query = str(params.get("query") or "").strip()
        group_id = str(params.get("group_id") or "")
        return store.search(query, group_id=group_id, limit=_limit(params, 5))

    if method == "recent":
        return [
            {"content": r["content"], "kind": r["kind"], "created_at": r["created_at"]}
            for r in store.recent(scopes=_scopes(params), limit=_limit(params))
        ]

    if method == "get_block":
        label = str(params.get("label") or "persona")
        return store.get_block(label)

    if method == "candidates":
        return store.list_candidates(str(params.get("status") or "candidate"), _limit(params, 15))

    if method == "stats":
        return {"blocks": store.list_blocks(), "candidates": candidate_stats(store)}

    # 写操作在只读模式下统一拒绝
    if readonly():
        raise ServiceError("readonly", "service started read-only")

    if method == "remember":
        content = str(params.get("content") or "").strip()
        if not content:
            raise ServiceError("bad_params", "content is required")
        return {
            "id": store.remember(
                content,
                platform=str(params.get("platform") or "qq"),
                scope=str(params.get("scope") or "private"),
                kind=str(params.get("kind") or "note"),
                session=params.get("session"),
                actor=params.get("actor"),
                admit=False,
            )
        }

    if method == "review":
        status = str(params.get("status") or "")
        try:
            candidate_id = int(params.get("id"))
        except (TypeError, ValueError):
            raise ServiceError("bad_params", "id must be an integer") from None
        ok = store.review_candidate(candidate_id, status, str(params.get("note") or "service"))
        return {"ok": ok}

    if method == "extract":
        raw_since = params.get("since_id")
        try:
            since_id = int(raw_since) if raw_since is not None else 0
        except (TypeError, ValueError):
            since_id = 0
        result = extract_candidates(store, since_id=since_id)
        result["promoted"] = promote_repeated(store)
        result["stats"] = candidate_stats(store)
        return result

    if method == "set_block":
        label = str(params.get("label") or "")
        value = str(params.get("value") or "")
        if label in ("persona",) and not params.get("force"):
            raise ServiceError("readonly_block", "persona block requires explicit force")
        return {
            "ok": store.set_block(
                label,
                value,
                char_limit=params.get("char_limit"),
                read_only=bool(params.get("read_only", True)),
                description=params.get("description"),
                force=bool(params.get("force")),
            )
        }

    raise ServiceError("bad_method", f"unknown method: {method}")


def main() -> int:
    try:
        path = db_path()
    except ServiceError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False))
        return 2
    store = MemoryStore(path)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request_id = None
        try:
            payload = json.loads(line)
            request_id = payload.get("id")
            method = str(payload.get("method") or "")
            result = handle(method, payload.get("params") or {}, store)
            print(json.dumps({"id": request_id, "ok": True, "result": result}, ensure_ascii=False), flush=True)
        except ServiceError as exc:
            print(json.dumps({"id": request_id, "ok": False, "error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False), flush=True)
        except json.JSONDecodeError:
            print(json.dumps({"id": request_id, "ok": False, "error": {"code": "bad_json", "message": "invalid JSON"}}, ensure_ascii=False), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"id": request_id, "ok": False, "error": {"code": "internal", "message": type(exc).__name__}}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
