from __future__ import annotations

import asyncio
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

from plugin_support import load_plugin

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bots"))

from fatfish_core import MemoryStore, RuntimeStore
from astrbot_plugin_fatfish_obsidian.sync import sync_vault, vault_files

PLUGIN = load_plugin("astrbot_plugin_fatfish_obsidian")


class Helper:
    def __init__(self):
        self.kb = types.SimpleNamespace(kb_id="private-kb")
        self.init_error = None
        self.docs = {}
        self.uploads = []
        self.fail = False

    async def upload_document(self, file_name: str, file_content: bytes | None, file_type: str):
        # These required argument names/types match native KBHelper.upload_document.
        kwargs = {"file_name": file_name, "file_content": file_content, "file_type": file_type}
        self.uploads.append(kwargs)
        if self.fail:
            raise RuntimeError("SECRET_PROVIDER_ERROR")
        document = types.SimpleNamespace(doc_id="doc-" + str(len(self.uploads)), doc_name=kwargs["file_name"])
        self.docs[document.doc_id] = document
        return document

    async def list_documents(self, *, search, limit):
        return [doc for doc in self.docs.values() if search in doc.doc_name][:limit]

    async def get_document(self, doc_id):
        return self.docs.get(doc_id)

    async def delete_document(self, doc_id):
        self.docs.pop(doc_id, None)


class ObsidianSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "vault"
        self.root.mkdir()
        self.runtime = RuntimeStore(Path(directory.name) / "memory.db")
        self.helper = Helper()

    async def test_first_sync_unchanged_modified_and_removed_are_native_incremental(self):
        path = self.root / "note.md"
        path.write_text("初始笔记", encoding="utf-8")
        first = await sync_vault(self.helper, self.runtime, self.root)
        self.assertEqual(first["uploaded"], 1)
        self.assertEqual(self.helper.uploads[0]["file_content"], "初始笔记".encode())
        self.assertEqual(len(self.helper.docs), 1)
        second = await sync_vault(self.helper, self.runtime, self.root)
        self.assertEqual(second["unchanged"], 1)
        self.assertEqual(len(self.helper.uploads), 1)
        path.write_text("修改笔记", encoding="utf-8")
        changed = await sync_vault(self.helper, self.runtime, self.root)
        self.assertEqual(changed["uploaded"], 1)
        self.assertEqual(list(self.helper.docs), ["doc-2"])
        self.assertEqual(path.read_text(encoding="utf-8"), "修改笔记")
        path.unlink()
        removed = await sync_vault(self.helper, self.runtime, self.root)
        self.assertEqual(removed["deleted"], 1)
        self.assertEqual(self.helper.docs, {})

    async def test_failed_replacement_preserves_old_document_and_retries_next_time(self):
        path = self.root / "note.md"
        path.write_text("old", encoding="utf-8")
        await sync_vault(self.helper, self.runtime, self.root)
        path.write_text("new", encoding="utf-8")
        self.helper.fail = True
        result = await sync_vault(self.helper, self.runtime, self.root)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["error_types"], {"upload:RuntimeError": 1})
        self.assertNotIn("SECRET", str(result))
        self.assertIn("doc-1", self.helper.docs)
        self.helper.fail = False
        result = await sync_vault(self.helper, self.runtime, self.root)
        self.assertEqual(result["uploaded"], 1)
        self.assertNotIn("doc-1", self.helper.docs)

    async def test_pending_limit_and_oversized_files_do_not_manufacture_uploads(self):
        for name in ("a.md", "b.md", "c.md"):
            (self.root / name).write_text(name)
        (self.root / "large.md").write_text("x" * 100)
        result = await sync_vault(self.helper, self.runtime, self.root, limit=1, max_bytes=20)
        self.assertEqual((result["uploaded"], result["pending"], result["oversized"]), (1, 2, 1))
        result = await sync_vault(self.helper, self.runtime, self.root, limit=1, max_bytes=20)
        self.assertEqual((result["uploaded"], result["pending"], result["unchanged"]), (1, 1, 1))

    async def test_existing_successful_upload_recovered_after_missing_manifest_save(self):
        (self.root / "note.md").write_text("note")
        await sync_vault(self.helper, self.runtime, self.root)
        self.runtime.set("obsidian:private-kb", "files", {})
        await sync_vault(self.helper, self.runtime, self.root)
        self.assertEqual(len(self.helper.uploads), 1)
        self.assertEqual(len(self.helper.docs), 1)

    async def test_unavailable_vault_never_deletes_existing_index(self):
        (self.root / "note.md").write_text("note")
        await sync_vault(self.helper, self.runtime, self.root)
        with self.assertRaises(FileNotFoundError):
            await sync_vault(self.helper, self.runtime, self.root / "missing")
        self.assertEqual(len(self.helper.docs), 1)

    async def test_same_kb_cannot_silently_merge_a_different_vault(self):
        await sync_vault(self.helper, self.runtime, self.root)
        other = self.root.parent / "other"
        other.mkdir()
        with self.assertRaisesRegex(ValueError, "其他 vault"):
            await sync_vault(self.helper, self.runtime, other)

    def test_hidden_folders_and_non_note_files_are_not_read(self):
        hidden = self.root / ".obsidian"
        hidden.mkdir()
        (hidden / "secret.md").write_text("private config")
        (self.root / "note.md").write_text("note")
        (self.root / "image.png").write_bytes(b"image")
        self.assertEqual(list(vault_files(self.root)), ["note.md"])

    async def test_empty_notes_are_skipped_without_upload_or_zero_vectors(self):
        (self.root / "empty.md").write_bytes(b"")
        (self.root / "whitespace.txt").write_bytes(b"\n \r\t")
        (self.root / "normal.md").write_text("knowledge")
        result = await sync_vault(self.helper, self.runtime, self.root)
        self.assertEqual((result["empty"], result["uploaded"], result["failed"]), (2, 1, 0))
        self.assertEqual(len(self.helper.uploads), 1)
        self.assertEqual(self.helper.uploads[0]["file_content"], b"knowledge")

    async def test_clearing_source_note_removes_obsolete_index_without_changing_source(self):
        path = self.root / "note.md"
        path.write_bytes(b"old note")
        await sync_vault(self.helper, self.runtime, self.root)
        path.write_bytes(b"")
        result = await sync_vault(self.helper, self.runtime, self.root)
        self.assertEqual((result["empty"], result["failed"]), (1, 0))
        self.assertEqual(self.helper.docs, {})
        self.assertEqual(path.read_bytes(), b"")

    async def test_native_parse_error_keeps_previous_index_and_has_only_safe_categories(self):
        path = self.root / "note.md"
        path.write_bytes(b"old note")
        await sync_vault(self.helper, self.runtime, self.root)
        path.write_bytes(b"\xff\xfe\xff")

        class KnowledgeBaseUploadError(RuntimeError):
            stage = "parsing"

        async def broken_parser(file_name, file_content, file_type):
            try:
                file_content.decode("utf-8")
            except UnicodeDecodeError as cause:
                raise KnowledgeBaseUploadError("PRIVATE_CONTENT_AND_PROVIDER_KEY") from cause

        self.helper.upload_document = broken_parser
        result = await sync_vault(self.helper, self.runtime, self.root)
        self.assertEqual(result["error_types"], {"parsing:KnowledgeBaseUploadError:UnicodeDecodeError": 1})
        self.assertEqual((result["failed"], result["uploaded"]), (1, 0))
        self.assertEqual(list(self.helper.docs), ["doc-1"])
        self.assertNotIn("PRIVATE", str(result))
        self.assertNotIn("note.md", str(result))

    async def test_rate_limited_upload_never_records_success_or_replaces_old_vector(self):
        path = self.root / "note.txt"
        path.write_text("previous")
        await sync_vault(self.helper, self.runtime, self.root)
        path.write_text("changed")

        async def rate_limited(file_name, file_content, file_type):
            raise RuntimeError("429 RATE_LIMIT SECRET_TOKEN")

        self.helper.upload_document = rate_limited
        result = await sync_vault(self.helper, self.runtime, self.root)
        self.assertEqual((result["failed"], result["uploaded"]), (1, 0))
        self.assertEqual(result["error_types"], {"upload:RuntimeError": 1})
        self.assertEqual(list(self.helper.docs), ["doc-1"])
        self.assertNotIn("SECRET", str(result))


class ObsidianPluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "vault"
        self.root.mkdir()
        self.plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        self.plugin.store = MemoryStore(Path(directory.name) / "memory.db")
        self.plugin.runtime = RuntimeStore(self.plugin.store.path)
        from fatfish_core.knowledge_graph import KnowledgeGraph
        self.plugin.graph = KnowledgeGraph(self.plugin.store.path)
        self.plugin.config = {"vault_path": str(self.root), "owner_ids": "qq:owner"}
        self.plugin._lock = asyncio.Lock()
        self.plugin._clock = datetime.strptime("03:00", "%H:%M")
        self.helper = Helper()
        self.manager = types.SimpleNamespace(get_kb_by_name=AsyncMock(return_value=self.helper), create_kb=AsyncMock(),
                                             retrieve=AsyncMock(return_value={"context_text": "PRIVATE_NOTE"}))
        self.plugin.context = types.SimpleNamespace(kb_manager=self.manager)

    def event(self, *, owner=True, private=True, platform="aiocqhttp"):
        return types.SimpleNamespace(is_private_chat=lambda: private, get_platform_name=lambda: platform,
                                     get_sender_id=lambda: "owner" if owner else "stranger", plain_result=lambda text: text)

    async def test_only_owner_private_queries_can_reach_manager(self):
        for event in (self.event(owner=False), self.event(private=False), self.event(platform="telegram")):
            self.assertIn("仅供老大私聊", await self.plugin.knowledge_tool(event, "PRIVATE_QUERY"))
            self.assertEqual([item async for item in self.plugin.knowledge(event, "同步")], ["知识库仅供老大私聊使用。"])
        self.manager.retrieve.assert_not_awaited()
        self.manager.get_kb_by_name.assert_not_awaited()
        result = await self.plugin.knowledge_tool(self.event(), "PRIVATE_QUERY")
        self.assertEqual(result, "PRIVATE_NOTE")
        self.manager.retrieve.assert_awaited_once_with(query="PRIVATE_QUERY", kb_names=["FatFish-Obsidian-Private"], top_m_final=3)
        rows = self.plugin.store.recent(scopes=("private",))
        self.assertEqual(len(rows), 1)
        self.assertNotIn("PRIVATE", str(rows))
        self.assertEqual(self.plugin.store.recent(scopes=("public",)), [])

    async def test_native_create_uses_configured_embedding_and_no_global_mutation(self):
        self.manager.get_kb_by_name.return_value = None
        self.manager.create_kb.return_value = self.helper
        await self.plugin.synchronize()
        self.assertEqual(self.manager.create_kb.await_args.kwargs["embedding_provider_id"], "siliconflow/bge-m3")
        self.assertNotIn("kb_names", self.plugin.config)

    async def test_sync_failure_is_private_growth_and_never_exposes_raw_error(self):
        self.manager.get_kb_by_name.side_effect = RuntimeError("SECRET_PROVIDER_KEY")
        replies = [item async for item in self.plugin.knowledge(self.event(), "同步")]
        self.assertIn("RuntimeError", replies[0])
        self.assertNotIn("SECRET", replies[0])
        rows = self.plugin.store.recent(scopes=("private",), kinds=("capability",))
        self.assertIn("失败", rows[0]["content"])
        self.assertNotIn("SECRET", str(rows))


if __name__ == "__main__":
    unittest.main()
