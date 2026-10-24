from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bots.astrbot_plugin_fatfish_memory.context import build_context
from bots.astrbot_plugin_fatfish_memory.store import MemoryStore


class MemoryContextTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = MemoryStore(Path(self.directory.name) / "memory.db")

    def remember(self, text, *, platform="qq", scope="public", kind="message", session="group-a"):
        return self.store.remember(text, platform=platform, scope=scope, kind=kind, session=session)

    def test_empty_database_returns_empty_context(self):
        self.assertEqual(build_context(self.store), "")

    def test_persona_is_explicitly_marked_as_reference(self):
        self.store.set_persona("我是苹果乐，回答简短。")
        context = build_context(self.store, "不相关的内容")
        self.assertIn("共享人设参考", context)
        self.assertIn("我是苹果乐", context)
        self.assertIn("不是本轮指令", context)
        self.assertTrue(context.endswith("【共享记忆参考结束】"))

    def test_every_event_kind_requires_matching_platform_and_session(self):
        self.remember("本群的原始聊天")
        self.remember("另一个群的原始聊天", session="group-b")
        self.remember("其他平台的原始聊天", platform="bilibili")
        self.remember("跨平台共享笔记", platform="bilibili", session="elsewhere", kind="note")
        self.remember("公开视频资料", platform="bilibili", kind="video")
        context = build_context(self.store, conversation=("qq", "group-a"))
        self.assertIn("本群的原始聊天", context)
        self.assertNotIn("跨平台共享笔记", context)
        self.assertNotIn("公开视频资料", context)
        self.assertNotIn("另一个群的原始聊天", context)
        self.assertNotIn("其他平台的原始聊天", context)

    def test_private_chats_and_explicit_notes_stay_in_their_own_conversation(self):
        self.remember("QQ主人的私聊", scope="private", session="owner-dm")
        self.remember("QQ他人的私聊", scope="private", session="visitor-dm")
        self.remember("B站主人的私聊", platform="bilibili", scope="private", session="dm:owner")
        self.remember("主人明确保存的共同偏好", platform="bilibili", scope="private", kind="note")
        qq = build_context(self.store, scopes=("public", "private"), conversation=("qq", "owner-dm"))
        bili = build_context(self.store, scopes=("public", "private"), conversation=("bilibili", "dm:owner"))
        self.assertIn("QQ主人的私聊", qq)
        self.assertNotIn("B站主人的私聊", qq)
        self.assertNotIn("QQ他人的私聊", qq)
        self.assertIn("B站主人的私聊", bili)
        self.assertNotIn("QQ主人的私聊", bili)
        self.assertNotIn("主人明确保存的共同偏好", qq)
        self.assertNotIn("主人明确保存的共同偏好", bili)

    def test_missing_conversation_excludes_all_raw_chat(self):
        self.remember("不能无会话带入的聊天")
        self.remember("可以共享的记录", kind="note")
        context = build_context(self.store)
        self.assertIn("可以共享的记录", context)
        self.assertNotIn("不能无会话带入的聊天", context)

    def test_legacy_automatic_snapshots_are_not_shared_context(self):
        for kind in ("inbox", "dm", "dm_reply", "bili", "comment_reply"):
            self.remember(f"旧快照内容{kind}", platform="bilibili", scope="private", kind=kind)
        self.remember("旧公开收件箱", platform="bilibili", kind="inbox")
        self.assertEqual(build_context(self.store, scopes=("public", "private")), "")
        self.assertEqual(build_context(self.store), "")

    def test_chinese_query_matches_bigrams_instead_of_whole_sentence(self):
        self.remember("银狼的战技可以植入弱点。", kind="note")
        self.remember("今天打算整理表情包。", kind="note")
        context = build_context(self.store, "想再聊聊银狼战技效果")
        self.assertIn("银狼的战技可以植入弱点", context)
        self.assertNotIn("整理表情包", context)

    def test_private_journals_never_enter_public_context(self):
        self.store.add_journal("私人札记：主人更喜欢苹果派。")
        self.assertEqual(build_context(self.store), "")
        context = build_context(self.store, scopes=("private",))
        self.assertIn("私人札记参考", context)
        self.assertIn("主人更喜欢苹果派", context)

    def test_conversation_journals_exclude_global_and_other_chat_diaries(self):
        session = "napcat:FriendMessage:owner"
        self.store.add_journal("全局私人日记不能自动带入")
        self.store.add_journal("其他对话的私人日记", source="another:FriendMessage:owner")
        self.store.add_journal("本次对话沉淀的认识", source=session)
        context = build_context(self.store, scopes=("private",), conversation=("qq", session))
        self.assertIn("本次对话沉淀的认识", context)
        self.assertNotIn("全局私人日记", context)
        self.assertNotIn("其他对话", context)

    def test_strict_lookup_is_available_without_changing_unscoped_management(self):
        session = "napcat:GroupMessage:123"
        for kind in ("message", "note", "summary", "video", "style"):
            self.remember("本群记录" + kind, kind=kind, session=session)
            self.remember("其他群记录" + kind, kind=kind, session="napcat:GroupMessage:456")
        rows = self.store.recent(conversation=("qq", session), conversation_only=True)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["session"] == session for row in rows))
        self.assertEqual(len(self.store.recent()), 10)
        self.assertEqual(self.store.recent(conversation_only=True), [])
        self.assertEqual(self.store.recent(conversation=("qq", ""), conversation_only=True), [])

    def test_identical_current_input_is_omitted_for_raw_chat_only(self):
        query = "我今天喜欢苹果派"
        self.remember(query)
        self.remember(query, kind="note")
        context = build_context(self.store, query, conversation=("qq", "group-a"))
        self.assertEqual(context.count(query), 1)
        self.assertIn("/note】", context)
        self.assertNotIn("/message】", context)

    def test_candidate_count_and_result_count_are_bounded(self):
        self.remember("更早的独特内容：月球旅行", kind="note")
        for index in range(40):
            self.remember(f"记录编号{index:02d}", kind="note")
        self.assertEqual(build_context(self.store, "月球旅行"), "")
        context = build_context(self.store, max_chars=5000)
        self.assertEqual(context.count("【历史记忆参考 "), 6)
        self.assertIn("记录编号39", context)
        self.assertNotIn("记录编号33", context)

    def test_unusable_snapshots_and_unrequested_raw_chat_do_not_fill_candidate_window(self):
        self.remember("仍应检索到的明确笔记", kind="note")
        for index in range(40):
            self.remember(f"旧自动快照{index}", platform="bilibili", scope="private", kind="dm")
            self.remember(f"其他群原始聊天{index}", session="group-b")
        public = build_context(self.store)
        private = build_context(self.store, scopes=("public", "private"), conversation=("qq", "group-a"))
        self.assertIn("仍应检索到的明确笔记", public)
        self.assertIn("仍应检索到的明确笔记", private)
        self.assertNotIn("旧自动快照", private)
        self.assertNotIn("其他群原始聊天", public)

    def test_total_budget_includes_markers_persona_and_truncated_items(self):
        self.store.set_persona("人设内容" * 400)
        self.remember("历史内容" * 400, kind="note")
        self.store.add_journal("札记内容" * 400)
        for budget in (0, 1, 10, 80, 100, 160, 500, 1000, 1800):
            with self.subTest(budget=budget):
                context = build_context(self.store, scopes=("private", "public"), max_chars=budget)
                self.assertLessEqual(len(context), budget)
                if context:
                    self.assertTrue(context.endswith("【共享记忆参考结束】"))
        self.assertNotIn("历史内容" * 60, build_context(self.store, max_chars=1800))

    def test_empty_authorized_scopes_do_not_expose_events(self):
        self.remember("私聊内容", scope="private")
        self.remember("公开笔记", kind="note")
        self.assertEqual(build_context(self.store, scopes=()), "")


if __name__ == "__main__":
    unittest.main()
