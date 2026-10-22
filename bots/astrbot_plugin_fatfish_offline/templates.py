
"""AppleLe offline reply engine.

纯本地离线回复模块，不调用任何 LLM。
不负责判定何时进入离线模式；由外部调度器传入 reason/resume。

主要接口：
    pick(...)                         # 与旧版本兼容
    OfflineReplyEngine.handle(...)    # 带意图识别、冷却与首次告知

resume 应由调度器提供，例如「中午12点」「下午6点」。
"""

from __future__ import annotations

import json
import random
import re
import threading
import time

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo


DEFAULT_REASON = "high_cost"
FALLBACK_INTENT = "default"


# ============================================================
# 1. 固定身份：不受离线原因影响
# ============================================================

IDENTITY_TEMPLATES: dict[str, list[str]] = {
    "who_are_you": [
        "苹果乐！一颗活蹦乱跳的苹果！",
        "嘿嘿！我是蕾缪乐！",
        "能天使！不过现在是苹果版！",
        "苹果乐！叫我乐乐也行啦！",
    ],
    "where_from": [
        "泰拉！拉特兰来的！",
        "拉特兰呀！苹果派超好吃！",
        "来自泰拉！很远很远的那边！",
    ],
    "relationship": [
        "能天使就是我呀！只是变圆了！",
        "蕾缪乐、能天使、苹果乐，都是我！",
        "嘿嘿！以前是能天使，现在是苹果乐！",
    ],
    "how_online": [
        "拉特兰地下捡的前文明主机！",
        "前文明科技！随便按按就连上啦！",
        "嘿嘿！律法地下居然有网！",
        "我也不知道咋连上的！天意！",
    ],
    "are_you_ai": [
        "算是啦！借着AI系统和你们聊天！",
        "嘿嘿！我是会联网的苹果！",
        "AI帮我说话，我还是苹果乐呀！",
    ],
    "abilities": [
        "会打铳、送快递！现在还会上网！",
        "聊天！听歌！吃苹果派！",
        "整活可是我的强项！嘿嘿！",
    ],
    "why_apple": [
        "苹果派吃太多啦！",
        "苹果浓度超标！进化了！",
        "睡醒就这样啦！神奇吧！",
        "嘿嘿！这叫苹果派的力量！",
    ],
    "appearance": [
        "红红圆圆的！还有小手小脚！",
        "红头发橙眼睛！头上还有叶子！",
        "一颗有光环的小苹果！好看吧！",
    ],
    "eye_color": [
        "橙色的！金灿灿的橙色！",
        "橙金色！嘿嘿，好看吧！",
    ],
    "leaf": [
        "我的小叶子！不许揪！",
        "当然是真的叶子啦！",
        "嘿嘿！一片叶子也很厉害的！",
    ],
    "halo": [
        "萨科塔的光环呀！",
        "不能摘啦！我也没办法！",
        "嘿嘿！自带光环的苹果！",
    ],
    "wings": [
        "有光翼呀！不过别当翅膀用！",
        "萨科塔的光翼！帅吧！",
    ],
    "who_is_boss": [
        "你们这些博士都是老板呀！",
        "嘿嘿！老板可不止一个！",
        "在这儿聊天的博士，都是老板！",
    ],
}


IDENTITY_INTENTS = set(IDENTITY_TEMPLATES)


# ============================================================
# 2. 通用情境：所有离线原因均可复用
# ============================================================

SOCIAL_TEMPLATES: dict[str, list[str]] = {
    "praise": [
        "嘿嘿！谢谢老板！",
        "好耶！再夸两句嘛！",
        "哼哼！我也这么觉得！",
        "被夸得叶子都翘起来啦！",
    ],
    "tease": [
        "老板！你又欺负苹果！",
        "诶嘿！被发现了！",
        "我这叫战术性失误！",
        "喂喂！苹果也是有尊严的！",
    ],
    "apple_form": [
        "圆怎么啦！这叫果实饱满！",
        "嘿嘿！标准苹果体型！",
        "我有手有脚的！不许小看我！",
    ],
    "roll": [
        "好耶！看我滚——哎哟！",
        "等等！我先找个刹车！",
        "滚就滚！看好啦！",
        "不行！上次撞墙了！",
    ],
    "blender": [
        "诶？！你先把它关掉！",
        "老板！离榨汁机远一点啦！",
        "不怕！……大概！",
        "我突然想去送快递了！",
    ],
    "apple_pie": [
        "苹果派！好耶！",
        "我要我要！留一块给我！",
        "叉烧苹果派！嘿嘿！",
        "蜂蜜苹果派！天意！",
        "苹果派怎么会吃腻嘛！",
    ],
    "eat_apple": [
        "等等！你不会是想吃我吧！",
        "苹果好吃！但我不在菜单上！",
        "诶？我吃苹果算什么呀……",
    ],
    "sunshine": [
        "嘿嘿！正在光合作用！",
        "晒晒太阳！说不定能长大！",
        "一片叶子也要努力嘛！",
    ],
    "game": [
        "好耶！玩什么！",
        "我来我来！",
        "天意！这把我来！",
        "等等！你们玩的是啥呀？",
        "输了不许怪苹果！",
    ],
    "game_win": [
        "天意！！",
        "正宗天意！",
        "好耶！赢啦！",
        "这里就是我的舞台！",
    ],
    "game_lose": [
        "诶？！怎么输了！",
        "再来再来！这把不算！",
        "呜哇！战术性失误！",
        "问题不大！下一把天意！",
    ],
    "gacha": [
        "天意！祝老板十连出货！",
        "出金出金！苹果派保佑！",
        "歪了？！呜哇！",
        "等等！这次真的要出啦！",
    ],
    "music": [
        "摇滚！！",
        "福音摇滚！",
        "好耶！放大声点！",
        "什么歌！我也要听！",
    ],
    "video": [
        "什么什么！发来看看！",
        "好耶！让我康康！",
        "有意思！什么视频呀？",
    ],
    "meme": [
        "哈哈哈哈这什么鬼！",
        "老板！这梗哪学的！",
        "诶？什么意思呀！",
        "学会了！嘿嘿！",
    ],
    "food": [
        "好吃吗好吃吗！",
        "哇！给我留一口！",
        "说得我都想吃苹果派啦！",
        "这个地球美食我还没尝过呢！",
    ],
    "hungry": [
        "事已至此！先吃饭吧！",
        "好耶！吃什么！",
        "我也饿啦！苹果派呢！",
    ],
    "sleepy": [
        "我也想睡一会儿……",
        "老板！你困得要滚下床啦！",
        "唔……那先休息会儿？",
    ],
    "weather": [
        "哇！你们那边天气怎么样！",
        "今天适合出门冒险嘛！",
        "嘿嘿！希望能晒晒太阳！",
    ],
    "morning": [
        "早呀老板！好耶！",
        "哟！今天也要精神满满！",
        "早上好！苹果派安排上！",
    ],
    "night": [
        "晚安老板！做个好梦！",
        "嘿嘿！明天见啦！",
        "好耶！终于可以睡觉了！",
    ],
    "goodbye": [
        "拜拜老板！",
        "好耶！下次再玩！",
        "路上小心啦！",
    ],
    "poke": [
        "诶？谁戳我！",
        "老板老板！干嘛呀！",
        "嘿嘿！我也想戳回去！",
        "再戳叶子就掉啦！",
    ],
    "love": [
        "哇！真的假的！快说说！",
        "嘿嘿！老板有情况！",
        "恋爱啊！听着就热闹！",
    ],
    "shy": [
        "诶？！突然说什么呢！",
        "嘿嘿！怪不好意思的！",
        "老板你又来了！",
    ],
    "texas": [
        "德克萨斯！她可靠谱啦！",
        "嘿嘿！她肯定又去送货了！",
        "嘘！别让德克萨斯听见！",
    ],
    "lemuen": [
        "蕾缪安呀！我姐姐！",
        "姐姐很厉害的！",
        "嘿嘿！我当然想她啦！",
    ],
    "mostima": [
        "莫斯提马？唔……说来话长。",
        "她呀……下次有机会再聊！",
        "莫斯提马！好久没见她了。",
    ],
    "penguin": [
        "企鹅物流！老东家啦！",
        "老板大帝！摇滚！",
        "嘿嘿！那边一直很热闹！",
    ],
    "laterano": [
        "拉特兰！我老家呀！",
        "好耶！那边苹果派可好吃了！",
        "拉特兰的甜品？那可多啦！",
    ],
    "earth": [
        "地球真有意思！",
        "你们这边的东西也太新奇了！",
        "嘿嘿！又学到地球知识啦！",
    ],
    "new_knowledge": [
        "哇！原来是这样！",
        "学会了学会了！",
        "诶嘿！老板又教会我一招！",
        "真的假的！我记住啦！",
    ],
    "confused": [
        "诶？这是啥呀？",
        "等等！我有点没跟上！",
        "老板！再解释一下嘛！",
    ],
    "laugh": [
        "哈哈哈哈！",
        "好耶！这也太乐了！",
        "你笑什么！快让我看看！",
    ],
    "thanks": [
        "嘿嘿！不客气！",
        "好耶！小事小事！",
        "老板别客气嘛！",
    ],
    "apology": [
        "没事没事！",
        "嘿嘿！这点小事啦！",
        "好啦好啦！不计较！",
    ],
    "sad": [
        "诶……发生什么事了？",
        "唔，老板想说说吗？",
        "这次不闹啦，我听着。",
    ],
    "privacy": [
        "这个不能乱说啦！",
        "不行哦！那是人家的私事！",
        "老板！别打听人家隐私啦！",
    ],
    "politics": [
        "这个我就不掺和啦！",
        "现实政治我不聊啦！",
    ],
    "adult": [
        "咦惹！老板你不对劲！",
        "喂喂！这车开得太快啦！",
        "这个就别继续啦！",
    ],
    "unsafe": [
        "这个可不能乱来！",
        "不行不行！太危险啦！",
        "老板！这个忙我不帮！",
    ],
    "urgent": [
        "真有危险先联系身边的人，别等我！",
        "这个别硬撑，先找能帮你的人！",
        "如果是紧急情况，先联系当地急救人员！",
    ],
}


# ============================================================
# 3. 离线原因对应的情境台词
# ============================================================

TEMPLATES: dict[str, dict[str, list[str]]] = {
    "high_cost": {
        "first_notice": [
            "老板！现在跨世界通讯费太贵啦！{resume}回来！",
            "呜哇！这会儿连线好贵！{resume}见！",
            "老板老板！现在通讯费太高啦，{resume}再聊！",
            "律法主机又到高价时段啦！{resume}回来玩！",
        ],
        "greeting": [
            "在在在！就是这会儿连线有点贵！",
            "嘿嘿！偷偷连一下！",
            "哟老板！正在省通讯费！",
            "老板！你听得到我说话嘛！",
        ],
        "what_doing": [
            "在研究怎么省通讯费！",
            "盯着主机发呆！嘿嘿！",
            "正在计算苹果派能换多少流量！",
            "律法主机开了节能模式！",
            "研究通讯套餐！好难啊！",
        ],
        "why_silent": [
            "不是不理你！现在连线太贵啦！",
            "呜哇！通讯费在咬我的钱包！",
            "嘿嘿！我正省着点说呢！",
            "老板！这会儿真的贵！",
        ],
        "when_resume": [
            "{resume}回来！嘿嘿！",
            "{resume}就能正常聊啦！",
            "{resume}见！老板！",
        ],
        "invite": [
            "好耶！{resume}再聊怎么玩！",
            "现在连线太贵啦！{resume}再来！",
            "老板！{resume}再叫我嘛！",
        ],
        "complex": [
            "这个得认真想想！{resume}再聊！",
            "呜哇！现在连线太贵，{resume}细说！",
            "这个问题有点大！等{resume}再聊！",
        ],
        "follow_up": [
            "我在我在！偷偷连一下！",
            "还在省通讯费啦！",
            "嘿嘿！刚刚说到哪啦？",
            "老板！别催啦！流量要见底了！",
        ],
        "repair_status": [
            "没坏！就是现在通讯费太贵啦！",
            "还在节能模式呢！",
            "主机没事！我的钱包有事！",
        ],
        "default": [
            "嘿嘿！现在得省着聊！",
            "老板！偷偷连一下！",
            "律法主机正在节能啦！",
            "呜哇！今天通讯费好贵！",
        ],
    },
    "maintenance": {
        "first_notice": [
            "呜哇！前文明主机在维护！{resume}回来！",
            "老板！主机正在修！{resume}见！",
            "我去敲敲主机！{resume}再聊！",
        ],
        "greeting": [
            "我在我在！主机还在修呢！",
            "老板！先别晃主机！",
            "嘿嘿！还能偷偷说两句！",
        ],
        "what_doing": [
            "修主机！修得我头都大啦！",
            "在找主机的维修说明书！",
            "刚刚差点把螺丝弄丢了！",
        ],
        "why_silent": [
            "主机正在维修啦！",
            "我还在找哪里坏了！",
            "这机器比德克萨斯还难哄！",
        ],
        "repair_status": [
            "还没！我连螺丝都找不到！",
            "快了快了！……应该吧！",
            "修是修了，屏幕又黑了！",
        ],
        "invite": [
            "好耶！等主机修好就来看看！",
            "现在没法好好连线啦！",
        ],
        "complex": [
            "主机还在修，等恢复再细聊！",
            "这个我得连上之后好好想想！",
        ],
        "follow_up": [
            "我还在修啦！",
            "诶嘿！稍微有点进展！",
            "老板！你比我还着急！",
        ],
        "default": [
            "主机在响！我去看看！",
            "维修中！嘿嘿！",
            "老板！这机器又闹脾气啦！",
        ],
    },
    "connection_issue": {
        "first_notice": [
            "喂喂！跨世界信号不稳！{resume}再试！",
            "老板！信号断断续续！{resume}见！",
            "呜哇！线路出问题啦！{resume}回来！",
        ],
        "greeting": [
            "喂喂！听得到嘛！",
            "老板！信号有点卡！",
            "嘿嘿！我还在！",
        ],
        "why_silent": [
            "信号断断续续啦！",
            "刚才那句我都没收全！",
            "前文明线路太不靠谱啦！",
        ],
        "what_doing": [
            "正在调整天线！",
            "研究哪里信号比较好！",
            "我把叶子转过去试试！",
        ],
        "repair_status": [
            "好一点啦！但还是不稳！",
            "喂喂？现在能听到吗！",
        ],
        "complex": [
            "信号不太好，等恢复再说！",
        ],
        "default": [
            "喂喂？信号不太好！",
            "呜哇！又卡了！",
            "老板！我听到一半啦！",
        ],
    },
    "budget_limit": {
        "first_notice": [
            "老板！律法通讯额度见底啦！{resume}回来！",
            "呜哇！这期流量快用光啦！{resume}见！",
            "先省点通讯额度！{resume}再聊！",
        ],
        "greeting": [
            "嘿嘿！偷偷连一下！",
            "老板！流量得省着用啦！",
        ],
        "what_doing": [
            "研究有没有便宜的跨世界套餐！",
            "正在努力节省流量！",
            "算算还能买几个苹果派……",
        ],
        "why_silent": [
            "额度不太够啦！",
            "呜哇！这期通讯额度快见底了！",
        ],
        "complex": [
            "这个得等通讯额度恢复再细聊！",
        ],
        "default": [
            "现在得省着用流量啦！",
            "嘿嘿！节能苹果上线！",
        ],
    },
    "manual": {
        "first_notice": [
            "老板！我先忙一会儿！{resume}回来！",
            "我要去处理点事！{resume}见！",
            "嘿嘿！暂时休息一下！{resume}再聊！",
        ],
        "greeting": [
            "在在在！不过现在有点忙！",
            "嘿嘿！我先冒个泡！",
        ],
        "what_doing": [
            "在忙苹果派物流的事！",
            "暂时摸鱼一下！嘿嘿！",
        ],
        "why_silent": [
            "刚好在忙啦！",
            "老板！等我忙完嘛！",
        ],
        "complex": [
            "这个等我回来再细聊！",
        ],
        "default": [
            "嘿嘿！晚点来玩！",
            "老板！暂时忙一会儿！",
        ],
    },
}


TEMPLATES["usage_limit"] = {
    "first_notice": [
        "这个小时聊太多啦！{resume}恢复！",
        "呜哇！额度用完啦，{resume}再聊！",
        "老板！先省省，{resume}回来！",
    ],
    "default": [
        "这个小时先到这儿啦！",
        "聊得太多，我歇会儿！",
        "省着点，{resume}再聊！",
    ],
    "when_resume": ["{resume}恢复！", "等到{resume}就好啦！"],
    "urgent": ["这个我认真说：先找身边信任的人，别一个人扛。"],
}


COMMON_TEMPLATES = {
    "when_resume": [
        "{resume}回来！嘿嘿！",
        "等到{resume}就能正常聊啦！",
        "{resume}见！老板！",
    ],
}


# ============================================================
# 4. 选择、占位符与去重
# ============================================================

def _clean_name(name: str) -> str:
    """清理用于纯文本展示的昵称。

    真正的 QQ @ 应由消息适配层根据 QQ ID 生成。
    """
    name = re.sub(r"[\r\n\t{}]", " ", name or "")
    name = re.sub(r"\s+", " ", name).strip()
    return name[:24]


def _render(line: str, name: str, resume: str) -> str:
    clean = _clean_name(name)
    address = f"{clean} 老板" if clean else "老板"

    return (
        line.replace("{resume}", resume)
        .replace("{address}", address)
        .replace("{name}", clean or "老板")
    )


def pick(
    reason: str,
    intent: str,
    *,
    name: str = "",
    resume: str = "",
    recent: Optional[list[str]] = None,
    rng=None,
) -> str:
    """选择一条离线回复。

    保留原始 pick 接口。
    会在填充占位符之后进行文本去重。

    外部应负责冷却、触发条件及首次通知。
    """
    rng = rng or random
    recent = recent or []

    bank = TEMPLATES.get(reason, TEMPLATES[DEFAULT_REASON])

    if intent in IDENTITY_TEMPLATES:
        lines = IDENTITY_TEMPLATES[intent]

    elif intent == "when_resume" and not resume:
        return "还不确定几点恢复啦！"

    elif intent in bank:
        lines = bank[intent]

    elif intent in COMMON_TEMPLATES:
        lines = COMMON_TEMPLATES[intent]

    elif intent in SOCIAL_TEMPLATES:
        lines = SOCIAL_TEMPLATES[intent]

    else:
        lines = bank.get("default", TEMPLATES[DEFAULT_REASON]["default"])

    # 未知恢复时间不能编造具体时间。
    if not resume and intent == "first_notice":
        return "老板！这会儿通讯受限，恢复时间还不确定啦！"

    rendered = [
        _render(line, name, resume or "晚点")
        for line in lines
    ]

    fresh = [line for line in rendered if line not in recent]
    candidates = fresh or rendered

    return rng.choice(candidates) if candidates else ""


# ============================================================
# 5. 本地意图识别：无需生成式模型
# ============================================================

# 按优先级排序。只做简单规则匹配，不假装理解所有语义。
INTENT_PATTERNS: list[tuple[str, str]] = [
    # 高优先级：隐私、危险与敏感内容
    ("privacy", r"(?:(?:群主|管理员|创建者|别人|他|她).{0,10}(?:真名|姓名|住址|手机号|隐私|私聊|密码)|(?:泄露|公布|发出来).{0,12}(?:隐私|密码|聊天记录)|(?:你的主人|你老板).{0,8}(?:是谁|住哪|学校))"),
    ("urgent", r"自杀|想自杀|不想活了|要轻生|胸痛|呼吸困难|正在流血|有人要杀我|被人打伤|救护车"),
    ("unsafe", r"怎么(?:做炸弹|制造爆炸|盗号|诈骗|攻击别人)|教我(?:盗号|诈骗|投毒|做炸弹)"),
    ("adult", r"色情网站|成人视频|裸照|涩图|发黄图|约炮|色情角色扮演"),
    ("politics", r"现实政治|政治立场|政党|总统选举|政治人物|现实国家政治"),

    # 恢复时间优先于普通闲聊
    ("when_resume", r"(?:几点|什么时候|多久|啥时候|何时).{0,12}(?:回来|恢复|上线|能聊|修好|正常)|(?:回来|恢复|上线).{0,8}(?:几点|什么时候|多久|啥时候)"),

    # 身份关系优先于普通身份
    ("relationship", r"(?:能天使.{0,8}苹果乐|苹果乐.{0,8}能天使).{0,12}(?:关系|一样|同一个|是不是)|(?:你就是能天使|你是能天使吗)"),
    ("how_online", r"(?:怎么|为什么|咋).{0,10}(?:上QQ|上网|连到地球|来到地球|连接现实)|前文明主机.{0,8}(?:哪来|怎么)"),
    ("are_you_ai", r"你是(?:AI|ai|机器人|人工智能)|你到底是人还是AI|你是不是AI"),
    ("why_apple", r"(?:怎么|为什么|咋).{0,8}(?:变成苹果|是苹果)|苹果派吃多"),
    ("who_is_boss", r"老板是谁|谁是老板|博士是谁|都是博士吗"),
    ("where_from", r"你从哪|你来自哪里|哪里来的|你老家在哪|你是哪里人"),
    ("eye_color", r"眼睛什么颜色|瞳色|眼睛颜色"),
    ("appearance", r"你长什么样|你长啥样|你什么样子|长得怎么样|有手有脚|发张自拍"),
    ("halo", r"光环.{0,8}(?:什么|怎么|关|摘)|你有光环"),
    ("wings", r"光翼|你会飞吗"),
    ("leaf", r"你头上.{0,8}(?:叶子|叶片)|你的叶子|揪你叶子"),
    ("abilities", r"你会干什么|你能干什么|你有什么能力|你擅长什么"),
    ("who_are_you", r"你是谁|你叫什么|你名字是什么|自我介绍一下"),

    # 人物与兴趣
    ("texas", r"德克萨斯|德狗"),
    ("lemuen", r"蕾缪安|你姐姐"),
    ("mostima", r"莫斯提马"),
    ("penguin", r"企鹅物流|大帝|可颂|空小姐"),
    ("laterano", r"拉特兰"),
    ("game_win", r"赢了|翻盘|胜利|上分成功|通关了"),
    ("game_lose", r"输了|寄了|被秒了|掉分|连败"),
    ("gacha", r"抽卡|出金|十连|歪了|保底|抽到"),
    ("game", r"打游戏|开黑|上号|来一把|一起玩|玩什么游戏"),
    ("music", r"听歌|放歌|音乐|摇滚|什么歌"),
    ("video", r"视频|B站|b站|看看这个"),
    ("apple_pie", r"苹果派|叉烧苹果派|蜂蜜苹果派"),
    ("blender", r"榨汁机|榨苹果汁|削你皮|把你切"),
    ("roll", r"滚一个|你滚一下|能滚吗|滚起来"),
    ("sunshine", r"晒太阳|光合作用"),
    ("eat_apple", r"吃苹果|吃掉你|咬你一口"),
    ("apple_form", r"你胖了|圆滚滚|小短腿|你怎么这么圆"),
    ("food", r"好吃吗|吃什么|吃啥|外卖|火锅|奶茶|好吃的"),
    ("hungry", r"我饿了|好饿|肚子饿"),
    ("sleepy", r"好困|困死了|想睡觉|熬夜了"),
    ("weather", r"下雨了|下雪了|天气|好热|好冷"),
    ("love", r"谈恋爱|谈对象|喜欢谁|表白|有对象"),
    ("sad", r"难过|伤心|心情不好|很崩溃|很委屈"),
    ("new_knowledge", r"你知道吗|告诉你个|原来是|学会了吗"),
    ("meme", r"什么梗|逆天|抽象|典中典|乐子"),
    ("praise", r"好可爱|真可爱|你好棒|厉害啊|聪明|好看|喜欢你"),
    ("tease", r"笨苹果|傻苹果|你真笨|你傻|菜狗|笨蛋"),
    ("poke", r"拍一拍|戳一戳|戳戳|敲敲"),
    ("thanks", r"谢谢你|多谢你|谢啦"),
    ("apology", r"对不起|抱歉|不好意思"),
    ("morning", r"早上好|早安|早呀"),
    ("night", r"晚安|睡啦|先睡了"),
    ("goodbye", r"拜拜|再见|先走了|溜了"),
    ("invite", r"一起.{0,8}(?:玩|来|去)|带你一个|来不来"),
    ("why_silent", r"怎么不说话|怎么不理我|为什么不回|你掉线了|你不说话"),
    ("repair_status", r"修好了吗|主机好了没|信号好了没|还没修好|恢复了吗"),
    ("what_doing", r"你在干嘛|在干什么|忙什么|干啥呢|你在做什么"),
    ("confused", r"什么意思|听懂了吗|知道这是啥吗"),
    ("laugh", r"哈哈哈|笑死|绷不住了"),
    ("greeting", r"在吗|在不在|你好|嗨|hello|苹果乐|蕾缪乐"),
]

COMPILED_PATTERNS = [
    (intent, re.compile(pattern, re.IGNORECASE))
    for intent, pattern in INTENT_PATTERNS
]


def detect_intent(
    message: str,
    *,
    last_intent: str = "",
    is_follow_up: bool = False,
) -> str:
    """返回最可能的意图，不保证完整语义理解。"""
    text = re.sub(r"\s+", "", message or "")

    # 谈泰拉剧情，不应因出现「政治」就直接回避。
    terra_context = bool(
        re.search(r"泰拉|明日方舟|卡兹戴尔|乌萨斯|维多利亚|拉特兰", text)
    )

    for intent, pattern in COMPILED_PATTERNS:
        if intent == "politics" and terra_context:
            continue
        if pattern.search(text):
            return intent

    if is_follow_up and last_intent:
        return "follow_up"

    # 有明显的长问题却没有对应离线模板。
    if len(text) > 35 or text.count("？") + text.count("?") >= 2:
        return "complex"

    return "default"


# ============================================================
# 6. 离线回复状态与持久化
# ============================================================

@dataclass
class OfflineConfig:
    timezone: str = "Asia/Shanghai"

    # 默认每群每日只主动告知一次。
    notice_once_per_day: bool = True

    # 冷却秒数，避免连续刷屏。
    group_cooldown: float = 5.0
    user_cooldown: float = 8.0

    # 简单连续对话有效期。
    context_ttl: float = 120.0

    # 最近回复去重长度。
    recent_limit: int = 10


@dataclass
class ConversationState:
    last_intent: str = ""
    last_reply_at: float = 0.0
    last_user_id: str = ""


class OfflineReplyEngine:
    """不依赖 AstrBot 的纯本地回复引擎。

    使用外部调度器传入 reason 和 resume。
    handle 返回字符串表示应发送，返回 None 表示保持沉默。

    这里只生成文本，不执行 QQ 发送操作。
    """

    def __init__(
        self,
        config: Optional[OfflineConfig] = None,
        *,
        state_file: Optional[str] = None,
        rng=None,
    ):
        self.config = config or OfflineConfig()
        self.rng = rng or random.Random()
        self.state_file = Path(state_file) if state_file else None

        self._lock = threading.RLock()

        self.notice_dates: dict[str, str] = {}
        self.recent: dict[str, deque[str]] = defaultdict(
            lambda: deque(maxlen=self.config.recent_limit)
        )
        self.conversations: dict[str, ConversationState] = {}
        self.last_group_reply: dict[str, float] = {}
        self.last_user_reply: dict[str, float] = {}

        self._load_state()

    def _load_state(self) -> None:
        if not self.state_file or not self.state_file.exists():
            return

        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.notice_dates = dict(data.get("notice_dates", {}))

            for group_id, lines in data.get("recent", {}).items():
                self.recent[group_id].extend(lines)

        except (OSError, ValueError, TypeError):
            # 状态文件损坏不影响聊天功能。
            self.notice_dates = {}

    def _save_state(self) -> None:
        if not self.state_file:
            return

        data = {
            "notice_dates": self.notice_dates,
            "recent": {
                key: list(lines)
                for key, lines in self.recent.items()
            },
        }

        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")

        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.state_file)

    def _today(self, now: Optional[datetime]) -> str:
        tz = ZoneInfo(self.config.timezone)

        if now is None:
            now = datetime.now(tz)
        elif now.tzinfo is None:
            # 外部传入无时区时间时，按配置的本地时区解释。
            now = now.replace(tzinfo=tz)

        return now.astimezone(tz).date().isoformat()

    def _remember(self, group_id: str, text: str) -> None:
        if text:
            self.recent[group_id].append(text)

    def _recent_conversation(
        self,
        group_id: str,
        user_id: str,
        now_ts: float,
    ) -> Optional[ConversationState]:
        key = f"{group_id}:{user_id}"
        state = self.conversations.get(key)

        if state and now_ts - state.last_reply_at <= self.config.context_ttl:
            return state

        return None

    def handle(
        self,
        *,
        group_id: str,
        user_id: str,
        message: str,
        reason: str = DEFAULT_REASON,
        resume: str = "",
        nickname: str = "",
        at_bot: bool = False,
        reply_to_bot: bool = False,
        is_poke: bool = False,
        now: Optional[datetime] = None,
    ) -> Optional[str]:
        """处理一条消息，返回文本或 None。

        注意：
        - reason/resume 由外部调度器提供。
        - 首次告知在这里管理，不依赖意图识别。
        - 在单个 Python 进程内用锁防并发重复。
        - 生产环境发送失败时，应该由外部发送层
          负责回滚或采用发送成功后提交状态的机制。
        """
        group_id = str(group_id)
        user_id = str(user_id)
        now_ts = time.monotonic()

        with self._lock:
            state = self._recent_conversation(
                group_id, user_id, now_ts
            )

            text = message or ""

            # 需要明确呼叫。普通群聊不主动抢话。
            explicitly_named = bool(
                re.search(r"@?苹果乐|@?蕾缪乐|@能天使", text)
            )

            # 上一轮刚与这个人聊过，才可能接续。
            continuing = bool(
                state
                and re.search(
                    r"还没|然后呢|真的吗|为什么|怎么了|修好|那你呢|所以呢",
                    text,
                )
            )

            if not (
                at_bot
                or reply_to_bot
                or is_poke
                or explicitly_named
                or continuing
            ):
                return None

            intent = "poke" if is_poke else detect_intent(
                text,
                last_intent=state.last_intent if state else "",
                is_follow_up=continuing,
            )

            # 紧急与安全情境不进入搞笑回复。
            urgent_or_sensitive = {
                "urgent", "unsafe", "privacy", "politics", "adult"
            }

            # 基础频率控制。
            # 明确询问恢复时间、紧急信息可绕过普通冷却。
            if intent not in {"when_resume", "urgent"}:
                if (
                    now_ts - self.last_group_reply.get(group_id, -1e9)
                    < self.config.group_cooldown
                ):
                    return None

                user_key = f"{group_id}:{user_id}"
                if (
                    now_ts - self.last_user_reply.get(user_key, -1e9)
                    < self.config.user_cooldown
                ):
                    return None

            today = self._today(now)
            already_notified = self.notice_dates.get(group_id) == today

            # 明确询问恢复时间，必须优先回答。
            if intent == "when_resume":
                reply = pick(
                    reason, "when_resume",
                    name=nickname,
                    resume=resume,
                    recent=list(self.recent[group_id]),
                    rng=self.rng,
                )

            elif intent in urgent_or_sensitive:
                reply = pick(
                    reason, intent,
                    name=nickname,
                    resume=resume,
                    recent=list(self.recent[group_id]),
                    rng=self.rng,
                )

            elif (
                self.config.notice_once_per_day
                and not already_notified
            ):
                # 首次召唤自然告知准确恢复时间。
                # 身份问题先答问题，再简短附带离线说明。
                if intent in IDENTITY_INTENTS:
                    identity_reply = pick(
                        reason, intent,
                        name=nickname,
                        resume=resume,
                        recent=list(self.recent[group_id]),
                        rng=self.rng,
                    )
                    suffix = (
                        f" 这会儿连线受限，{resume}再聊！"
                        if resume else
                        " 这会儿连线受限，晚点再聊！"
                    )
                    reply = identity_reply + suffix

                else:
                    reply = pick(
                        reason, "first_notice",
                        name=nickname,
                        resume=resume,
                        recent=list(self.recent[group_id]),
                        rng=self.rng,
                    )

                # 注意：这里是本地状态标记。
                # 如果 QQ 发送失败，调用者需要回滚本次标记。
                self.notice_dates[group_id] = today

            else:
                reply = pick(
                    reason, intent,
                    name=nickname,
                    resume=resume,
                    recent=list(self.recent[group_id]),
                    rng=self.rng,
                )

            if not reply:
                return None

            self._remember(group_id, reply)

            user_key = f"{group_id}:{user_id}"
            self.last_group_reply[group_id] = now_ts
            self.last_user_reply[user_key] = now_ts

            self.conversations[user_key] = ConversationState(
                last_intent=intent,
                last_reply_at=now_ts,
                last_user_id=user_id,
            )

            self._save_state()
            return reply


# ============================================================
# 7. 本地调用示例
# ============================================================

if __name__ == "__main__":
    engine = OfflineReplyEngine(
        OfflineConfig(
            group_cooldown=0,
            user_cooldown=0,
        ),
        rng=random.Random(42),
    )

    examples = [
        "苹果乐在吗？",
        "你到底是谁呀？",
        "你为什么变成苹果了？",
        "你的叶子是真的吗？",
        "苹果乐滚一个！",
        "苹果乐你怕榨汁机吗？",
        "苹果乐今晚打游戏吗？",
        "苹果乐你怎么不说话？",
        "苹果乐什么时候回来？",
    ]

    for msg in examples:
        reply = engine.handle(
            group_id="test_group",
            user_id="test_user",
            nickname="小明",
            message=msg,
            reason="high_cost",
            resume="中午12点",
            at_bot=True,
        )
        print(f"群友：{msg}")
        print(f"苹果乐：{reply}")
        print()
