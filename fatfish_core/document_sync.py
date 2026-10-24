"""Read-only vault mirroring through AstrBot's native KBHelper API."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

EXCLUDED = {".obsidian", ".trash", ".git", "node_modules", ".venv"}
ERROR_TYPES = {
    "KnowledgeBaseUploadError", "UnicodeDecodeError", "PermissionError", "FileNotFoundError",
    "TimeoutError", "HTTPError", "HTTPStatusError", "ClientResponseError", "ClientConnectionError",
    "ValueError", "RuntimeError", "OSError", "ConnectionError", "IntegrityError",
}
ERROR_STAGES = {"parsing", "chunking", "validation", "storage", "metadata", "lookup", "read", "upload", "cleanup"}


def _failure(result: dict, error: Exception, phase: str):
    """Keep diagnostic categories, never exception messages or file identities."""
    stage = getattr(error, "stage", phase)
    stage = stage if stage in ERROR_STAGES else phase
    kind = type(error).__name__
    kind = kind if kind in ERROR_TYPES else "OtherError"
    key = f"{stage}:{kind}"
    cause = error.__cause__
    if cause is not None:
        cause_kind = type(cause).__name__
        key += ":" + (cause_kind if cause_kind in ERROR_TYPES else "OtherError")
    result["failed"] += 1
    result["error_types"][key] = result["error_types"].get(key, 0) + 1


def vault_files(root: Path) -> dict[str, Path]:
    """Do not follow vault links/junctions into unrelated folders."""
    if not root.is_dir():
        raise ValueError("vault_path 需要是已有的文件夹")

    def failed(error):
        raise error

    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
        dirs[:] = [name for name in sorted(dirs) if name not in EXCLUDED and not name.startswith(".")
                   and not _linked(Path(directory) / name)]
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix.lower() not in {".md", ".txt"} or _linked(path):
                continue
            result[path.relative_to(root).as_posix()] = path
    return result


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024))


async def sync_vault(helper, runtime, root: Path, *, limit=25, max_bytes=1_048_576) -> dict:
    """Upload a changed version before removing its old index; keep failed work pending."""
    root = root.resolve(strict=True)
    digest = hashlib.sha256(str(root).casefold().encode()).hexdigest()[:16]
    namespace = "obsidian:" + str(helper.kb.kb_id)
    binding = runtime.get(namespace, "vault")
    if binding and binding != digest:
        raise ValueError("该知识库已绑定其他 vault；请使用新的独立知识库名称")
    files = vault_files(root)
    runtime.set(namespace, "vault", digest)
    manifest = runtime.get(namespace, "files", {})
    result = {"uploaded": 0, "unchanged": 0, "deleted": 0, "failed": 0, "pending": 0, "oversized": 0,
              "empty": 0, "error_types": {}}
    work = 0
    for relative, path in files.items():
        try:
            if path.stat().st_size > max_bytes:
                result["oversized"] += 1
                continue
            content = path.read_bytes()
        except Exception as error:
            _failure(result, error, "read")
            continue
        content_hash = hashlib.sha256(content).hexdigest()
        previous = manifest.get(relative) or {}
        # Empty source notes contain nothing to embed. Do not send zero vectors or
        # count them as failed uploads. If a note was cleared, remove its old index.
        if not content.strip():
            result["empty"] += 1
            if previous:
                try:
                    for old_id in [previous["doc_id"], *previous.get("retired", [])]:
                        await helper.delete_document(old_id)
                    del manifest[relative]
                    runtime.set(namespace, "files", manifest)
                except Exception as error:
                    _failure(result, error, "cleanup")
            continue
        try:
            unchanged = previous.get("hash") == content_hash and await helper.get_document(previous.get("doc_id", ""))
        except Exception as error:
            _failure(result, error, "lookup")
            continue
        if unchanged:
            result["unchanged"] += 1
            if previous.get("retired"):
                try:
                    for old_id in previous["retired"]:
                        await helper.delete_document(old_id)
                    previous.pop("retired")
                    runtime.set(namespace, "files", manifest)
                except Exception as error:
                    _failure(result, error, "cleanup")
            continue
        if work >= limit:
            result["pending"] += 1
            continue
        work += 1
        # Deterministic names recover uploads interrupted before manifest save.
        path_hash = hashlib.sha256(relative.encode()).hexdigest()[:16]
        document_name = f"obsidian-{path_hash}-{content_hash[:16]}{path.suffix.lower()}"
        phase = "lookup"
        try:
            existing = await helper.list_documents(search=document_name, limit=10)
            document = next((item for item in existing if item.doc_name == document_name), None)
            if document is None:
                phase = "upload"
                document = await helper.upload_document(
                    file_name=document_name, file_content=content, file_type=path.suffix.lower()[1:],
                )
            retired = list(previous.get("retired") or [])
            if previous.get("doc_id") and previous["doc_id"] != document.doc_id:
                retired.append(previous["doc_id"])
            manifest[relative] = {"hash": content_hash, "doc_id": document.doc_id, "retired": retired}
            runtime.set(namespace, "files", manifest)
            result["uploaded"] += 1
            phase = "cleanup"
            for old_id in retired:
                await helper.delete_document(old_id)
            manifest[relative].pop("retired")
            runtime.set(namespace, "files", manifest)
        except Exception as error:
            _failure(result, error, phase)
    # Only remove documents created by this manifest, after a complete directory scan.
    for relative in set(manifest) - set(files):
        try:
            previous = manifest[relative]
            for doc_id in [previous["doc_id"], *previous.get("retired", [])]:
                await helper.delete_document(doc_id)
            del manifest[relative]
            runtime.set(namespace, "files", manifest)
            result["deleted"] += 1
        except Exception as error:
            _failure(result, error, "cleanup")
    return result
