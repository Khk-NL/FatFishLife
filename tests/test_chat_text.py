from types import SimpleNamespace
import unittest

from fatfish_core.chat_text import clean_chat_text, collapse_chat_repeats, event_chat_text


class ChatTextTests(unittest.TestCase):
    def test_only_explicit_mentions_and_media_placeholders_are_removed(self):
        self.assertEqual(clean_chat_text('[At:12345] [CQ:at,qq=67890]  今晚玩游戏吗 [图片]'), '今晚玩游戏吗')
        self.assertEqual(clean_chat_text('[At:全体成员] [CQ:at,qq=all] [语音]'), '')
        self.assertEqual(clean_chat_text('[图片] [合并消息] [视频] [表情] [转发] [Forward]'), '')
        self.assertEqual(clean_chat_text('[合并消息] 这张图片怎么修？ [图片]'), '这张图片怎么修？')
        self.assertEqual(clean_chat_text('@123456 明白啦'), '明白啦')
        self.assertEqual(clean_chat_text('邮箱 a@example.com，代码 @decorator，@小明 今晚玩？'),
                         '邮箱 a@example.com，代码 @decorator，@小明 今晚玩？')

    def test_structured_components_drop_mentions_without_guessing_display_names(self):
        At = type('At', (), {})
        Plain = type('Plain', (), {})
        at, plain = At(), Plain()
        plain.text = '今天还玩不玩？'
        event = SimpleNamespace(message_str='@一长串昵称 今天还玩不玩？',
                                message_obj=SimpleNamespace(message=[at, plain], raw_message={}))
        self.assertEqual(event_chat_text(event), '今天还玩不玩？')
        event.message_obj.message = [at]
        self.assertEqual(event_chat_text(event), '')
        event.message_obj.raw_message = {'post_type': 'notice'}
        event.message_obj.message = [plain]
        self.assertEqual(event_chat_text(event), '')

    def test_repetition_is_adjacent_and_preserves_scope_and_source_rows(self):
        def row(index, content='好耶', **kw):
            return {'id': index, 'content': content, 'kind': 'message', 'platform': 'qq', 'scope': 'public',
                    'session': 'napcat:GroupMessage:1', 'actor': 'a' if index == 1 else 'b',
                    'created_at': f'2026-10-24T12:00:{index:02d}+08:00', **kw}
        original = [row(1), row(2), row(3, '别的话'), row(4)]
        folded = collapse_chat_repeats(original)
        self.assertEqual([r['repeat_count'] for r in folded], [2, 1, 1])
        self.assertNotIn('actor', folded[0])
        self.assertNotIn('_actors', folded[0])
        self.assertNotIn('repeat_count', original[0])
        boundaries = [row(1), {**row(2), 'scope': 'private'}, {**row(3), 'session': 'napcat:FriendMessage:1'},
                      {**row(4), 'platform': 'bilibili'}]
        self.assertEqual(len(collapse_chat_repeats(boundaries)), 4)
        self.assertEqual(len(collapse_chat_repeats([row(1), {**row(2), 'created_at': '2026-10-25T12:00:01+08:00'}])), 2)
