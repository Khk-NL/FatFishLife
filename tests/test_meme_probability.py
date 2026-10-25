import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fatfish_core import meme_probability as policy
from scripts.configure_meme_probability import configure, patch_source


class Image:
    pass


class Plain:
    def __init__(self, text="hello"):
        self.text = text


class Chain:
    def __init__(self, chain):
        self.chain = chain


def event(umo="napcat:GroupMessage:1"):
    extras = {}
    result = Chain([Plain()])
    return types.SimpleNamespace(unified_msg_origin=umo, send=AsyncMock(return_value=None),
        get_extra=lambda key:extras.get(key),set_extra=lambda key,value:extras.__setitem__(key,value),
        get_result=lambda:result)


def plugin(**values):
    config = {"probability":35,"probability_step":10,"probability_max":90,**values}
    return types.SimpleNamespace(emotions_probability=config['probability'],
        _read_config_value=lambda keys,default:config.get(keys[-1],default),
        _scope_allows_llm_origin=lambda e:True,_should_attach_for_result=lambda e,r:True)


class MemeProgressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_event_rolls_once_and_records_one_miss_after_reply(self):
        p=plugin();e=event()
        with patch.object(policy.random,'random',return_value=.8) as rng:
            self.assertFalse(policy.meme_probability_hit(p,e))
            self.assertFalse(policy.meme_probability_hit(p,e))
            self.assertFalse(policy.meme_probability_hit(p,e))
            self.assertEqual(rng.call_count,1)
        self.assertEqual(policy._counts(p).get(e.unified_msg_origin),0)
        after=policy.progressive_after_sent(AsyncMock())
        await after(p,e);await after(p,e)
        self.assertEqual(policy._counts(p).get(e.unified_msg_origin),1)
        with patch.object(policy.random,'random',return_value=.4):
            following=event();self.assertTrue(policy.meme_probability_hit(p,following))
            self.assertAlmostEqual(getattr(following,policy.STATE)['probability'],.45)
        # A successful roll is not a successful image send.
        self.assertEqual(policy._counts(p).get(e.unified_msg_origin),1)
        await after(p,following)
        self.assertEqual(policy._counts(p).get(e.unified_msg_origin),2)

    async def test_full_umo_isolation_and_cap(self):
        p=plugin();policy._counts(p).counts['napcat:GroupMessage:1']=100
        with patch.object(policy.random,'random',return_value=.95):
            e=event();policy.meme_probability_hit(p,e)
            self.assertEqual(getattr(e,policy.STATE)['probability'],.9)
            for key in ('napcat:FriendMessage:1','other:GroupMessage:1'):
                other=event(key);policy.meme_probability_hit(p,other)
                self.assertEqual(getattr(other,policy.STATE)['probability'],.35)

    async def test_mixed_image_resets_only_after_successful_native_send(self):
        p=plugin();e=event();key=e.unified_msg_origin;policy._counts(p).record(key,sent=False)
        async def decorate(plugin,event):event.get_result().chain.append(Image())
        with patch.object(policy.random,'random',return_value=0):
            await policy.progressive_decorate(decorate)(p,e)
        self.assertEqual(policy._counts(p).get(key),1)
        await e.send(e.get_result())
        self.assertEqual(policy._counts(p).get(key),0)
        await policy.progressive_after_sent(AsyncMock())(p,e)
        self.assertEqual(policy._counts(p).get(key),0)

    async def test_unrelated_existing_image_does_not_reset_meme_counter(self):
        p=plugin();e=event();key=e.unified_msg_origin;policy._counts(p).record(key,sent=False)
        e.get_result().chain.append(Image())
        with patch.object(policy.random,'random',return_value=0):
            await policy.progressive_decorate(AsyncMock())(p,e)
        await e.send(e.get_result());await policy.progressive_after_sent(AsyncMock())(p,e)
        self.assertEqual(policy._counts(p).get(key),2)

    async def test_separate_and_streaming_image_send_success_false_and_exception(self):
        p=plugin();key='napcat:GroupMessage:1'
        for outcome in (False,TimeoutError()):
            e=event();policy._counts(p).counts[key]=2
            sender=AsyncMock(side_effect=outcome) if isinstance(outcome,Exception) else AsyncMock(return_value=outcome)
            with patch.object(policy.random,'random',return_value=0):
                if isinstance(outcome,Exception):
                    with self.assertRaises(TimeoutError):await policy.progressive_image_send(sender)(p,e,Image())
                else:await policy.progressive_image_send(sender)(p,e,Image())
            self.assertEqual(policy._counts(p).get(key),2)
            await policy.progressive_after_sent(AsyncMock())(p,e)
            self.assertEqual(policy._counts(p).get(key),3)
        e=event()
        with patch.object(policy.random,'random',return_value=0):
            await policy.progressive_image_send(AsyncMock(return_value=None))(p,e,Image())
        self.assertEqual(policy._counts(p).get(key),0)

    async def test_semantic_miss_clears_selection_without_dropping_visible_text(self):
        p=plugin();e=event();response=types.SimpleNamespace(completion_text='visible text')
        async def respond(plugin,event,response):
            event.set_extra('meme_manager_semantic_selected_ids',['pack:id'])
            event.set_extra('found_emotions',['happy'])
        with patch.object(policy.random,'random',return_value=.9):
            await policy.progressive_response(respond)(p,e,response)
        self.assertEqual(e.get_extra('meme_manager_semantic_selected_ids'),[])
        self.assertEqual(e.get_extra('found_emotions'),[])
        self.assertEqual(response.completion_text,'visible text')

    async def test_compat_mixed_send_has_same_success_accounting(self):
        p=plugin();e=event();image=Image();policy._counts(p).counts[e.unified_msg_origin]=3
        async def original(plugin,event,prepared):await event.send(Chain(prepared['images']))
        with patch.object(policy.random,'random',return_value=0):
            await policy.progressive_compat_send(original)(p,e,{'images':[image]})
        self.assertEqual(policy._counts(p).get(e.unified_msg_origin),0)
        # No second increment from an additional normal after-message hook.
        await policy.progressive_after_sent(AsyncMock())(p,e)
        self.assertEqual(policy._counts(p).get(e.unified_msg_origin),0)

    async def test_late_after_hook_does_not_reset_a_newer_reply_miss(self):
        p=plugin();first=event();second=event()
        with patch.object(policy.random,'random',return_value=0):
            await policy.progressive_image_send(AsyncMock(return_value=None))(p,first,Image())
        with patch.object(policy.random,'random',return_value=.99):
            policy.meme_probability_hit(p,second)
        after=policy.progressive_after_sent(AsyncMock())
        await after(p,second)
        await after(p,first)
        self.assertEqual(policy._counts(p).get(first.unified_msg_origin),1)

    async def test_explicit_request_bypasses_probability_without_random_roll(self):
        p=plugin(probability=0,probability_step=0);e=event();e.message_str='苹果乐，给我发一张开心的表情包'
        with patch.object(policy.random,'random',return_value=.99) as rng:
            self.assertTrue(policy.meme_probability_hit(p,e))
        rng.assert_not_called()
        self.assertTrue(getattr(e,policy.STATE)['manual'])

    async def test_opt_out_and_setting_do_not_force_a_manual_hit(self):
        for text,enabled in [('不要发个表情包，纯文字就好',True),('发个表情包',False),('表情包怎么都不发了',True)]:
            p=plugin(probability=0,probability_step=0,manual_trigger=enabled);e=event();e.message_str=text
            with patch.object(policy.random,'random',return_value=.99):
                self.assertFalse(policy.meme_probability_hit(p,e))

    async def test_manual_text_reply_reuses_one_native_search_and_parser(self):
        p=plugin();e=event();e.message_str='发个开心表情包'
        e.set_extra('meme_manager_semantic_mode','tool')
        p._semantic_mode_active=lambda e:True
        async def search(event,query):
            event.set_extra('meme_manager_semantic_search_completed',True)
            event.set_extra('meme_manager_semantic_candidates',{'first':{'id':'pack:first','score':.3},'best':{'id':'pack:best','score':.8}})
        p.search_memes_tool=AsyncMock(side_effect=search)
        p._resp_semantic_impl=AsyncMock()
        response=types.SimpleNamespace(completion_text='来啦')
        await policy.progressive_response(AsyncMock())(p,e,response)
        p.search_memes_tool.assert_awaited_once_with(e,e.message_str)
        p._resp_semantic_impl.assert_awaited_once_with(e,response,'来啦\n&&pack:best&&')

    async def test_manual_reuses_existing_candidates_without_searching_twice(self):
        p=plugin();e=event();e.message_str='来个表情包'
        e.set_extra('meme_manager_semantic_mode','tool');e.set_extra('meme_manager_semantic_search_completed',True)
        e.set_extra('meme_manager_semantic_candidates',{'first':{'id':'pack:first','score':.8}})
        p._semantic_mode_active=lambda e:True;p.search_memes_tool=AsyncMock();p._resp_semantic_impl=AsyncMock()
        await policy.progressive_response(AsyncMock())(p,e,types.SimpleNamespace(completion_text='好呀'))
        p.search_memes_tool.assert_not_awaited();p._resp_semantic_impl.assert_awaited_once()

    async def test_manual_no_candidates_or_failed_search_keeps_original_text(self):
        for outcome in (None,TimeoutError()):
            p=plugin();e=event();e.message_str='发个表情包';e.set_extra('meme_manager_semantic_mode','tool')
            p._semantic_mode_active=lambda e:True
            p.search_memes_tool=AsyncMock(side_effect=outcome) if isinstance(outcome,Exception) else AsyncMock()
            p._resp_semantic_impl=AsyncMock();response=types.SimpleNamespace(completion_text='原来的文字')
            await policy.progressive_response(AsyncMock())(p,e,response)
            self.assertEqual(response.completion_text,'原来的文字');p._resp_semantic_impl.assert_not_awaited()

    async def test_manual_never_widens_scope_or_offline_plain_result(self):
        for allowed,active,selected in ((False,True,False),(True,False,False),(True,True,True)):
            p=plugin();e=event();e.message_str='发个表情包';e.set_extra('meme_manager_semantic_mode','tool')
            if selected:e.set_extra('meme_manager_semantic_selected_ids',['already-selected'])
            p._scope_allows_llm_origin=lambda e:allowed;p._semantic_mode_active=lambda e:active
            p.search_memes_tool=AsyncMock();p._resp_semantic_impl=AsyncMock()
            await policy.progressive_response(AsyncMock())(p,e,types.SimpleNamespace(completion_text='来啦'))
            p.search_memes_tool.assert_not_awaited();p._resp_semantic_impl.assert_not_awaited()


SOURCE='''from ..utils import probability_hit
class EventHandlerMixin:
    def _meme_probability_hit(self, event) -> bool:
        return True
    async def _mark_llm_request_origin_impl(self,event):pass
    async def _resp_impl(self,event,response):
        if semantic_mode == "llm":
            return await self._resp_semantic_llm_impl(event, response, text)
    async def _on_decorating_result_impl(self,event):pass
    async def _after_message_sent_impl(self,event):pass
    async def _send_meme_image(self,event,image):
        await self.context.send_message(event.unified_msg_origin, MessageChain([image]))
    async def compat_send_prepared_message(self,event,prepared):pass
    async def _build_emotion_images_for_event(self,event,emotions):
        random_value = random.randint(1, 100)
        if random_value > self.emotions_probability:
            return [], []
'''


class MemeInstallerTests(unittest.TestCase):
    def test_installer_preview_preserves_current_values_and_idempotently_applies(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);native=root/'data/plugins/meme_manager';(native/'mixins').mkdir(parents=True)
            (native/'metadata.yaml').write_text('version: 5.2.5\n')
            (native/'LICENSE').write_text('MIT License\n')
            source=native/'mixins/event_handlers.py';source.write_text(SOURCE)
            schema=native/'_conf_schema.json';schema.write_text(json.dumps({'generation':{'items':{'emotion':{'items':{}}}}}))
            config=root/'data/config/meme_manager_config.json';config.parent.mkdir()
            config.write_text(json.dumps({'generation':{'emotion':{'probability':35}},'api_key':'local-secret','keep':7}))
            report=configure(root);self.assertFalse(report['applied']);self.assertEqual(source.read_text(),SOURCE)
            self.assertNotIn('local-secret',str(report))
            report=configure(root,apply=True);current=json.loads(config.read_text())
            self.assertEqual(current['generation']['emotion'],{'probability':35,'probability_step':10,'probability_max':90,'manual_trigger':True})
            self.assertEqual(current['keep'],7);self.assertEqual(current['api_key'],'local-secret')
            self.assertEqual(configure(root,apply=True)['changed_files'],[])
            self.assertEqual(patch_source(patch_source(SOURCE)),patch_source(SOURCE))
            self.assertIn('return await self.context.send_message',source.read_text())

    def test_changed_upstream_shape_stops_instead_of_partial_patch(self):
        with self.assertRaises(ValueError):patch_source('class Changed:pass')
