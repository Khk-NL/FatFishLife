import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

from fatfish_core import proactive_probability as gate
from scripts.configure_proactive_probability import configure, patch_flow, patch_override


FLOW = '''from __future__ import annotations
class Flow:
    async def check_and_chat(self, session_id):
        normalized_session_id = session_id
        session_config = self.session_config
        try:
            request_package = await self._prepare_llm_request(normalized_session_id)
            sent_ok = await self._send_proactive_message(session_id, request_package)
            if not sent_ok:
                await self._schedule_next_chat_and_save(session_id)
                return
            await self._finalize_and_reschedule(session_id)
        finally:
            pass
'''
OVERRIDES = '''class Overrides:
    ALLOWED_ROOT_KEYS = {
        "schedule_settings",
    }
'''


class ProactiveProbabilityTests(unittest.IsolatedAsyncioTestCase):
    def plugin(self, **config):
        namespace={};exec(patch_flow(FLOW),namespace)
        plugin=namespace['Flow']()
        plugin.session_config={'probability_settings':{'base':.1,'step':.1,'max':.3,**config}}
        plugin._normalize_session_id=lambda value:value
        plugin.manual_trigger_sessions=set()
        plugin._prepare_llm_request=AsyncMock(return_value={'prepared':True})
        plugin._send_proactive_message=AsyncMock(return_value=True)
        plugin._schedule_next_chat_and_save=AsyncMock()
        plugin._finalize_and_reschedule=AsyncMock()
        return plugin

    async def test_missed_draw_reschedules_without_model_or_send(self):
        plugin=self.plugin();session='napcat:FriendMessage:1'
        with patch.object(gate,'_offline',return_value=False),patch.object(gate.random,'random',return_value=.99):
            await plugin.check_and_chat(session)
        plugin._prepare_llm_request.assert_not_awaited()
        plugin._send_proactive_message.assert_not_awaited()
        plugin._schedule_next_chat_and_save.assert_awaited_once_with(session)
        self.assertEqual(plugin._fatfish_proactive_misses.get(session),1)

    async def test_hits_use_full_session_counter_and_reset_only_after_true_send(self):
        plugin=self.plugin();one='napcat:FriendMessage:1';other='other:FriendMessage:1'
        with patch.object(gate,'_offline',return_value=False),patch.object(gate.random,'random',return_value=.99):
            for _ in range(3):gate.proactive_probability_allowed(plugin,one,plugin.session_config)
        self.assertEqual(plugin._fatfish_proactive_misses.get(other),0)
        with patch.object(gate,'_offline',return_value=False),patch.object(gate.random,'random',return_value=.25):
            self.assertTrue(gate.proactive_probability_allowed(plugin,one,plugin.session_config))
            self.assertFalse(gate.proactive_probability_allowed(plugin,other,plugin.session_config))
        self.assertEqual(plugin._fatfish_proactive_misses.get(one),4)
        plugin._send_proactive_message.return_value=False
        with patch.object(gate,'_offline',return_value=False),patch.object(gate.random,'random',return_value=0):
            await plugin.check_and_chat(one)
        self.assertEqual(plugin._fatfish_proactive_misses.get(one),5)
        plugin._finalize_and_reschedule.assert_not_awaited()
        plugin._send_proactive_message.return_value=True
        with patch.object(gate,'_offline',return_value=False),patch.object(gate.random,'random',return_value=0):
            await plugin.check_and_chat(one)
        self.assertEqual(plugin._fatfish_proactive_misses.get(one),0)

    async def test_offline_and_fully_disabled_do_not_accumulate_or_generate(self):
        plugin=self.plugin(base=0,step=0);session='napcat:FriendMessage:1'
        with patch.object(gate,'_offline',return_value=False):await plugin.check_and_chat(session)
        self.assertFalse(hasattr(plugin,'_fatfish_proactive_misses'))
        plugin.manual_trigger_sessions.add(session)
        with patch.object(gate,'_offline',return_value=True):await plugin.check_and_chat(session)
        plugin._prepare_llm_request.assert_not_awaited()
        with patch.object(gate,'_offline',return_value=False):await plugin.check_and_chat(session)
        plugin._prepare_llm_request.assert_awaited_once()

    async def test_installer_preserves_scope_and_schedule_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plugin=root/'data/plugins/astrbot_plugin_proactive_chat';(plugin/'core').mkdir(parents=True)
            (plugin/'metadata.yaml').write_text('version: "v1.2.6"\n')
            (plugin/'LICENSE').write_text('GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3')
            (plugin/'core/chat_flow.py').write_text(FLOW)
            (plugin/'core/session_override_manager.py').write_text(OVERRIDES)
            (plugin/'_conf_schema.json').write_text(json.dumps({'friend_settings':{'items':{}},'group_settings':{'items':{}}}))
            config=root/'data/config/astrbot_plugin_proactive_chat_config.json';config.parent.mkdir()
            friend={'enable':True,'session_list':['napcat:FriendMessage:1'],'schedule_settings':{'quiet_hours':'1-7'},'local_key':'secret-local'}
            config.write_text(json.dumps({'friend_settings':friend,'group_settings':{'enable':False,'session_list':[]}}))
            preview=configure(root);self.assertFalse(preview['applied']);self.assertNotIn('secret-local',str(preview))
            configure(root,apply=True);current=json.loads(config.read_text())
            for key,value in friend.items():self.assertEqual(current['friend_settings'][key],value)
            self.assertFalse(current['group_settings']['enable'])
            self.assertEqual(current['friend_settings']['probability_settings'],gate.DEFAULTS)
            self.assertEqual(configure(root,apply=True)['changed_files'],[])
            self.assertIn('"probability_settings"',(plugin/'core/session_override_manager.py').read_text())

    async def test_unknown_upstream_shape_is_rejected(self):
        with self.assertRaises(ValueError):patch_flow('changed')
        with self.assertRaises(ValueError):patch_override('changed')
