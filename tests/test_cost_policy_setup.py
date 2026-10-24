import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from scripts.configure_cost_policy import configure


class CostPolicySetupTests(unittest.TestCase):
    def test_local_model_and_isolation_preserve_existing_keys_and_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=root/'data';(data/'config').mkdir(parents=True);model=root/'model';model.mkdir()
            main={'provider_sources':[{'id':'deepseek','key':['existing-private-test-key']}],
                  'provider':[{'id':'deepseek/flash','provider_source_id':'deepseek','custom_extra_body':{}}],
                  'agent_runner':{'config':{'model':{},'misc':{},'compression':{}}},'provider_settings':{},
                  'provider_ltm_settings':{'active_reply':{'enable':True}}}
            (data/'cmd_config.json').write_text(json.dumps(main),encoding='utf-8')
            (data/'config/astrbot_plugin_self_learning_config.json').write_text(json.dumps({'nested':{'enable_affection_system':True,'filter_provider_id':None,'keep':'yes'}}),encoding='utf-8')
            (data/'config/astrbot_plugin_token_controller_config.json').write_text(json.dumps({'limited_groups':[],'over_limit_policy':{}}),encoding='utf-8')
            with closing(sqlite3.connect(data/'data_v4.db')) as db, db:
                db.execute('CREATE TABLE provider_stats(umo TEXT)');db.executemany('INSERT INTO provider_stats VALUES(?)',[('napcat:GroupMessage:123',),('napcat:FriendMessage:123',)])
            self.assertFalse(configure(root,model)['applied'])
            self.assertFalse((model/'api-key.local').exists())
            report=configure(root,model,apply=True)
            saved=json.loads((data/'cmd_config.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['provider_sources'][0]['key'],['existing-private-test-key'])
            self.assertFalse(saved['platform_settings']['unique_session'])
            self.assertFalse(saved['platform_settings']['reply_with_quote'])
            self.assertFalse(saved['platform_settings']['segmented_reply']['enable'])
            self.assertTrue(saved['provider_settings']['buffer_intermediate_messages'])
            self.assertEqual(saved['agent_runner']['config']['compression']['provider_id'],'fatfish_context_local')
            compression = saved['agent_runner']['config']['compression']
            self.assertEqual(compression['max_turns'], -1)
            self.assertEqual(compression['fallback_max_tokens'], 12000)
            self.assertEqual(compression['keep_recent_ratio'], .3)
            self.assertEqual(saved['provider'][0]['max_context_tokens'], 12000)
            self.assertNotIn((model/'api-key.local').read_text(),str(report))
            self.assertEqual(report['limited_group_count'],1)
            self.assertEqual(configure(root,model,apply=True)['changed_files'],[])
