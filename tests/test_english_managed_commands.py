import unittest
import inspect
import types
from unittest.mock import AsyncMock, Mock, patch

import test_bili_plugin as bili_fixture
import test_memory_plugin as memory_fixture
import test_offline_plugin as offline_fixture
import test_life_plugin as life_fixture
import test_obsidian as kb_fixture
import test_steam as steam_fixture
import test_story_plugin as video_fixture


class EnglishManagedCommandTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, case):
        fixture = case()
        fixture.setUp()
        for callback,args,kwargs in fixture._cleanups:
            self.addCleanup(callback,*args,**kwargs)
        fixture._cleanups.clear()
        return fixture

    async def test_life_help_is_english_and_diary_uses_the_existing_private_record(self):
        fixture = self.fixture(life_fixture.LifePluginTests)
        event = life_fixture.Event(admin=True)
        help_text = (await fixture.command(event, "help"))[0]
        self.assertTrue(help_text.isascii())
        self.assertIn("/life preview", help_text)
        day = life_fixture.DAY
        fixture.plugin.state.data.setdefault("days", {})[day] = {"journal": "今天想摸鱼。"}
        self.assertEqual(await fixture.command(event, "diary"), ["今天想摸鱼。"])
        self.assertEqual(await fixture.command(event, "日记"), ["今天想摸鱼。"])

    async def test_video_english_preview_and_approval_keep_the_review_boundary(self):
        fixture = self.fixture(video_fixture.StoryPluginTests)
        help_text = (await fixture.invoke("help"))[0]
        self.assertTrue(help_text.isascii())
        self.assertIn("/video approve <review-id>", help_text)
        with patch("fatfish_story.review.publish", return_value=Mock(as_dict=lambda: {"url": "https://www.bilibili.com/video/BV1234567890"})) as publish:
            rejected = await fixture.invoke("approve", fixture.row["id"])
            self.assertTrue(rejected)
            publish.assert_not_called()
            await fixture.invoke("preview", fixture.row["id"])
            self.assertEqual(fixture.event.send.await_count, 3)
            await fixture.invoke("approve", fixture.row["id"])
            publish.assert_called_once()

    async def test_video_create_preserves_topic_body_and_does_not_import_or_publish(self):
        fixture = self.fixture(video_fixture.StoryPluginTests)
        topic = "能天使与德克萨斯的午休 / Keep Case"
        fixture.plugin._prepare_updream = AsyncMock(return_value={"id": "brief-test", "brief": {"title": "午休"}, "path": "local-brief.md"})
        await fixture.invoke("create", topic)
        fixture.plugin._prepare_updream.assert_awaited_once_with(topic, fixture.event)
        fixture.event.send.assert_not_awaited()

    async def test_kb_english_search_preserves_the_question_and_private_guard(self):
        fixture = self.fixture(kb_fixture.ObsidianPluginTests)
        event = fixture.event()
        fixture.plugin._search = AsyncMock(return_value="私人资料")
        help_text = [value async for value in fixture.plugin.knowledge(event, "help")]
        self.assertTrue(help_text[0].isascii())
        question = "Cloud API / 大小写 保留"
        replies = [value async for value in fixture.plugin.knowledge(event, "search", question)]
        self.assertEqual(replies, ["私人资料"])
        fixture.plugin._search.assert_awaited_once_with(question)
        blocked = [value async for value in fixture.plugin.knowledge(fixture.event(private=False), "search", question)]
        self.assertIn("仅供老大私聊", blocked[0])
        self.assertEqual(fixture.plugin._search.await_count, 1)

    async def test_steam_english_actions_share_existing_lookup_and_help_does_not_call_it(self):
        fixture = self.fixture(steam_fixture.SteamPluginTests)
        fixture.plugin._lookup = AsyncMock(return_value="游戏价格")
        help_text = [value async for value in fixture.plugin.steam(fixture.event, "help")]
        self.assertTrue(help_text[0].isascii())
        self.assertIn("/steam price", help_text[0])
        fixture.plugin._lookup.assert_not_awaited()
        for query, expected in (("price 620", "620"), ("search Portal 2", "Portal 2"), ("价格 620", "620"), ("620", "620")):
            result = [value async for value in fixture.plugin.steam(fixture.event, query)]
            self.assertEqual(result, ["游戏价格"])
            fixture.plugin._lookup.assert_awaited_with(expected)


class EnglishBiliCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = bili_fixture.BiliPrivacyTests()
        self.fixture.setUp()
        for callback,args,kwargs in self.fixture._cleanups:
            self.addCleanup(callback,*args,**kwargs)
        self.fixture._cleanups.clear()
        self.plugin = self.fixture.plugin

    async def test_help_is_english_without_cli_calls(self):
        text = await bili_fixture.collect(self.plugin.bili(bili_fixture.Event(), 'help'))
        self.assertTrue(text.isascii())
        for command in ('read', 'search', 'feed', 'subscribe', 'resume'):
            self.assertIn(command, text)
        self.plugin._run.assert_not_awaited()

    async def test_english_search_keeps_the_complete_case_sensitive_body(self):
        query = 'Cloud API / 明日方舟 前瞻'
        await bili_fixture.collect(self.plugin.bili(bili_fixture.Event(), 'search', query))
        self.plugin._run.assert_awaited_once_with('search','video',query,'--size','10',timeout=90)

    async def test_english_subscribe_uses_existing_discovery_store(self):
        self.plugin.discovery = Mock(subscribe=Mock(return_value=7))
        query = '明日方舟 Cloud API'
        await bili_fixture.collect(self.plugin.bili(bili_fixture.Event(), 'subscribe', 'keyword '+query))
        self.plugin.discovery.subscribe.assert_called_once_with('keyword',query)
        self.plugin._run.assert_not_awaited()

    async def test_english_write_actions_keep_the_existing_private_boundary(self):
        for event in self.fixture.untrusted_events():
            for action in ('like','favorite','triple','post','dm'):
                text = await bili_fixture.collect(self.plugin.bili(event,action,'BVexample'))
                self.assertIn('私聊',text)
        self.plugin._run.assert_not_awaited()

    async def test_omitted_greedy_body_produces_usage_instead_of_the_type_name(self):
        for action in ('read','search','reply','dm'):
            text = await bili_fixture.collect(self.plugin.bili(bili_fixture.Event(),action))
            self.assertTrue(text.isascii())
            self.assertIn('Usage:',text)
            self.assertNotIn("<class",text)
        self.plugin._run.assert_not_awaited()


class EnglishMemoryCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_english_add_and_legacy_alias_share_scoped_storage(self):
        fixture=memory_fixture.MemoryPluginTests();fixture.setUp()
        for callback,args,kwargs in fixture._cleanups:
            self.addCleanup(callback,*args,**kwargs)
        fixture._cleanups.clear()
        event=memory_fixture.Event('owner',True)
        for action,text in [('add','保留 Cloud API / 大小写'),('记住','旧命令仍兼容')]:
            await memory_fixture.collect(fixture.plugin.memory(event,action,text))
            rows=fixture.plugin.store.recall(text,scopes=('private',),conversation=('qq',event.unified_msg_origin),conversation_only=True)
            self.assertEqual(len(rows),1)
        help_text=await memory_fixture.collect(fixture.plugin.memory(event,'help'))
        self.assertTrue(help_text.isascii())


class EnglishCoreHelpTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_help_is_english_and_does_not_need_runtime_services(self):
        from plugin_support import load_plugin
        for name, method, args in [
            ('lore','lore',()), ('style','style_command',('help',)), ('offline','offline',('help',))]:
            modules={'offline':offline_fixture.PLUGIN,'memory':memory_fixture.PLUGIN,'bili':bili_fixture.PLUGIN,
                     'life':life_fixture.PLUGIN,'story':video_fixture.PLUGIN,'obsidian':kb_fixture.PLUGIN,'steam':steam_fixture.PLUGIN}
            module=modules[name] if name in modules else load_plugin('astrbot_plugin_fatfish_'+name)
            plugin=module.Main.__new__(module.Main)
            event=types.SimpleNamespace(plain_result=lambda value:value)
            text='\n'.join([v async for v in getattr(plugin,method)(event,*args)])
            self.assertTrue(text.isascii(),name)
            self.assertIn('/'+name,text)
        offline=offline_fixture.PLUGIN
        # 顶层帮助是中文分类版，只校验关键命令都在，内容留给人工维护
        for command in ('/memory', '/lore', '/offline', '/bili', '/reset', '/help'):
            self.assertIn(command, offline.HELP_TEXT)
        self.assertNotIn('subscriptions', offline.HELP_TEXT)

    def test_native_greedy_defaults_preserve_multiword_body_contract(self):
        from plugin_support import load_plugin
        handlers=[('memory','memory','text'),('lore','lore','text'),('style','style_command','target'),
                  ('offline','offline','text'),('life','life','text'),('story','video','text'),
                  ('obsidian','knowledge','text'),('steam','steam','query'),('bili','bili','text')]
        for name,method,arg in handlers:
            modules={'offline':offline_fixture.PLUGIN,'memory':memory_fixture.PLUGIN,'bili':bili_fixture.PLUGIN,
                     'life':life_fixture.PLUGIN,'story':video_fixture.PLUGIN,'obsidian':kb_fixture.PLUGIN,'steam':steam_fixture.PLUGIN}
            module=modules[name] if name in modules else load_plugin('astrbot_plugin_fatfish_'+name)
            default=inspect.signature(getattr(module.Main,method)).parameters[arg].default
            self.assertIs(default,module.GreedyStr,name)
