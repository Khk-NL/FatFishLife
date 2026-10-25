"""Candidate approval must commit the decision and searchable index together."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fatfish_core.memory import MemoryStore


class CandidateIndexTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = MemoryStore(Path(directory.name) / 'memory.db')
        self.cid = self.store.add_candidate('测试群长期记忆', kind='claim', group_id='napcat:GroupMessage:a')

    def indexed(self):
        with self.store._connect() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM memory_fts')]

    def test_approval_uses_one_connection_and_immediately_indexes(self):
        with patch.object(self.store, '_connect', wraps=self.store._connect) as connect:
            self.assertTrue(self.store.review_candidate(self.cid, 'verified', 'owner verified'))
            self.assertEqual(connect.call_count, 1)
        rows = self.indexed()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ref_id'], self.cid)
        self.assertEqual(rows[0]['group_id'], 'napcat:GroupMessage:a')
        self.assertEqual(len(self.store.search('长期记忆', group_id='napcat:GroupMessage:a')), 1)
        self.assertEqual(self.store.search('长期记忆', group_id='napcat:GroupMessage:b'), [])

    def test_repeated_approval_replaces_instead_of_duplicating(self):
        for _ in range(3):
            self.store.review_candidate(self.cid, 'verified')
        self.assertEqual(len(self.indexed()), 1)

    def test_rejection_and_return_to_pending_remove_searchable_content(self):
        for status in ('rejected', 'candidate'):
            self.store.review_candidate(self.cid, 'verified')
            self.assertTrue(self.store.review_candidate(self.cid, status))
            self.assertEqual(self.indexed(), [])
            self.assertEqual(self.store.search('长期记忆'), [])

    def test_failed_index_write_rolls_back_decision_and_prior_index(self):
        self.store.review_candidate(self.cid, 'verified', 'previous review')
        before = self.indexed()
        with patch.object(self.store, '_index', side_effect=sqlite3.OperationalError('forced failure')):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.review_candidate(self.cid, 'verified', 'replacement review')
        self.assertEqual(self.indexed(), before)
        with self.store._connect() as conn:
            row = conn.execute('SELECT status,review_note FROM candidates WHERE id=?', (self.cid,)).fetchone()
        self.assertEqual(tuple(row), ('verified', 'previous review'))

    def test_missing_candidate_does_not_touch_existing_index(self):
        self.store.review_candidate(self.cid, 'verified')
        before = self.indexed()
        self.assertFalse(self.store.review_candidate(self.cid + 100, 'rejected'))
        self.assertEqual(self.indexed(), before)

    def test_rebuild_repairs_legacy_rows_without_rewriting_review_evidence(self):
        rejected = self.store.add_candidate('已拒绝记忆', kind='claim', group_id='napcat:GroupMessage:b')
        with self.store._connect() as conn:
            conn.execute("UPDATE candidates SET status='verified',review_note='original' WHERE id=?", (self.cid,))
            conn.execute("UPDATE candidates SET status='rejected' WHERE id=?", (rejected,))
            conn.execute('INSERT INTO memory_fts VALUES (?,?,?,?)', ('已拒绝记忆', 'claim', 'napcat:GroupMessage:b', rejected))
            before = [tuple(row) for row in conn.execute('SELECT * FROM candidates ORDER BY id')]
        self.assertEqual(self.store.rebuild_candidate_index(), 1)
        self.assertEqual(self.store.rebuild_candidate_index(), 1)
        self.assertEqual(self.indexed()[0]['ref_id'], self.cid)
        with self.store._connect() as conn:
            after = [tuple(row) for row in conn.execute('SELECT * FROM candidates ORDER BY id')]
        self.assertEqual(before, after)
