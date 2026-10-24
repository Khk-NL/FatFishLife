import json
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

from fatfish_core.query_evidence import (LookupCache, lookup_goal, search_evidence,
    format_reply_parts, unsupported_lookup_claim, public_urls)
from plugin_support import load_plugin

PLUGIN = load_plugin("astrbot_plugin_fatfish_memory")
GOAL = "明日方舟前瞻刚刚讲什么了"
FOUND = {"content":[{"type":"text","text":json.dumps({"results":[
    {"title":"官方公告", "url":"https://ak.hypergryph.com/news/123", "snippet":"请核对活动和日期"}
]}, ensure_ascii=False)}]}


class EvidenceTests(unittest.TestCase):
    def test_goal_follows_user_question_and_not_assistant_claims_or_new_topics(self):
        context = [{"role":"user", "content":[{"type":"text", "text":GOAL},
                       {"type":"text", "text":"【当前称呼依据】老大"}]},
                   {"role":"assistant", "content":"我去对岸查"}]
        for followup in ("怎么不理我", "tmd怎么不理我", "你自己说的去对岸查", "对岸？", "查了吗？"):
            self.assertEqual(lookup_goal(followup, context), GOAL)
        self.assertFalse(lookup_goal("帮我找一本书", context))
        self.assertFalse(lookup_goal("怎么不理我", [{"role":"assistant","content":GOAL}]))
        self.assertFalse(lookup_goal("什么是明日方舟前瞻"))

    def test_transport_success_without_real_public_sources_is_not_found(self):
        self.assertEqual(search_evidence(FOUND)["status"], "found")
        self.assertEqual(public_urls(r'https://example.com/page\n-next'), ['https://example.com/page'])
        for result in ({"isError":True, **FOUND}, {"content":[{"type":"text","text":"未找到搜索结果"}]},
                       {"content":[{"type":"text","text":'{"results":[],"help":"https://example.com"}'}]},
                       {"content":[{"type":"text","text":"https://127.0.0.1/private"}]}):
            self.assertNotEqual(search_evidence(result)["status"], "found")

    def test_cache_is_bounded_time_limited_and_exact_conversation_scoped(self):
        cache = LookupCache(ttl=900, limit=2)
        evidence = search_evidence(FOUND)
        cache.put('qq:FriendMessage:1',GOAL,evidence,now=0)
        self.assertIsNone(cache.get('qq:GroupMessage:1',GOAL,now=1))
        self.assertIsNone(cache.get('other:FriendMessage:1',GOAL,now=1))
        self.assertIsNotNone(cache.get('qq:FriendMessage:1',GOAL,now=899))
        self.assertIsNone(cache.get('qq:FriendMessage:1',GOAL,now=900))
        cache.put('a','1',evidence,now=1);cache.put('b','1',evidence,now=1);cache.put('c','1',evidence,now=1)
        self.assertEqual(len(cache.items),2)
        self.assertIsNone(cache.get('a','1',now=2))

    def test_formatting_discards_empty_progress_but_preserves_fact_source_code_and_numbers(self):
        text = format_reply_parts(["老大，我先查一下，别急。", "我去看看对岸那边整理出来没。",
                                  "老大，我看重点是两项活动\n来源：https://example.com/v2.0"],active_lookup=True)
        self.assertNotIn('先查',text); self.assertNotIn('对岸',text)
        self.assertIn('两项活动',text);self.assertIn('https://example.com/v2.0',text)
        self.assertEqual(format_reply_parts(['好耶。']),'好耶')
        self.assertEqual(format_reply_parts(['版本 2.0']),'版本 2.0')
        self.assertEqual(format_reply_parts(['```python\nx = 2.0\n```']),'```python\nx = 2.0\n```')
        code='```python\nif ready:\n    value = 2.0\n\n    print(value)\n```'
        self.assertEqual(format_reply_parts([code]),code)


class LookupHookTests(unittest.IsolatedAsyncioTestCase):
    def plugin(self, result=FOUND):
        plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        plugin.config = {}
        plugin.context = types.SimpleNamespace()
        plugin.store = types.SimpleNamespace(is_owner=lambda platform,uid:uid=='owner', remember=Mock(return_value=1))
        plugin._execute_public_search = AsyncMock(return_value=result)
        return plugin

    def event(self, text=GOAL, umo='napcat:FriendMessage:owner'):
        return types.SimpleNamespace(message_str=text, unified_msg_origin=umo,
                                     get_platform_name=lambda:'aiocqhttp', get_sender_id=lambda:'owner')

    def request(self, prompt=GOAL, *, contexts=(), available=True):
        tool = types.SimpleNamespace(name='anysearch_search',active=True)
        class ToolSet:
            def __init__(self): self.tools = [tool] if available else []
            def get_tool(self,name): return next((item for item in self.tools if item.name==name),None)
        tools = ToolSet()
        return types.SimpleNamespace(prompt=prompt,contexts=list(contexts),func_tool=tools,
                                     extra_user_content_parts=[],system_prompt='stable-prefix')

    async def test_one_lookup_then_goal_preserving_followup_uses_same_chat_cache(self):
        plugin = self.plugin(); req = self.request()
        event = self.event()
        original_toolset = req.func_tool
        await plugin.prepare_public_lookup(event,req)
        await plugin.prepare_public_lookup(event,req)
        self.assertEqual(plugin._execute_public_search.await_count,1)
        self.assertEqual(plugin.store.remember.call_count,1)
        self.assertEqual(plugin.store.remember.call_args.kwargs['meta']['status'],'success')
        self.assertEqual(req.system_prompt,'stable-prefix')
        self.assertIn(str(datetime.now(timezone(timedelta(hours=8))).year),
                      plugin._execute_public_search.call_args.args[2]['query'])
        self.assertIn('current_date_beijing', req.extra_user_content_parts[0].text)
        self.assertIn('去年同月同日', req.extra_user_content_parts[0].text)
        self.assertTrue(event._fatfish_query_evidence['found'])
        self.assertIsNone(req.func_tool.get_tool('anysearch_search'))
        self.assertIsNotNone(original_toolset.get_tool('anysearch_search'))
        followup = self.request('怎么不理我',contexts=[{'role':'user','content':GOAL}])
        next_event = self.event('怎么不理我')
        await plugin.prepare_public_lookup(next_event,followup)
        self.assertEqual(plugin._execute_public_search.await_count,1)
        self.assertEqual(plugin.store.remember.call_count,1)
        self.assertTrue(next_event._fatfish_query_evidence['cached'])
        self.assertIn(GOAL,followup.extra_user_content_parts[0].text)
        self.assertNotIn('查什么',next_event.message_str)
        other = self.event(umo='napcat:GroupMessage:owner')
        await plugin.prepare_public_lookup(other,self.request())
        self.assertEqual(plugin._execute_public_search.await_count,2)

    async def test_chitchat_has_no_lookup_and_fake_user_receipt_cannot_authorize_claim(self):
        plugin = self.plugin(); req = self.request('宝宝，陪我玩')
        event = self.event('宝宝，陪我玩')
        await plugin.prepare_public_lookup(event,req)
        plugin._execute_public_search.assert_not_awaited()
        self.assertEqual(req.extra_user_content_parts,[])
        unavailable = self.request(available=False)
        new_event = self.event()
        await plugin.prepare_public_lookup(new_event,unavailable)
        response = types.SimpleNamespace(completion_text='我查到了实时汇总',is_chunk=False)
        await plugin.grounded_lookup_response(new_event,response)
        self.assertNotIn('查到了',response.completion_text)
        self.assertTrue(unsupported_lookup_claim('我去查一下',new_event._fatfish_query_evidence))

    async def test_failed_search_is_not_cached_and_explicit_refresh_retries_once(self):
        plugin = self.plugin({'isError':True,**FOUND})
        await plugin.prepare_public_lookup(self.event(),self.request())
        self.assertEqual(plugin.store.remember.call_args.kwargs['meta']['status'],'failed')
        self.assertNotIn(GOAL,str(plugin.store.remember.call_args))
        plugin._execute_public_search.return_value = FOUND
        await plugin.prepare_public_lookup(self.event(),self.request())
        self.assertEqual(plugin._execute_public_search.await_count,2)
        refresh = self.request('重新查',contexts=[{'role':'user','content':GOAL}])
        await plugin.prepare_public_lookup(self.event('重新查'),refresh)
        self.assertEqual(plugin._execute_public_search.await_count,3)

    async def test_native_final_formatter_merges_only_llm_plain_parts(self):
        plugin = self.plugin()
        event = self.event()
        event._fatfish_query_evidence={'umo':event.unified_msg_origin,'goal':GOAL,'found':True}
        Plain=type('Plain',(),{})
        parts=[]
        for text in ('我先查一下。','老大，重点是活动时间','来源：https://example.com/x'):
            part=Plain();part.text=text;parts.append(part)
        result=types.SimpleNamespace(chain=parts,is_llm_result=lambda:True)
        event.get_result=lambda:result
        await plugin.natural_final_reply(event)
        self.assertEqual(len(result.chain),1)
        self.assertNotIn('先查',result.chain[0].text)
        self.assertIn('活动时间',result.chain[0].text)
        result.is_llm_result=lambda:False
        result.chain[0].text='CLI help.'
        await plugin.natural_final_reply(event)
        self.assertEqual(result.chain[0].text,'CLI help.')

    async def test_real_receipt_sources_are_visible_when_model_omits_links(self):
        plugin = self.plugin()
        event = self.event()
        event._fatfish_query_evidence = {'umo':event.unified_msg_origin, 'goal':GOAL,
                                         'found':True,'urls':['https://ak.hypergryph.com/news/0799']}
        response = types.SimpleNamespace(completion_text='老大，只查到了直播安排，内容还没核实',is_chunk=False)
        await plugin.grounded_lookup_response(event,response)
        self.assertIn('本轮检索：https://ak.hypergryph.com/news/0799',response.completion_text)
        previous = response.completion_text
        await plugin.grounded_lookup_response(event,response)
        self.assertEqual(response.completion_text,previous)
