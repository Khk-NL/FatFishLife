import unittest
from fatfish_core.prts_stories import chapter_catalog,room_sections


class StorySourceTests(unittest.TestCase):
    def test_only_actual_story_links_in_the_matching_activity_row_are_indexed(self):
        html='<table><tr><th>喧闹法则</th><td><a title="CB-1 入夜/BEG" href="/w/CB-1/BEG">开始</a><a title="活动公告" href="/w/公告">公告</a></td></tr><tr><th>别的活动</th><td><a title="LE-1/END" href="/w/LE-1/END">结束</a></td></tr></table>'
        data=chapter_catalog(html,['喧闹法则'])
        self.assertEqual(list(data),['喧闹法则'])
        self.assertEqual(len(data['喧闹法则']),1)
        self.assertTrue(data['喧闹法则'][0]['url'].startswith('https://prts.wiki/w/'))

    def test_event_overviews_are_separated_by_real_anchors(self):
        data=room_sections('<p id="活动甲" style="margin:0;padding:0;"></p><table><tr><td>事件一</td></tr></table><p id="活动乙" style="margin:0;padding:0;"></p><table><tr><td>事件二</td></tr></table>')
        self.assertIn('事件一',data['活动甲'])
        self.assertNotIn('事件二',data['活动甲'])


if __name__=='__main__':unittest.main()
