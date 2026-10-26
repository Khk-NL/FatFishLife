import asyncio
import ast
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

from fatfish_core.voice_policy import (DEFAULT_POLICY, guarded_result, guarded_manual,
                                      protect_delivery, MANUAL_REQUEST, _voice_counters)
from scripts.configure_voice_policy import configure, patch_source, MARKER


class Plain:
    def __init__(self,text):self.text=text


class Record:
    def __init__(self,file):self.file=str(file)


class Chain:
    def __init__(self,chain):self.chain=chain
    def derive(self,chain):return Chain(chain)
    def is_llm_result(self):return True


class Config(dict):
    def is_voice_output_enabled_for_umo(self,umo):return self.get('allowed',True)


class VoicePolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        components=types.ModuleType('astrbot.core.message.components');components.Plain=Plain
        session=types.ModuleType('astrbot.core.star.session_llm_manager')
        session.SessionServiceManager=types.SimpleNamespace(should_process_tts_request=AsyncMock(return_value=True))
        constants=types.ModuleType('policy_test.core.constants');constants.TEMP_DIR=self.root
        self.modules=patch.dict(sys.modules,{'astrbot.core.message.components':components,
            'astrbot.core.star.session_llm_manager':session,'policy_test.core.constants':constants})
        self.modules.start();self.addCleanup(self.modules.stop)

    def event(self,*,private=False,prompt='你好',umo='napcat:GroupMessage:1'):
        result=Chain([Plain('老大，出发啦')])
        return types.SimpleNamespace(message_str=prompt,unified_msg_origin=umo,
            get_platform_name=lambda:'aiocqhttp',is_private_chat=lambda:private,
            get_result=lambda:result,send=AsyncMock())

    def router(self,**cfg):
        cls=type('Router',(),{'__module__':'policy_test.main'})
        r=cls();r.config=Config(fatfish_policy={**DEFAULT_POLICY,'enabled':True,**cfg})
        offline=types.SimpleNamespace(enabled=True,state=types.SimpleNamespace(runtime=types.SimpleNamespace(get=lambda *a:{'offline':False})))
        r.context=types.SimpleNamespace(get_registered_star=lambda name:types.SimpleNamespace(star_cls=offline))
        r.condition_checker=types.SimpleNamespace(check_all=lambda *a,**k:types.SimpleNamespace(passed=True))
        r._get_umo=lambda event:event.unified_msg_origin;r._get_session_state=lambda umo:object()
        return r

    async def test_disabled_offline_length_session_block_prevent_synthesis(self):
        function=AsyncMock()
        wrapped=guarded_result(function)
        for cfg in ({'enabled':False},{'max_text_length':2}):
            await wrapped(self.router(**cfg),self.event())
        offline=self.router();offline.context.get_registered_star=lambda name:None
        await wrapped(offline,self.event())
        blocked=self.router();blocked.config['allowed']=False
        await wrapped(blocked,self.event())
        function.assert_not_awaited()

    async def test_normal_reply_uses_native_checker_and_explicit_request_only_bypasses_probability(self):
        calls=[]
        async def original(router,event):calls.append(event._fatfish_manual_voice)
        r=self.router(voice_probability=0)
        await guarded_result(original)(r,self.event())
        self.assertEqual(calls,[])
        await guarded_result(original)(r,self.event(prompt='用语音回复我'))
        self.assertEqual(calls,[True]);self.assertEqual(r.condition_checker.cooldown,180)
        self.assertTrue(MANUAL_REQUEST.search('老板，读给我听'))
        self.assertFalse(MANUAL_REQUEST.search('语音识别是什么'))
        await guarded_result(original)(r,self.event(prompt='不要用语音回复我'))
        self.assertEqual(calls,[True])

    async def test_same_full_session_single_inflight_and_global_two_no_waiting_queue(self):
        started=asyncio.Event();release=asyncio.Event();calls=[]
        async def original(router,event):
            calls.append(event.unified_msg_origin);started.set();await release.wait()
        r=self.router();wrapped=guarded_result(original)
        first=asyncio.create_task(wrapped(r,self.event()));await started.wait()
        await wrapped(r,self.event())
        second=asyncio.create_task(wrapped(r,self.event(umo='napcat:FriendMessage:1')))
        await asyncio.sleep(0)
        await wrapped(r,self.event(umo='other:GroupMessage:2'))
        self.assertEqual(len(calls),2)
        release.set();await asyncio.gather(first,second)
        self.assertEqual(r._fatfish_voice_inflight,set())

    async def test_explicit_request_reports_scope_block_instead_of_silently_ignoring_it(self):
        r=self.router();r.config['allowed']=False
        event=self.event(prompt='语音呢？')
        function=AsyncMock()
        await guarded_result(function)(r,event)
        function.assert_not_awaited()
        self.assertIn('当前会话没有开启语音',event.get_result().chain[0].text)
        self.assertTrue(MANUAL_REQUEST.search('语音呢？'))
        self.assertFalse(MANUAL_REQUEST.search('语音识别是什么'))

    async def test_manual_short_reply_bypasses_only_automatic_minimum_and_restores_checker(self):
        r=self.router(voice_probability=0);r.condition_checker.text_min_limit=5
        event=self.event(prompt='用语音说好');event.get_result().chain[0].text='好'
        checks=[]
        def check(text,*args,**kwargs):
            checks.append(r.condition_checker.text_min_limit)
            return types.SimpleNamespace(passed=len(text)>=r.condition_checker.text_min_limit)
        r.condition_checker.check_all=check
        original=AsyncMock()
        await guarded_result(original)(r,event)
        original.assert_awaited_once()
        self.assertEqual(checks,[0])
        self.assertEqual(r.condition_checker.text_min_limit,5)
        self.assertEqual(r.condition_checker.cooldown,180)

    async def test_explicit_request_reports_failed_synthesis_without_an_extra_model_call(self):
        event=self.event(prompt='发语音')
        function=AsyncMock()
        await guarded_result(function)(self.router(),event)
        function.assert_awaited_once()
        self.assertIn('本次未生成语音',event.get_result().chain[0].text)

    async def test_generated_record_uses_existing_sender_discloses_ai_and_removes_own_file(self):
        audio=self.root/'voice.mp3';audio.write_bytes(b'fake')
        async def original(router,event):event.get_result().chain=[Record(audio)]
        event=self.event();sender=event.send;original_text=event.get_result().chain[0].text
        await guarded_result(original)(self.router(),event)
        owned=Path(event.get_result().chain[0].file)
        self.assertNotEqual(owned,audio);self.assertTrue(owned.exists())
        await event.send(event.get_result().derive(event.get_result().chain))
        self.assertEqual(sender.await_count,2)
        self.assertEqual(sender.await_args_list[0].args[0].chain[0].text,'AI合成角色语音')
        self.assertIsInstance(sender.await_args_list[1].args[0].chain[0],Record)
        self.assertTrue(audio.exists());self.assertFalse(owned.exists());self.assertIs(event.send,sender)
        self.assertEqual(original_text,'老大，出发啦')

    async def test_send_failure_falls_back_to_original_text_without_model_or_retry(self):
        audio=self.root/'voice.mp3';audio.write_bytes(b'fake')
        event=self.event(private=True);sent=[]
        async def sender(message):
            sent.append(message)
            if isinstance(message.chain[0],Record):raise TimeoutError()
        event.send=sender
        record=Record(audio)
        protect_delivery(event,[record],'原有文字',root=self.root)
        owned=Path(record.file)
        await event.send(Chain([record]))
        self.assertEqual(len(sent),2);self.assertEqual(sent[-1].chain[0].text,'原有文字')
        self.assertIs(event.send,sender);self.assertTrue(audio.exists());self.assertFalse(owned.exists())

    async def test_two_conversations_reusing_the_same_cached_path_keep_independent_delivery_copies(self):
        cache=self.root/'shared-cache.mp3';cache.write_bytes(b'shared-cached-audio')
        first=self.event(private=True,umo='napcat:FriendMessage:1')
        second=self.event(private=True,umo='napcat:GroupMessage:1')
        second_started=asyncio.Event();second_may_finish=asyncio.Event()
        async def second_sender(message):
            second_started.set()
            await second_may_finish.wait()
            self.assertEqual(Path(message.chain[0].file).read_bytes(),b'shared-cached-audio')
        second.send=second_sender
        first_record=Record(cache);second_record=Record(cache)
        first_record.url=second_record.url=str(cache)
        first_record.path=second_record.path=str(cache)
        protect_delivery(first,[first_record],'同一句话',root=self.root)
        protect_delivery(second,[second_record],'同一句话',root=self.root)
        a,b=Path(first_record.file),Path(second_record.file)
        self.assertNotEqual(a,b);self.assertNotEqual(a,cache)
        self.assertEqual(first_record.url,str(a));self.assertEqual(second_record.url,str(b))
        self.assertEqual(first_record.path,str(a));self.assertEqual(second_record.path,str(b))
        second_task=asyncio.create_task(second.send(Chain([second_record])))
        await second_started.wait()
        await first.send(Chain([first_record]))
        self.assertFalse(a.exists());self.assertTrue(b.exists());self.assertTrue(cache.exists())
        self.assertEqual(b.read_bytes(),b'shared-cached-audio')
        second_may_finish.set();await second_task
        self.assertFalse(b.exists());self.assertEqual(cache.read_bytes(),b'shared-cached-audio')

    async def test_alongside_failure_does_not_duplicate_original_text(self):
        event=self.event(private=True);sent=[]
        async def sender(message):
            sent.append(message)
            if isinstance(message.chain[0],Record):raise RuntimeError()
        event.send=sender;record=Record(self.root/'missing.mp3')
        protect_delivery(event,[record,Plain('原有文字')],'原有文字',root=self.root,alongside=True)
        await event.send(Chain([record,Plain('原有文字')]))
        self.assertEqual([p.text for msg in sent for p in msg.chain if isinstance(p,Plain)],['原有文字'])

    async def test_synthesis_failure_preserves_text_and_manual_keeps_cooldown(self):
        event=self.event();old=list(event.get_result().chain)
        async def failed(router,event):raise ValueError()
        await guarded_result(failed)(self.router(),event)
        self.assertEqual(event.get_result().chain,old)
        r=self.router();r.condition_checker.check_all=lambda *a,**k:types.SimpleNamespace(passed=False)
        original=AsyncMock()
        result=await guarded_manual(original)(r,event,'读这一句')
        self.assertFalse(result[0]);original.assert_not_awaited()

    async def test_cleanup_never_deletes_files_outside_router_directory(self):
        with tempfile.TemporaryDirectory() as other:
            path=Path(other)/'original.mp3';path.write_bytes(b'original')
            event=self.event(private=True);record=Record(path)
            protect_delivery(event,[record],'文字',root=self.root)
            await event.send(Chain([record]))
            self.assertTrue(path.exists())

    async def test_manual_failure_preserves_current_decoder_reason(self):
        router = self.router()
        router._recent_reasons = {}
        event = self.event(prompt='发个语音')
        async def failed(r, e):
            r._recent_reasons[e.unified_msg_origin] = (1, '请在 AstrBot 运行环境安装 ffmpeg')
        await guarded_result(failed)(router, event)
        self.assertIn('安装 ffmpeg', event.get_result().chain[0].text)

    async def test_manual_failure_does_not_reuse_old_reason(self):
        router = self.router()
        event = self.event(prompt='发个语音')
        router._recent_reasons = {event.unified_msg_origin: (1, '旧的余额错误')}
        await guarded_result(AsyncMock())(router, event)
        self.assertNotIn('旧的余额错误', event.get_result().chain[0].text)
        self.assertIn('本次未生成语音', event.get_result().chain[0].text)

    async def test_progressive_voice_uses_current_conversation_misses_and_ceiling(self):
        r=self.router(voice_probability=.1,voice_probability_step=.2,voice_probability_max=.5)
        observed=[]
        def check(*args,enable_probability=True,**kwargs):
            if enable_probability:observed.append(r.condition_checker.prob)
            return types.SimpleNamespace(passed=not enable_probability)
        r.condition_checker.check_all=check
        async def original(router,event):
            router.condition_checker.check_all('原回复',object())
        wrapped=guarded_result(original)
        for _ in range(4):await wrapped(r,self.event())
        await wrapped(r,self.event(umo='napcat:FriendMessage:1'))
        await wrapped(r,self.event(umo='other:GroupMessage:1'))
        for actual,expected in zip(observed,[.1,.3,.5,.5,.1,.1]):self.assertAlmostEqual(actual,expected)
        self.assertEqual(_voice_counters(r).get('napcat:GroupMessage:1'),4)
        self.assertEqual(_voice_counters(r).get('napcat:FriendMessage:1'),1)

    async def test_zero_base_can_accumulate_when_step_is_positive(self):
        r=self.router(voice_probability=0,voice_probability_step=.1,voice_probability_max=.3)
        observed=[]
        def check(*args,enable_probability=True,**kwargs):
            if enable_probability:observed.append(r.condition_checker.prob)
            return types.SimpleNamespace(passed=not enable_probability)
        r.condition_checker.check_all=check
        async def original(router,event):router.condition_checker.check_all('原回复',object())
        await guarded_result(original)(r,self.event())
        await guarded_result(original)(r,self.event())
        self.assertEqual(observed,[0,.1])

    async def test_synthesis_or_delivery_failure_does_not_reset_until_actual_record_send(self):
        r=self.router(voice_probability_step=.1)
        async def failed(router,event):raise RuntimeError()
        await guarded_result(failed)(r,self.event(private=True))
        key='napcat:GroupMessage:1'
        self.assertEqual(_voice_counters(r).get(key),1)
        cache=self.root/'progressive.mp3';cache.write_bytes(b'audio')
        async def generated(router,event):event.get_result().chain=[Record(cache)]
        event=self.event(private=True)
        await guarded_result(generated)(r,event)
        self.assertEqual(_voice_counters(r).get(key),2)
        await event.send(event.get_result())
        self.assertEqual(_voice_counters(r).get(key),0)
        broken=self.event(private=True)
        async def sender(message):
            if isinstance(message.chain[0],Record):raise TimeoutError()
        broken.send=sender
        await guarded_result(generated)(r,broken)
        await broken.send(broken.get_result())
        self.assertEqual(_voice_counters(r).get(key),1)

    async def test_cooldown_and_other_gates_do_not_accumulate_misses(self):
        r=self.router(voice_probability_step=.1)
        r.condition_checker.check_all=lambda *a,**k:types.SimpleNamespace(passed=False)
        original=AsyncMock()
        await guarded_result(original)(r,self.event())
        original.assert_not_awaited()
        self.assertIsNone(getattr(r,'_fatfish_voice_misses',None))
        r=self.router(voice_probability_step=.1)
        r.context.get_registered_star=lambda name:None
        await guarded_result(original)(r,self.event())
        self.assertIsNone(getattr(r,'_fatfish_voice_misses',None))

    async def test_concurrent_conversations_keep_their_effective_probability(self):
        r=self.router(voice_probability=.1,voice_probability_step=.2)
        _voice_counters(r).record('napcat:GroupMessage:1',sent=False)
        observed={};all_started=asyncio.Event();entered=0
        async def original(router,event):
            nonlocal entered
            entered+=1
            if entered==2:all_started.set()
            await all_started.wait()
            router.condition_checker.check_all('原回复',object())
        # Observe inside the actual synchronous checker where the contextual
        # value is installed, not a shared attribute during the preceding await.
        def check(*args,enable_probability=True,**kwargs):
            if enable_probability:
                observed[asyncio.current_task().get_name()]=r.condition_checker.prob
            return types.SimpleNamespace(passed=True)
        r.condition_checker.check_all=check
        wrapped=guarded_result(original)
        a=asyncio.create_task(wrapped(r,self.event()),name='group')
        b=asyncio.create_task(wrapped(r,self.event(umo='napcat:FriendMessage:1')),name='private')
        await asyncio.gather(a,b)
        self.assertAlmostEqual(observed['group'],.3);self.assertAlmostEqual(observed['private'],.1)
        self.assertEqual(r.condition_checker.prob,.1)

    async def test_manual_voice_success_resets_same_conversation_counter(self):
        r=self.router(voice_probability_step=.1);key='napcat:GroupMessage:1'
        _voice_counters(r).record(key,sent=False)
        cache=self.root/'manual.mp3';cache.write_bytes(b'audio')
        async def original(router,event,text):return True,[Record(cache)],text
        event=self.event(private=True)
        ok,chain,_=await guarded_manual(original)(r,event,'原来这一句')
        self.assertTrue(ok);self.assertEqual(_voice_counters(r).get(key),2)
        await event.send(Chain(chain))
        self.assertEqual(_voice_counters(r).get(key),0)

    async def test_false_voice_send_falls_back_once_without_success_callback(self):
        event=self.event(private=True);sent=[];success=[]
        async def sender(message):
            sent.append(message)
            if isinstance(message.chain[0],Record):return False
        event.send=sender;record=Record(self.root/'not-needed.mp3')
        protect_delivery(event,[record],'原有文字',root=self.root,on_success=lambda:success.append(True))
        await event.send(Chain([record]))
        self.assertEqual([p.text for msg in sent for p in msg.chain if isinstance(p,Plain)],['原有文字'])
        self.assertEqual(success,[]);self.assertIs(event.send,sender)

    async def test_manual_alongside_failure_propagates_after_one_text_fallback(self):
        r=self.router(text_alongside_voice=True);event=self.event(private=True);sent=[]
        async def sender(message):
            sent.append(message)
            if isinstance(message.chain[0],Record):raise TimeoutError()
        event.send=sender
        async def original(router,event,text):return True,[Record(self.root/'not-needed.mp3')],text
        ok,chain,_=await guarded_manual(original)(r,event,'原有文字')
        self.assertTrue(ok)
        with self.assertRaisesRegex(RuntimeError,'语音投递失败'):
            await event.send(Chain(chain))
        self.assertEqual([p.text for msg in sent for p in msg.chain if isinstance(p,Plain)],['原有文字'])
        self.assertEqual(_voice_counters(r).get(event.unified_msg_origin),1)
        self.assertIs(event.send,sender)

    async def test_cancelled_manual_delivery_does_not_fallback_or_reset_misses(self):
        r=self.router();event=self.event(private=True);sent=[]
        async def sender(message):
            sent.append(message)
            raise asyncio.CancelledError()
        event.send=sender
        async def original(router,event,text):return True,[Record(self.root/'not-needed.mp3')],text
        _,chain,_=await guarded_manual(original)(r,event,'原有文字')
        with self.assertRaises(asyncio.CancelledError):await event.send(Chain(chain))
        self.assertEqual(len(sent),1)
        self.assertEqual(_voice_counters(r).get(event.unified_msg_origin),1)
        self.assertIs(event.send,sender)

    async def test_installed_native_manual_sender_never_claims_failed_delivery_succeeded(self):
        # Read only the actual installed caller; no plugin startup, provider or
        # account is involved. CI without AstrBot still runs the adapter tests.
        root=Path(os.environ.get('ASTRBOT_TEST_ROOT','D:/Code/Apps/AstrBot'))
        source=root/'data/plugins/astrbot_plugin_tts_emotion_router/main.py'
        if not source.is_file():self.skipTest('Installed AstrBot router unavailable')
        tree=ast.parse(source.read_text(encoding='utf-8-sig'))
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='_send_manual_tts')
        method.decorator_list=[]
        scope={'AstrMessageEvent':object,'VOICE_ONLY_SUPPRESSION_TTL_SECONDS':180,
               'logger':logging.getLogger(__name__),'logging':logging}
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),scope)
        for failure in ('exception','false','cancelled',None):
            with self.subTest(failure=failure):
                r=self.router();event=self.event(private=True);sent=[];suppressed=[]
                event.chain_result=Chain
                async def sender(message):
                    sent.append(message)
                    if isinstance(message.chain[0],Record):
                        if failure=='exception':raise TimeoutError('local-only failure')
                        if failure=='false':return False
                        if failure=='cancelled':raise asyncio.CancelledError()
                event.send=sender
                async def original(router,event,text):return True,[Record(self.root/'not-needed.mp3')],text
                r._build_manual_tts_chain=lambda event,text:guarded_manual(original)(r,event,text)
                r._get_session_state=lambda umo:types.SimpleNamespace(
                    mark_next_llm_plain_text_suppressed=lambda **kwargs:suppressed.append(True))
                call=scope['_send_manual_tts'](r,event,'原有文字',suppress_next_llm_plain_text=True)
                if failure=='cancelled':
                    with self.assertRaises(asyncio.CancelledError):await call
                else:
                    result=await call
                    self.assertEqual('语音已发送' in result,failure is None)
                self.assertEqual(bool(suppressed),failure is None)
                expected=[] if failure in ('cancelled',None) else ['原有文字']
                self.assertEqual([p.text for msg in sent for p in msg.chain if isinstance(p,Plain)],expected)
                self.assertEqual(_voice_counters(r).get(event.unified_msg_origin),0 if failure is None else 1)


SOURCE='''from __future__ import annotations
class Router:
    @filter.on_decorating_result(priority=-1000)
    async def on_decorating_result(self,event):
        check(enable_probability=self.config.is_probability_output_enabled_for_umo(umo),)
    async def _build_manual_tts_chain(self,event,text):
        return False,[],text
'''


class InstallerTests(unittest.TestCase):
    def test_upgrades_existing_adapter_once_without_stacking_handlers(self):
        current = patch_source(SOURCE)
        legacy = current.replace(
            'from fatfish_core.audio_tools import ensure_ffmpeg_on_path\nensure_ffmpeg_on_path()\n', '')
        updated = patch_source(legacy)
        self.assertEqual(updated, current)
        self.assertEqual(patch_source(updated), updated)
        self.assertEqual(updated.count('@guarded_result'), 1)

    def test_installer_dry_run_preserves_secrets_apply_is_idempotent_and_keeps_unrelated_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);plugin=root/'data/plugins/astrbot_plugin_tts_emotion_router';plugin.mkdir(parents=True)
            (plugin/'metadata.yaml').write_text('version: 3.3.3\nlicense: MIT\n')
            (plugin/'main.py').write_text(SOURCE)
            (plugin/'_conf_schema.json').write_text('{}')
            config=root/'data/config/astrbot_plugin_tts_emotion_router_config.json';config.parent.mkdir()
            config.write_text(json.dumps({'tts_engine':{'minimax':{'key':'local-secret'}},'preserve':42}))
            preview=configure(root)
            self.assertFalse(preview['applied']);self.assertNotIn(MARKER,(plugin/'main.py').read_text())
            self.assertNotIn('local-secret',str(preview))
            applied=configure(root,apply=True)
            self.assertTrue(applied['backup_created'])
            current=json.loads(config.read_text())
            self.assertEqual(current['preserve'],42);self.assertEqual(current['tts_engine']['minimax']['key'],'local-secret')
            self.assertFalse(current['fatfish_policy']['enabled']);self.assertEqual(current['probability']['prob'],.1)
            self.assertFalse(current['emotion_route']['marker']['enable'])
            self.assertEqual(configure(root,apply=True)['changed_files'],[])
            self.assertEqual(patch_source(patch_source(SOURCE)),patch_source(SOURCE))
            main=root/'data/cmd_config.json'
            main.write_text(json.dumps({'provider':[{'id':'keep-llm'}],'provider_tts_settings':{'enable':True,'provider_id':'old-tts'}}))
            key=root/'key.env';key.write_text('local-minimax-key')
            receipt=root/'clone.json';receipt.write_text(json.dumps({'clone_state':'accepted','authorized':True,'voice_id':'AppleLeTest2026','sha256':'reference-hash'}))
            result=configure(root,apply=True,key_file=key,clone_receipt=receipt,umos=['napcat:GroupMessage:123'])
            current=json.loads(config.read_text());native=json.loads(main.read_text())
            self.assertEqual(current['tts_engine']['provider'],'minimax')
            self.assertEqual(current['tts_engine']['minimax']['voice_id'],'AppleLeTest2026')
            self.assertEqual(current['tts_engine']['minimax']['key'],'local-minimax-key')
            self.assertFalse(current['emotion_route']['enable'])
            self.assertEqual(native['provider'],[{'id':'keep-llm'}])
            self.assertFalse(native['provider_tts_settings']['enable'])
            self.assertEqual(current['feature_policies']['voice_output']['enabled_umos'],['napcat:GroupMessage:123'])
            self.assertEqual(native['provider_tts_settings']['provider_id'],'old-tts')
            saved=root/'data/plugin_data/astrbot_plugin_fatfish_voice/minimax-voice.json'
            self.assertNotIn('local-minimax-key',saved.read_text());self.assertNotIn('local-minimax-key',str(result))

    def test_unrecognized_upstream_shape_is_not_silently_patched(self):
        with self.assertRaises(ValueError):patch_source('class Changed: pass')


if __name__=='__main__':unittest.main()
