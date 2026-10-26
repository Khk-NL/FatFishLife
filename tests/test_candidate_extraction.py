"""A replay is not new evidence; automatic admission cannot undo a review."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fatfish_core.extract import extract_candidates, promote_repeated
from fatfish_core.memory import MemoryStore
from fatfish_core.runtime import RuntimeStore


class CandidateExtractionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=MemoryStore(Path(temp.name)/'memory.db')
        self.group='napcat:GroupMessage:a'

    def message(self, text='听说苹果派店开门了', *, day='2026-10-23', scope='public'):
        event_id=self.store.remember(text,platform='qq',session=self.group,scope=scope)
        with self.store._connect() as db:
            db.execute('UPDATE events SET created_at=? WHERE id=?',(day+'T12:00:00+08:00',event_id))
        return event_id

    def candidate(self):
        with self.store._connect() as db:
            return dict(db.execute('SELECT * FROM candidates ORDER BY id LIMIT 1').fetchone())

    def test_restart_and_explicit_replay_do_not_add_hits_or_roll_back_checkpoint(self):
        source=self.message()
        self.assertEqual(extract_candidates(self.store)['claim'],1)
        self.assertEqual(extract_candidates(MemoryStore(self.store.path))['scanned'],0)
        for day in ('2026-10-24','2026-10-25'):
            with patch('fatfish_core.memory.now',return_value=day+'T12:00:00+08:00'):
                self.assertEqual(extract_candidates(self.store,since_id=0)['claim'],0)
        self.assertEqual(self.candidate()['hits'],1)
        self.assertEqual(promote_repeated(self.store),0)
        self.assertEqual(RuntimeStore(self.store.path).get('memory_extract','last_event_id'),source)

    def test_distinct_original_messages_across_days_can_promote_once(self):
        for day in ('2026-10-23','2026-10-23','2026-10-24'):
            self.message(day=day)
        self.assertEqual(extract_candidates(self.store)['claim'],3)
        self.assertEqual(self.candidate()['hits'],3)
        self.assertEqual(promote_repeated(self.store),1)
        self.assertEqual(promote_repeated(self.store),0)
        self.assertEqual(self.candidate()['status'],'verified')

    def test_legacy_inflated_hits_without_distinct_sources_do_not_auto_promote(self):
        cid=self.store.add_candidate('旧转述',kind='claim',group_id=self.group)
        with self.store._connect() as db:
            db.execute("UPDATE candidates SET hits=100,first_seen='2026-10-01',last_seen='2026-10-25' WHERE id=?",(cid,))
        self.assertEqual(promote_repeated(self.store),0)

    def test_rejected_preference_survives_new_source_and_explicit_old_source_replay(self):
        text='以后叫我小明'
        self.message(text);extract_candidates(self.store)
        cid=self.candidate()['id'];self.store.review_candidate(cid,'rejected','owner rejected')
        self.message(text,day='2026-10-24');extract_candidates(self.store)
        extract_candidates(self.store,since_id=0)
        row=self.candidate()
        self.assertEqual((row['status'],row['review_note']),('rejected','owner rejected'))
        self.assertEqual(self.store.search('小明',group_id=self.group),[])
        self.assertTrue(self.store.review_candidate(cid,'verified','owner explicitly approved'))

    def test_inline_admission_also_respects_manual_rejection(self):
        text='以后叫我小明'
        self.store.remember(text,scope='public',session=self.group,admit=True)
        cid=self.candidate()['id'];self.store.review_candidate(cid,'rejected','owner rejected')
        self.store.remember(text,scope='public',session=self.group,admit=True)
        self.assertEqual(self.candidate()['status'],'rejected')

    def test_failed_batch_replays_committed_sources_without_double_counting(self):
        first=self.message();second=self.message('听说另一家苹果派店也开门了')
        original=self.store.add_candidate
        def fail_second(*args,**kwargs):
            if kwargs.get('source_event_id')==second:raise sqlite3.OperationalError('forced write error')
            return original(*args,**kwargs)
        with patch.object(self.store,'add_candidate',side_effect=fail_second):
            with self.assertRaises(sqlite3.OperationalError):extract_candidates(self.store)
        self.assertEqual(RuntimeStore(self.store.path).get('memory_extract','last_event_id',0),0)
        self.assertEqual(extract_candidates(self.store)['claim'],1)
        with self.store._connect() as db:
            self.assertEqual([tuple(row) for row in db.execute('SELECT hits FROM candidates ORDER BY id')],[(1,),(1,)])

    def test_two_stores_cannot_count_the_same_source_twice(self):
        source=self.message();other=MemoryStore(self.store.path)
        def add(store):return store.add_candidate('同一条原消息',kind='claim',group_id=self.group,source_event_id=source)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(add,(self.store,other)))
        self.assertEqual(sum(bool(x) for x in results),1)
        self.assertEqual(self.candidate()['hits'],1)

    def test_unattributed_legacy_event_is_skipped_without_stalling_checkpoint(self):
        self.store.remember('听说旧消息有个传闻',platform='qq',scope='public')
        source=self.message()
        result=extract_candidates(self.store)
        self.assertEqual((result['claim'],result['skipped'],result['last_id']),(1,1,source))
        self.assertEqual(extract_candidates(self.store)['scanned'],0)

    def test_source_scope_validation_and_source_write_failure_are_atomic(self):
        private=self.message(scope='private')
        with self.assertRaises(ValueError):self.store.add_candidate('不能用私人来源',kind='claim',group_id=self.group,source_event_id=private)
        source=self.message()
        with self.store._connect() as db:
            db.execute("CREATE TRIGGER fail_source BEFORE INSERT ON candidate_sources BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.add_candidate('失败须回滚',kind='claim',group_id=self.group,source_event_id=source)
        with self.store._connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],0)

    def test_concurrent_manual_rejection_wins_over_automatic_promotion(self):
        for day in ('2026-10-23','2026-10-24','2026-10-24'):self.message(day=day)
        extract_candidates(self.store);original=self.store.review_candidate
        def reject_before_automatic(cid,status,note,**kwargs):
            original(cid,'rejected','owner rejected while scanning')
            return original(cid,status,note,**kwargs)
        with patch.object(self.store,'review_candidate',side_effect=reject_before_automatic):
            self.assertEqual(promote_repeated(self.store),0)
        self.assertEqual(self.candidate()['status'],'rejected')
