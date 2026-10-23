# meme_manager 表情概率递增补丁

社区插件 `meme_manager` 的 `generation.emotion.probability` 是固定概率，每轮独立掷骰。这里改成随连续未命中递增：

- 基础概率取配置里的 `probability`（当前 35）
- 每连续一轮没发成表情，概率 +10
- 上限 90
- 成功进入发送流程后归零

实际曲线：35 → 45 → 55 → 65 → 75 → 85 → 90 → 90…

## 改动位置

- `data/plugins/meme_manager/main.py`：在 `self.emotions_probability` 后加 `self._meme_miss` 计数器
- `data/plugins/meme_manager/mixins/event_handlers.py`：新增 `_meme_probability_hit(event)`，把三处 `probability_hit(self.emotions_probability)` 换成它

## 升级注意

这是对社区插件源码的本地补丁，`meme_manager` 升级会用新文件覆盖，需要重新应用。升级后先确认两处改动还在，再重启 AstrBot。

想调力度就改 `_meme_probability_hit` 里的步长（10）和上限（90），基础概率仍在插件配置里。
