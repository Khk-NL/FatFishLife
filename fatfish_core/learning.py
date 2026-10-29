"""Learn recurring phrases from recent group messages without training a model.

Cheap by design: local n-gram counting over already stored events, no extra
model calls. Results are stored as public ``style`` memories so the normal
context builder can inject them.
"""

from __future__ import annotations

import re
from collections import Counter

# 单字停用词（保留给调用方判断"这个字是否算实词"）。
STOP = set(
    "的了是我你他她它们这那什么怎么就是不是可以一个没有现在今天明天昨天"
    "哈嗯哦啊吧呢吗呀啦嘛诶嘿好这个那个真的然后还是但是所以因为如果已经"
    "我们你们他们大家知道觉得应该可能这样那样一下一直还有自己"
)

# 口语高频虚词/套话（按词而不是按字匹配）。extract_terms 产出的 token 都是
# 2–4 字的片段，用单字集合去比对永远不命中 —— 真实群聊里"这个""什么"这类
# 词会稳定排在最前面，把真正的梗挤掉。所以另立一张词表。
STOP_TERMS = {
    "这个", "那个", "这些", "那些", "什么", "怎么", "为什么", "不是", "就是", "也是", "都是",
    "一个", "一下", "一直", "一起", "一般", "没有", "没事", "没什么", "可以", "可能", "应该",
    "真的", "然后", "还是", "但是", "所以", "因为", "如果", "已经", "现在", "今天", "明天",
    "昨天", "我们", "你们", "他们", "她们", "大家", "自己", "知道", "觉得", "感觉", "时候",
    "东西", "事情", "问题", "地方", "样子", "有点", "有些", "一点", "其实", "反正", "只是",
    "不过", "而且", "或者", "还有", "出来", "起来", "过来", "下来", "上去", "出去", "进去",
    "回来", "看到", "听说", "以为", "似乎", "好像", "绝对", "完全", "真的", "一样", "这么",
    "那么", "多少", "怎么样", "是不是", "有没有", "能不能", "要不要", "会不会", "对不起",
    "不好", "不要", "不用", "不行", "不会", "不能", "不太", "好像", "好像",
}
# 由高频虚词组成的片段（"我是""是我""是不"）不是梗：只要整段都由这些字
# 拼成，就丢掉。实词里出现一两个这类字不受影响（"苹果派""问薪无愧"）。
COMMON_CHARS = set("的了是我你他她它们这那什么怎么就是不是可以一个没有好嗯啊吧呢吗呀啦嘛")

MIN_COUNT = 3
MAX_TERMS = 20


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def extract_terms(texts, *, min_count: int = MIN_COUNT, max_terms: int = MAX_TERMS) -> list[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        clean = re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]", "", text or "")
        for size in (2, 3, 4):
            for index in range(len(clean) - size + 1):
                token = clean[index:index + size]
                if (all(_is_cjk(char) for char in token) and token not in STOP_TERMS
                        and not all(char in COMMON_CHARS for char in token)
                        and token[0] not in COMMON_CHARS and token[-1] not in COMMON_CHARS):
                    counter[token] += 1
    ranked = [term for term, count in counter.most_common(max_terms * 4) if count >= min_count]
    keep: list[str] = []
    for term in ranked:
        if any(term != other and term in other for other in ranked if len(other) > len(term)):
            continue
        keep.append(term)
        if len(keep) >= max_terms:
            break
    return keep


def save_style(store, terms: list[str], *, kind: str = "style", label: str = "群友最近常这样说",
               conversation: tuple[str, str] | None = None) -> int:
    """把提炼出的说法写进共享记忆，独立于人设。"""
    phrases = list(dict.fromkeys(str(term).strip() for term in terms if str(term).strip()))
    saved = 0
    for phrase in phrases[:MAX_TERMS]:
        if len(phrase) > 30:
            continue
        store.remember(f"{label}：{phrase}", platform=conversation[0] if conversation else "system",
                       session=conversation[1] if conversation else None,
                       scope="public", kind=kind, actor="bot")
        saved += 1
    return saved


def save_bili_style(store, terms: list[str]) -> int:
    """B 站评论区学到的说法，单独一类，方便排查来源。"""
    return save_style(store, terms, kind="bili_style", label="评论区最近常这样说")
