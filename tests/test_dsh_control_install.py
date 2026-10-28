import unittest
from scripts.dsh_install_control import add_patch


class ControlInstallTests(unittest.TestCase):
    def test_blank_profile_becomes_valid_patch_list(self):
        result=add_patch('# comments\n[]\n', {'identity':{'botId':'1','ownerId':'2'}})
        self.assertNotIn('[]',result)
        self.assertIn('fatfish-control',result)

    def test_native_expressions_and_user_parameters_remain_unchanged(self):
        before='- id: existing\n  config:\n    cwd: !!js process.cwd()\n    example_secret: test-only\n'
        after=add_patch(before,{'voice':{'basePercent':15}})
        self.assertTrue(after.startswith(before.rstrip()))
        self.assertEqual(add_patch(after,{'voice':{'basePercent':25}}),after)

    def test_existing_unmanaged_control_row_is_not_duplicated(self):
        for source in ('- id: fatfish-control\n','- {"id":"fatfish-control","config":{}}\n'):
            with self.assertRaises(RuntimeError): add_patch(source,{})

    def test_joined_old_marker_is_repaired_without_resetting_installed_controls(self):
        existing = ('- id: time-context\n  name: "@deepseek-ai/dsh-time-context"# <<< fatfish-managed\n\n'
                    '# >>> fatfish-control\n- {"id":"fatfish-control","config":{"voice":{"basePercent":15}}}\n'
                    '# <<< fatfish-control\n')
        repaired = add_patch(existing, {'voice': {'basePercent': 99}})
        self.assertIn('"@deepseek-ai/dsh-time-context"\n# <<< fatfish-managed', repaired)
        self.assertIn('"basePercent":15', repaired)
        self.assertNotIn('99', repaired)
        self.assertEqual(add_patch(repaired, {}), repaired)
