"""记忆准入：先判断消息的来源和性质，再决定记什么、怎么记。

三类来源不能一视同仁：
- 事实声明（「黎曼猜想已经被证明啦」）→ 只记「某人说过」，不记成事实
- 自我声明（「以后叫我小明」）→ 称呼偏好，可信度高
- 单次玩梗（「啊噗噜派！哈哈哈哈」）→ 不单独记，重复出现才算群文化

纯规则实现，不调模型。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 称呼/自我声明：第一人称 + 关系词
SELF_DECLARATION = re.compile(
    r"(以后|今后|就)?(叫我|喊我|称呼我)"
    r"|我(的名字)?叫[^\s，。！？]{1,8}"
    r"|我是[^\s，。！？]{1,10}(本人)?"
    r"|记住我"
    r"|别叫我"
    r"|(可以|请)叫我"
)

# 传述/断言：转述别人的说法
CLAIM = re.compile(
    r"已经(被)?(证明|确认|公布|上线|实装|官宣|证出)"
    r"|据说|听说|网传|有人(说|爆料)"
    r"|其实(是|就)|真相(是|就是)"
    r"|(官方|公告|泄露|爆料)(说|称|表示)"
    r"|证实|辟谣"
)

# 明显的信息源不可靠标记
UNRELIABLE = re.compile(r"(开玩笑|骗你的|假的|谣传|段子|昨晚梦到|我编的)")

# 玩梗/感叹：短、无信息量、情绪化
BANTER = re.compile(r"[！!]{2,}|哈哈|嘿嘿|笑死|草{2,}|绷不住|乐死|啊啊啊")
URL = re.compile(r"https?://\S+")
MENTION = re.compile(r"@\S+|\[CQ:at,[^\]]+\]")


@dataclass
class Admission:
    """一条消息的准入判定。"""

    kind: str
    """preference / claim / banter / chat"""

    content: str
    """格式化后真正要写入的内容。"""

    confident: bool
    """是否可以直接生效（True）还是只能作为候选（False）。"""

    reason: str = ""
    meta: dict = field(default_factory=dict)


def _clean(text: str) -> str:
    text = MENTION.sub("", str(text or ""))
    text = URL.sub("", text)
    return " ".join(text.split()).strip()


def classify(text: str, *, speaker: str = "", group: str = "") -> Admission | None:
    """判定一条消息该不该记、怎么记。返回 None 表示不值得记。"""
    body = _clean(text)
    if len(body) < 2:
        return None

    # 自称不可靠、明显是玩笑，直接按玩梗处理，不进记忆
    if UNRELIABLE.search(body):
        return Admission(
            kind="banter",
            content=body,
            confident=False,
            reason="自称不可靠的说法",
            meta={"speaker": speaker, "group": group},
        )

    # 传输/断言优先判：即使含感叹号也先按 claim 处理
    if CLAIM.search(body):
        who = speaker or "某群友"
        return Admission(
            kind="claim",
            content=f"{who}说过：{body}"[:300],
            confident=False,
            reason="转述，只能记为「某人说过」",
            meta={"speaker": speaker, "group": group},
        )

    if SELF_DECLARATION.search(body):
        who = speaker or "某群友"
        return Admission(
            kind="preference",
            content=f"{who}表示：{body}"[:300],
            confident=True,
            reason="本人声明，可信",
            meta={"speaker": speaker, "group": group},
        )

    if len(body) < 10 and BANTER.search(body):
        return Admission(
            kind="banter",
            content=body,
            confident=False,
            reason="单次玩梗，不单独记",
            meta={"speaker": speaker, "group": group},
        )

    if len(body) < 4:
        return None

    return Admission(
        kind="chat",
        content=body[:300],
        confident=False,
        reason="普通聊天，只做短期上下文",
        meta={"speaker": speaker, "group": group},
    )


# 注入时按来源分段的顺序和标题
SECTION_ORDER = [
    ("preference", "确定的事"),
    ("claim", "群友说过"),
    ("culture", "群里的梗"),
]
SECTION_TITLES = dict(SECTION_ORDER)
