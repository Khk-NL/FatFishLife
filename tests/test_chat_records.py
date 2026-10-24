from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fatfish_core.memory import MemoryStore
from fatfish_core.chat_records import export_chat_records, migrate_chat_records


class ChatRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = MemoryStore(self.root / 'memory.db')

    def raw(self, text, *, session='napcat:GroupMessage:123456', scope='public', actor='SENDER_SECRET', kind='message', meta=None, platform='qq'):
        with closing(sqlite3.connect(self.store.path)) as db, db:
            cursor = db.execute('INSERT INTO events(platform,scope,kind,session,actor,content,created_at,meta) VALUES (?,?,?,?,?,?,?,?)',
                                (platform, scope, kind, session, actor, text, '2026-10-24T12:00:00+08:00', json.dumps(meta or {})))
            return cursor.lastrowid

    def test_new_chat_records_cannot_store_sender_or_raw_metadata(self):
        self.store.remember('[At:123456] 好耶', actor='SENDER_SECRET', meta={'sender': 'SENDER_SECRET'},
                            platform='qq', scope='public', session='napcat:GroupMessage:123456')
        row = self.store.recent(scopes=('public',))[0]
        self.assertEqual(row['content'], '好耶')
        self.assertIsNone(row['actor'])
        self.assertEqual(json.loads(row['meta']), {})
        with self.assertRaises(ValueError):
            self.store.remember('[图片] [合并消息]', platform='qq', session='napcat:GroupMessage:123456')
        self.store.remember('[合并消息] 这张图片怎么修？ [图片]', platform='qq', scope='public', session='napcat:GroupMessage:123456')
        self.assertEqual(self.store.recent(scopes=('public',))[0]['content'], '这张图片怎么修？')

    def test_migration_is_dry_run_by_default_and_only_changes_chat(self):
        first = self.raw('@123456 好耶', meta={'sender': 'SENDER_SECRET'})
        second = self.raw('[图片] [合并消息]')
        note = self.raw('明确写下的笔记', kind='note')
        report = migrate_chat_records(self.store.path)
        self.assertFalse(report['applied'])
        self.assertEqual(report['changed'], 2)
        self.assertEqual(self.store.recall('好耶', scopes=('public',))[0]['actor'], 'SENDER_SECRET')
        applied = migrate_chat_records(self.store.path, apply=True)
        self.assertEqual(applied['empty_removed'], 1)
        with closing(sqlite3.connect(self.store.path)) as db:
            rows = {r[0]: r[1:] for r in db.execute('SELECT id,actor,content,meta,session,scope,created_at FROM events')}
        self.assertNotIn(second, rows)
        self.assertEqual(rows[first][:3], (None, '好耶', '{}'))
        self.assertEqual(rows[first][3:], ('napcat:GroupMessage:123456', 'public', '2026-10-24T12:00:00+08:00'))
        self.assertEqual(rows[note][0], 'SENDER_SECRET')
        self.assertEqual(migrate_chat_records(self.store.path, apply=True)['changed'], 0)

    def test_exports_are_hashed_sender_free_and_split_by_full_conversation_and_scope(self):
        self.raw('[At:777777] 好耶')
        self.raw('好耶')
        self.raw('另一适配器', session='other:GroupMessage:123456')
        self.raw('私聊内容', session='napcat:FriendMessage:123456', scope='private')
        self.raw('同群私人条目', scope='private')
        self.raw('不能自动识别的旧记录', session='123456')
        out = self.root / 'outputs/chat-memory'
        report = export_chat_records(self.store.path, out)
        self.assertEqual(report['conversations'], 4)
        self.assertEqual(report['skipped_unscoped'], 1)
        paths = list(out.glob('*.md'))
        self.assertEqual(len(paths), 4)
        for path in paths:
            self.assertNotIn('123456', path.name)
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('SENDER_SECRET', text)
            self.assertNotIn('123456', text)
            self.assertNotIn('777777', text)
            self.assertNotIn('[At:', text)
            self.assertEqual(sum(value in text for value in ['好耶', '另一适配器', '私聊内容', '同群私人条目']), 1)
        self.assertTrue(any('好耶 × 2' in p.read_text(encoding='utf-8') for p in paths))
        self.assertEqual(export_chat_records(self.store.path, out)['unchanged'], 4)
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('DELETE FROM events WHERE scope=?', ('private',))
        self.assertEqual(export_chat_records(self.store.path, out)['removed'], 2)

    def test_export_stays_in_local_ignored_directories_and_escapes_markup(self):
        self.raw('![追踪](https://example.invalid/x) <img src=x> | 正文')
        with self.assertRaises(ValueError):
            export_chat_records(self.store.path, self.root / 'docs')
        out = self.root / 'outputs/chat-memory'
        export_chat_records(self.store.path, out)
        text = next(out.glob('*.md')).read_text(encoding='utf-8')
        self.assertNotIn('<img', text)
        self.assertIn('\\!\\[', text)
        self.assertIn('\\| 正文', text)

    def test_bilibili_explicit_sessions_export_but_legacy_numeric_sessions_do_not(self):
        self.raw('B站私信', platform='bilibili', session='dm:123456', scope='private')
        self.raw('B站评论', platform='bilibili', session='comment:BV123abc')
        self.raw('不明确的旧会话', platform='bilibili', session='123456')
        out = self.root / 'outputs/chat-memory'
        report = export_chat_records(self.store.path, out)
        self.assertEqual(report['conversations'], 2)
        self.assertEqual(report['skipped_unscoped'], 1)
        self.assertFalse(any('123456' in p.name or 'BV123abc' in p.name for p in out.glob('*.md')))

    def test_placeholder_only_conversations_do_not_become_markdown_memory(self):
        self.raw('[图片] [合并消息]')
        out = self.root / 'outputs/chat-memory'
        report = export_chat_records(self.store.path, out)
        self.assertEqual(report['skipped_empty'], 1)
        self.assertEqual(report['conversations'], 0)
        self.assertEqual(list(out.glob('*.md')), [])
