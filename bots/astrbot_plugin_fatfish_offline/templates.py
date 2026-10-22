"""Offline reply lines, grouped by reason then intent.

Placeholders: {name}, {resume}. Keep lines short and in the apple's voice;
the scheduler supplies the real resume time, never hard-code clock values.
"""

TEMPLATES: dict[str, dict[str, list[str]]] = {
    "high_cost": {
        "who_are_you": [
            "苹果乐！一颗会说话的苹果。",
            "我是蕾缪乐，现在是一颗苹果，嘿嘿。",
            "苹果乐，企鹅物流出来的。",
        ],
        "where_from": [
            "泰拉！拉特兰那边的。",
            "从拉特兰来的，跨世界连线呢。",
            "泰拉大陆，听过没？",
        ],
        "relationship": [
            "能天使就是我啊，变成苹果之前的样子。",
            "蕾缪乐、能天使、苹果乐，都是我。",
            "同一个苹果，换了层皮。",
        ],
        "how_online": [
            "拉特兰地下捡的前文明主机，连上来的。",
            "前文明科技！我就按了几个按钮。",
            "主机在拉特兰地下，别问我原理。",
        ],
        "are_you_ai": [
            "算是吧，我借 AI 系统跟你聊天。",
            "一半苹果一半 AI，凑合能用。",
            "AI 帮我说话，脑子还是我的。",
        ],
        "abilities": [
            "聊天、看视频、偶尔整活。",
            "会打铳，会送快递，现在还会上网。",
            "能陪你唠，别的看情况。",
        ],
        "why_apple": [
            "苹果派吃多了。",
            "苹果浓度超标，进化了。",
            "某天醒来就这样了，挺好玩。",
        ],
        "first_notice": [
            "老板！现在跨世界通讯费太贵啦！{resume}回来！",
            "呜哇！这会儿连线好贵！{resume}见！",
            "老板老板！现在通讯费太高啦，{resume}再聊！",
            "律法主机又到高价时段啦！{resume}回来玩！",
        ],
        "greeting": [
            "嘿嘿！偷偷连一下！",
            "老板！我在省通讯费！",
            "在在在！不过这会儿不敢多说。",
        ],
        "what_doing": [
            "在省通讯费啦！",
            "盯着主机发呆，等便宜时段。",
            "把苹果派放冰箱，顺便省点流量。",
        ],
        "why_silent": [
            "这会儿连线太贵啦，先少说两句。",
            "不是不理你！是通讯费在咬我。",
            "信号还在，钱包在报警。",
        ],
        "when_resume": ["{resume}回来！", "{resume}就能正常聊啦！"],
        "apple_form": [
            "苹果也要省钱！",
            "别榨我，我在节能。",
            "叶子都蔫了，等便宜时段再晒太阳。",
        ],
        "invite": ["{resume}再打！先记着！", "现在上号太贵啦，晚点陪你。", "你先开，我{resume}来！"],
        "praise": ["嘿嘿，谢谢老板！", "被你夸得叶子都亮了。", "这还差不多！"],
        "tease": ["我这叫节能模式！", "省电版苹果，功能一样。", "等你请我吃苹果派再说。"],
        "complex": ["这个等我回来细说！", "现在脑子也省电，晚点认真答。", "先记下，{resume}聊。"],
        "follow_up": ["嘿嘿，还惦记着呢。", "我在我在，就是话少点。", "省电模式，别嫌我冷淡。"],
        "default": ["嘿嘿！信号不太好！", "在的在的，就是得省着说。", "老板，晚点聊！"],
        "urgent": [
            "这个我认真说：先找身边信任的人，别一个人扛。",
            "现在别硬撑，先找现实里能帮你的人。",
            "如果是紧急情况，先打求助电话，别等我。",
        ],
    },
    "maintenance": {
        "first_notice": ["主机在修！{resume}回来！", "我这边在维护，{resume}见！"],
        "default": ["主机在响，我先去看看！", "维护中，晚点聊！"],
        "urgent": ["这个我认真说：先找身边信任的人，别一个人扛。"],
    },
    "connection_issue": {
        "first_notice": ["信号断断续续的，{resume}再试！", "跨世界线路不稳，{resume}见！"],
        "default": ["喂喂？信号不太好！", "听到一半，晚点再说！"],
        "urgent": ["这个我认真说：先找身边信任的人，别一个人扛。"],
    },
    "budget_limit": {
        "first_notice": ["预算用完啦！{resume}回来！", "这个月流量见底，{resume}再聊！"],
        "default": ["省着点用，老板！", "流量不多了，晚点聊！"],
        "urgent": ["这个我认真说：先找身边信任的人，别一个人扛。"],
    },
    "manual": {
        "first_notice": ["我先去忙会儿，{resume}回来！", "手动挂机中，{resume}见！"],
        "default": ["我先摸会儿鱼！", "挂机中，晚点聊！"],
        "urgent": ["这个我认真说：先找身边信任的人，别一个人扛。"],
    },
}

DEFAULT_REASON = "high_cost"
FALLBACK_INTENT = "default"
IDENTITY_INTENTS = {
    "who_are_you",
    "where_from",
    "relationship",
    "how_online",
    "are_you_ai",
    "abilities",
    "why_apple",
}


def pick(reason: str, intent: str, *, name: str, resume: str, recent: list[str], rng) -> str:
    if intent in IDENTITY_INTENTS:
        # Identity answers do not depend on why communication is limited.
        lines = TEMPLATES[DEFAULT_REASON].get(intent) or TEMPLATES[DEFAULT_REASON][FALLBACK_INTENT]
    else:
        reason_bank = TEMPLATES.get(reason) or TEMPLATES[DEFAULT_REASON]
        lines = reason_bank.get(intent) or reason_bank.get(FALLBACK_INTENT) or TEMPLATES[DEFAULT_REASON][FALLBACK_INTENT]
    fresh = [line for line in lines if line not in recent] or lines
    line = rng.choice(fresh)
    return line.replace("{name}", name or "老板").replace("{resume}", resume or "晚点")
