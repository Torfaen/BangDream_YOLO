# REQ-20260503-m6-greenbar-state-machine

## 背景/目标

实机验证发现，上一版 `green_bar first` 仍然偏向逐帧局部反应：判定线附近看到 `green_bar` 就刷新，附近出现短暂断检时容易把长按拆成 `down -> up -> down`。绿色 slide 的正确行为应该是链路状态：底部 `green_bar` 进入判定线后按住并持续跟随，直到本条绿带上的下一个判定节点撞上判定线才结束；结束节点只能是 `green_note` 或 `flick`，`green_bar` 本身只是光带，不作为释放终点。

## 范围

本次做：

- 将 m6 绿色逻辑重构为 `GreenHoldState` 状态机，而不是由单帧 `green_bar` 直接决定释放。
- `green_bar` 到达判定线附近且附近没有 active green hold 时，创建一个 green hold 并 `down` 到 `green_bar` 中心。
- active green hold 期间，只跟随当前底部 `green_bar` 中心做 `move`；同一 track 优先，短暂换 track id 时用近距离匹配接续。
- active green hold 不因为 `green_bar` 到线而释放；`green_note` 只作为绿色普通终点释放信号。
- `green_note` 作为终点前必须先通过统一准入判断：起点回声、以及本帧仍被底部 `green_bar` 续住的同位置重复识别，都不能释放当前 hold。
- active green hold 的结束条件改为：
  - 附近的 `green_note` 到达判定线：`up`。
  - 附近的 `flick` 到达判定线：不再重新 `down`，复用 held pointer 执行 flick move/up。
  - 没有任何可见底部 `green_bar` 超过 `green_release_grace`：作为漏检兜底释放。
- 多条绿色链路同时存在时，每条链路占用一个 pointer；不会用一条 pointer 吃掉相邻链路。

本次不做：

- 不引入颜色阈值或图像分割识别绿条。
- 不做完整谱面级链路拓扑推断；仍只使用 m5 tracker 当前帧 track、ETA、lane 和连续坐标。
- 不把 `green_bar` 当成终点；哪怕下一个 `green_bar` 已到判定线，也只继续跟随或接续。

## 技术细节

新增绿色状态结构：

```text
GreenHoldState:
  pointer_id: int
  owner_track_id: int      # pointer_pool 中用于释放的初始 track
  follow_track_id: int     # 当前底部 green_bar track
  started_at: float
  last_seen: float
  has_followed_green_bar: bool  # 创建 hold 后是否已经接上过后续 green_bar
  ignored_terminal_track_ids: set[int]  # 创建 hold 同帧重叠的 green_note，视为起点回声
```

判定线附近可跟随 `green_bar`：

```text
track.note_type == "green_bar"
track.missed_frames == 0
green_bar_min_track_y <= track.latest.track_y <= green_bar_max_track_y
```

默认参数：

```text
green_bar_min_track_y = 0.82
green_bar_max_track_y = 1.10
green_slot_match_lanes = 0.75
green_bar_follow_lanes = 1.35
green_terminal_arm_seconds = 0.080
green_start_echo_track_y = 0.080
green_release_grace = 0.350
```

调度流程：

1. 每帧先释放已到期的普通 tap/flick pending 动作。
2. 筛出当前帧真实可见、判定线附近的 `green_bar`。
3. 对已有 green hold，优先用相同 `follow_track_id` 的 `green_bar` 刷新位置；否则用近距离 `green_bar` 接续，防止 tracker 换 id 后断按；创建 hold 之后第一次接上 `green_bar` 时，将该 hold 标记为已经进入 green_bar 跟随段。
4. 创建 green hold 时，记录同帧、同位置附近的 `green_note track_id` 为起点回声；这些 track 后续即使 ready，也不能释放该 hold。
5. active green hold 经过 `green_terminal_arm_seconds` 后，才允许响应 `green_note` 终点；响应前先进入统一准入判断。
6. 若 ready 的 `flick` 靠近 active green hold，立即复用 held pointer 进入 flick pending，后续按 `flick_duration` move/up。
7. 若 ready 的 `green_note` 靠近 active green hold、已过 arm 时间、通过终点准入且到达判定线，则释放该 hold。
8. 剩余未使用、且附近没有 active hold 的 `green_bar`，创建新的 green hold。
9. active green hold 若超过 `green_release_grace` 没有看到可跟随底部 `green_bar`，兜底释放。

`green_note` 终点准入：

```text
如果 track_id 属于 state.ignored_terminal_track_ids：
  忽略，视为创建 hold 同帧的起点回声。

起点回声只记录与起点 green_bar 的真实轨道位置接近的 green_note：
  abs(note.track_x - green_bar.track_x) <= green_slot_match_lanes / lane_count
  abs(note.track_y - green_bar.track_y) <= green_start_echo_track_y
  不使用 _track_touch 投影后的触控点距离，避免把同轨道远处后续 green_note 误记为起点回声。

如果 state.has_followed_green_bar 仍为 False：
  忽略并刷新 last_seen，视为刚按下到第一段 green_bar 接上前的 green_note 过渡视觉。

如果当前 state.pointer_id 本帧已经被 green_bar 跟随刷新，
且该 green_note 映射到触控判定线后的点距离当前 held pointer 很近：
  若该 green_note 没有 ETA 或历史不足 2 帧，则忽略，视为当前底部 green_bar/green_note 重复识别。

否则：
  允许继续检查 ready 条件并释放。
```

## 验收标准

- 底部 `green_bar` 到线后只产生一次 `down`，连续可见时不会反复 `up/down`。
- 底部 `green_bar` 横向移动时，held pointer 跟随中心 `move`。
- 短暂换 track id 的同一底部 `green_bar` 不会重新 `down`。
- 同位置/附近的 `green_bar` 不会释放 active green hold。
- 创建 hold 同帧与 `green_bar` 重叠的 `green_note` 不会在后续帧把 hold 释放。
- 与起点 `green_bar` 同轨道但 `track_y` 相距较远的后续 `green_note` 不会被记为起点回声。
- 刚按下后、第一段 `green_bar` 接上前，判定线附近持续出现的 `green_note` 不会释放 active green hold。
- active green hold 本帧仍跟随到底部 `green_bar` 时，同位置/近距离的新 `green_note track_id` 不会释放该 hold。
- 已接上过 `green_bar` 后，连续追踪且 ETA ready 的真正 `green_note` 终点可以释放 active green hold。
- active green hold 存在时，`green_note` 到线会释放当前 pointer。
- active green hold 存在时，终点 `flick` 到线会复用当前 pointer 划出，不产生新的 `down`。
- 两条相邻/并发 green bar 能分别持有 pointer。
- 单元测试和全量 `unittest discover` 通过。

## 风险与回滚

风险：

- 如果终点 `green_note` 漏检，只能依赖 `green_release_grace` 兜底，可能稍晚松手。
- 如果终点 `flick` 漏检，仍会退化为兜底释放，无法划出。

回滚：

- 运行时可调大/调小 `--green-slot-match-lanes`、`--green-bar-follow-lanes`、`--green-release-grace`。
- 如状态机效果变差，可临时回退上一版本实现，或先关闭真实触控只保留 dry-run 日志调试。
