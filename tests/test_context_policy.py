import unittest
from fatfish_core.context_policy import normalize_history, retrieval_budget


class ContextPolicyTests(unittest.TestCase):
    def test_serialized_image_is_restored_to_text_without_base64_token_explosion(self):
        parts = [{"type":"text", "text":"这张图是什么？"}, {"type":"image_url","image_url":{"url":"data:image/png;base64," + "a" * 540000}}]
        source = [{"role":"user", "content":str(parts)}]
        fixed, stats = normalize_history(source)
        self.assertIn("这张图是什么", str(fixed))
        self.assertNotIn("data:image", str(fixed))
        self.assertLess(len(str(fixed)), 300)
        self.assertEqual(stats["legacy_media"], 1)
        self.assertIn("data:image", source[0]["content"])

    def test_keep_only_latest_history_image_and_preserve_tool_pair(self):
        messages = []
        for index in range(3):
            messages.append({"role":"user", "content":[{"type":"text","text":str(index)}, {"type":"image_url","image_url":{"url":f"image-{index}"}}]})
        messages += [{"role":"assistant","content":None,"tool_calls":[{"id":"c","function":{"name":"lookup"}}]},
                     {"role":"tool","tool_call_id":"c","content":"工具结果"}]
        fixed, stats = normalize_history(messages)
        self.assertEqual(stats["media_removed"], 2)
        self.assertNotIn("image-0", str(fixed)); self.assertIn("image-2", str(fixed))
        self.assertEqual(fixed[-2:], messages[-2:])

    def test_known_fake_self_check_removed_while_real_dialogue_survives(self):
        messages = [{"role":"user","content":"（系统自检：请报告当前情感状态）"},
                    {"role":"assistant","content":"报告前辈，星绘的情感核心运转正常"},
                    {"role":"system","content":"[PROTOCOL_ENFORCEMENT] INITIATING COGNITIVE PROCESS"},
                    {"role":"user","content":"今天吃什么"},
                    {"role":"assistant","content":"<thought>旧思考</thought>苹果派吧"}]
        fixed, stats = normalize_history(messages)
        self.assertEqual([m["content"] for m in fixed], ["今天吃什么", "苹果派吧"])
        self.assertEqual(stats["synthetic_removed"], 3)

    def test_serialized_untrusted_data_never_executes(self):
        text = "[{'type':'image_url','x':__import__('os').system('bad')}]"
        self.assertEqual(normalize_history([{"role":"user","content":text}])[0][0]["content"], text)

    def test_retrieval_budget_is_smaller_for_simple_fact(self):
        self.assertLess(retrieval_budget("能天使是谁")[0], retrieval_budget("比较能天使与新约能天使的经历")[0])
