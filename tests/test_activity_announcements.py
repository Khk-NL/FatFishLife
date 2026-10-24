import unittest
from scripts.supplement_activity_announcements import activity_type
from fatfish_core.graph_build import file_documents
from pathlib import Path
import tempfile
class EvidenceTests(unittest.TestCase):
 def test_announcement_only_does_not_claim_story(self):
  value=activity_type('活动公告\n稳态测定签到活动开启')
  self.assertEqual(value[0],'签到');self.assertIsNone(activity_type('资料不详'))
 def test_activity_type_precedes_generic_challenge(self):
  self.assertEqual(activity_type('EP16 反常光谱作战环境\n活动关卡')[0],'主线章节')
 def test_structured_activity_type_is_evidence_backed(self):
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'活动梗概.md';path.write_text('## 众生行记\n- 活动性质：SideStory；同期限定寻访新增新约能天使。\n- 登场：能天使\n',encoding='utf-8')
   row=next(file_documents(Path(temp),'lore'))
   self.assertIn('新约能天使',row['structured']['relations'][-1]['evidence'])
   self.assertEqual(row['structured']['relations'][-1]['predicate'],'活动类型')
if __name__=='__main__':unittest.main()
