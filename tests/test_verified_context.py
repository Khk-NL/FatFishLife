"""Long-term chat recall keeps its evidence boundary after raw chat expires."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest

from fatfish_core.context import build_context
from fatfish_core.memory import MemoryStore, SCHEMA


class VerifiedContextTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'memory.db'
        self.store = MemoryStore(self.path)
        self.current = ('qq', 'napcat:GroupMessage:a')

    def candidate(self, text='苹果派不要加肉桂', *, conversation=None, status='verified'):
        platform, session = conversation or self.current
        event = self.store.remember(text, platform=platform, session=session, scope='public')
        cid = self.store.add_candidate(text, kind='claim', group_id=session, source_event_id=event)
        self.store.review_candidate(cid, status)
        return cid, event

    def test_expired_source_is_still_recalled_in_normal_context(self):
        cid, event = self.candidate()
        with self.store._connect() as db:
            db.execute("UPDATE events SET created_at='2000-01-01' WHERE id=?", (event,))
        self.assertEqual(self.store.prune(90), 1)
        self.assertIn('苹果派不要加肉桂', build_context(self.store, '苹果派', conversation=self.current))
        self.assertIn('已审核转述，非官方事实', build_context(self.store, '苹果派', conversation=self.current))
        self.store.review_candidate(cid, 'rejected')
        self.assertEqual(build_context(self.store, '苹果派', conversation=self.current), '')

    def test_platform_session_and_review_state_are_filtered_before_limit(self):
        self.candidate('苹果派本群可见')
        for index in range(8):
            self.candidate('苹果派其他群'+str(index), conversation=('qq','second:GroupMessage:a'))
            self.candidate('苹果派其他平台'+str(index), conversation=('bilibili',self.current[1]))
        self.candidate('苹果派还没审核', status='candidate')
        rows = self.store.recall_verified({'苹果派'}, conversation=self.current, limit=1)
        self.assertEqual([row['content'] for row in rows], ['苹果派本群可见'])
        for conversation in (None, ('qq',''), ('qq','napcat:FriendMessage:a')):
            self.assertEqual(self.store.recall_verified({'苹果派'}, conversation=conversation), [])
        self.assertEqual(self.store.recall_verified({'苹果派'}, conversation=self.current, scopes=('private',)), [])
        self.assertEqual(self.store.recall_verified(set(), conversation=self.current), [])

    def test_identical_umo_on_two_platforms_does_not_merge_candidates(self):
        first, _ = self.candidate()
        other, _ = self.candidate(conversation=('bilibili', self.current[1]))
        self.assertNotEqual(first, other)
        for platform in ('qq', 'bilibili'):
            rows=self.store.recall_verified({'苹果派'}, conversation=(platform,self.current[1]))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['platform'],platform)

    def test_recent_and_verified_content_is_deduplicated_and_budgeted(self):
        self.candidate()
        block=build_context(self.store,'苹果派',conversation=self.current)
        self.assertEqual(block.count('苹果派不要加肉桂'),1)
        self.assertLessEqual(len(build_context(self.store,'苹果派',conversation=self.current,max_chars=150)),150)
        self.assertEqual(build_context(self.store,'无关话题',conversation=self.current),'')

    def test_unbound_legacy_manual_rejection_cannot_be_bypassed_by_new_source(self):
        cid=self.store.add_candidate('苹果派不要加肉桂',kind='claim',group_id=self.current[1])
        self.store.review_candidate(cid,'rejected','owner rejected')
        event=self.store.remember('苹果派不要加肉桂',platform='qq',session=self.current[1],scope='public')
        self.assertEqual(self.store.add_candidate('苹果派不要加肉桂',kind='claim',group_id=self.current[1],source_event_id=event),0)
        self.assertEqual(len(self.store.list_candidates('rejected')),1)
        self.assertEqual(self.store.list_candidates('candidate'),[])

    def test_legacy_migration_binds_only_fully_proven_sources(self):
        legacy=self.path.with_name('legacy.db')
        with closing(sqlite3.connect(legacy)) as db, db:
            db.executescript(SCHEMA)
            for cid in range(1,6):
                db.execute("INSERT INTO candidates(id,group_id,kind,content,status,first_seen,last_seen) VALUES (?,?,'claim',?,'verified','2026-01-01','2026-01-01')",(cid,self.current[1],'苹果派迁移'+str(cid)))
            for eid,cid,platform,scope,session in [(1,1,'qq','public',self.current[1]),(2,2,'qq','private',self.current[1]),(4,4,'qq','public',self.current[1]),(5,4,'bilibili','public',self.current[1]),(6,5,'qq','public','other:GroupMessage:a')]:
                db.execute("INSERT INTO events(id,platform,scope,kind,session,content,created_at) VALUES (?,?,?,'message',?,'原文','2026-01-01')",(eid,platform,scope,session))
                db.execute("INSERT INTO candidate_sources VALUES (?,?,'2026-01-01')",(eid,cid))
            db.execute("INSERT INTO candidate_sources VALUES (3,3,'2026-01-01')")
        store=MemoryStore(legacy)
        self.assertEqual([r['content'] for r in store.recall_verified({'苹果派'},conversation=self.current)],['苹果派迁移1'])
        with store._connect() as db:
            db.execute('DELETE FROM events')
        store=MemoryStore(legacy)
        self.assertEqual(len(store.recall_verified({'苹果派'},conversation=self.current)),1)
