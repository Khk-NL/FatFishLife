"""Style retrieval must enforce scope before ranking or truncating rows."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fatfish_core.memory import MemoryStore
from bots.astrbot_plugin_fatfish_memory import style


class StyleScopeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.store=MemoryStore(self.root/'memory.db')
        self.upstream=self.root/'self-learning.db'
        with closing(sqlite3.connect(self.upstream)) as db, db:
            db.execute('CREATE TABLE expression_patterns(group_id TEXT,situation TEXT,expression TEXT)')
            db.executemany('INSERT INTO expression_patterns VALUES (?,?,?)',[
                ('napcat:GroupMessage:a','苹果派怎么做','苹果派多放糖呀'),
                ('napcat:GroupMessage:b','苹果派怎么做','其他群秘密短句'),
                ('second:GroupMessage:a','苹果派怎么做','其他适配器短句'),
                ('a','苹果派怎么做','旧群号不猜归属')])
        patched=patch.object(style,'SELF_LEARNING_DB',self.upstream);patched.start();self.addCleanup(patched.stop)

    def test_self_learning_requires_complete_current_group_origin(self):
        self.assertEqual(style.expression_patterns(conversation=('qq','napcat:GroupMessage:a')),[('苹果派怎么做','苹果派多放糖呀')])
        for conversation in (None,('qq','a'),('qq','napcat:FriendMessage:a'),('bilibili','napcat:GroupMessage:a')):
            self.assertEqual(style.expression_patterns(conversation=conversation),[])

    def test_shared_style_filters_platform_session_and_public_scope_before_limit(self):
        current=('qq','napcat:GroupMessage:a')
        self.store.remember('苹果派多加糖',kind='style',scope='public',platform=current[0],session=current[1])
        for platform,session,scope in [('qq','napcat:GroupMessage:b','public'),('qq',current[1],'private'),('bilibili',current[1],'public'),('system',None,'public')]:
            self.store.remember('苹果派不该跨群',kind='style',scope=scope,platform=platform,session=session)
        self.assertEqual(style.style_phrases(self.store.path,limit=1,conversation=current),['苹果派多加糖'])
        self.assertEqual(style.style_phrases(self.store.path),[])

    def test_final_prompt_never_contains_other_or_unattributed_expressions(self):
        block=style.build_style_block(self.store.path,'苹果派怎么做',conversation=('qq','napcat:GroupMessage:a'))
        self.assertIn('苹果派多放糖',block)
        for blocked in ('秘密','适配器','旧群号'):
            self.assertNotIn(blocked,block)
        self.assertEqual(style.build_style_block(self.store.path,'苹果派怎么做'),'')

    def test_maintenance_counts_do_not_require_exposing_unscoped_text(self):
        self.store.remember('仅供计数的旧表达',kind='style',scope='public')
        counts=style.stats(self.store.path)
        self.assertEqual(counts['expression_patterns'],4)
        self.assertEqual(counts['style'],1)
        self.assertEqual(style.style_phrases(self.store.path),[])
