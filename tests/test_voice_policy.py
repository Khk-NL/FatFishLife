import asyncio
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

from fatfish_core.voice_policy import (DEFAULT_POLICY, guarded_result, guarded_manual,
                                      protect_delivery, MANUAL_REQUEST)
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


SOURCE='''from __future__ import annotations
class Router:
    @filter.on_decorating_result(priority=-1000)
    async def on_decorating_result(self,event):
        check(enable_probability=self.config.is_probability_output_enabled_for_umo(umo),)
    async def _build_manual_tts_chain(self,event,text):
        return False,[],text
'''


class InstallerTests(unittest.TestCase):
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
