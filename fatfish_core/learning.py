"""Learn recurring phrases from recent group messages without training a model.

Cheap by design: local n-gram counting over already stored events, no extra
model calls. Results are stored as public ``style`` memories so the normal
context builder can inject them.
"""

from __future__ import annotations

import re
from collections import Counter

STOP = set(
    "的了是我你他她它们这那什么怎么就是不是可以一个没有现在今天明天昨天"
    "哈嗯哦啊吧呢吗呀啦嘛诶嘿好这个那个真的然后还是但是所以因为如果已经"
    "我们你们他们大家知道觉得应该可能这样那样一下一直还有自己"
)
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
                if all(_is_cjk(char) for char in token) and token not in STOP:
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


def save_style(store, terms: list[str]) -> int:
    if not terms:
        return 0
    content = "群友最近常这样说：" + "、".join(terms)
    store.remember(content, platform="system", scope="public", kind="style", actor="bot")
    return len(terms)
