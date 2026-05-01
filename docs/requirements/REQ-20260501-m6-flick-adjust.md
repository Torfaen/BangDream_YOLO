# REQ-20260501-m6-flick-adjust

## 背景/目标

m6 真实触控已验证普通 `tap` 可以命中，`flick` 能被 YOLO 识别并进入 policy，但实测表现为没有被游戏判定为有效 flick。当前实现使用 touch 坐标 `y - 45`，在 `touch.rotation: clockwise` 下方向不符合游戏画面直觉，且距离偏大。

目标：把 flick 调整为“比普通键略早进入 ETA 触发，并执行一个持续 50ms 的固定方向滑动”。

## 范围

本次做：

- flick 仍使用 m5 的 ETA 触发路线，不新增 hitbox。
- flick 进入触发窗口后先 `down`，随后立即开始跨帧 `move`，滑动过程持续 `flick_duration`，最后 `up`。
- 默认滑动方向改为游戏画面向下。
- 默认滑动距离改为 100 touch 像素。
- flick 默认提前 `flick_lead_seconds` 开始，保留 CLI 调参项。

本次不做：

- 不识别 flick 方向。
- 不按谱面或视觉方向动态调整 flick。
- 不改 tap / skill / green_note 的基本策略。
- 不引入复杂手势曲线。

## 技术细节

当前 `data/calibration.yml` 使用：

```text
touch.rotation: clockwise
touch_x = capture_height - capture_y
touch_y = capture_x
```

游戏画面向下表示 capture `y` 增大，因此对应到 touch 坐标为：

```text
touch_x 减小
touch_y 不变
```

因此 flick 终点从：

```text
end_x = start_x
end_y = start_y - flick_distance
```

调整为：

```text
end_x = max(0, start_x - flick_distance)
end_y = start_y
```

默认参数：

- `flick_distance = 100`
- `flick_duration = 0.050`
- `flick_lead_seconds = 0.020`

触发判断：

```text
tap_delta = eta_seconds - latency_offset
flick_delta = eta_seconds - latency_offset - flick_lead_seconds
```

flick 的触发窗口仍复用：

```text
-trigger_window_after <= flick_delta <= trigger_window_before
```

## 验收标准

- 单元测试覆盖 flick 终点为 `x - 100, y`。
- 可通过 CLI 将 `flick_lead_seconds` 调大，让 flick 比普通 tap 更早进入触发窗口。
- 单元测试覆盖 flick 在持续时间中途产生渐进 `move`，到达持续时间后 `up`。
- `policy_preview --help` 能看到 `--flick-lead-seconds`。
- 实测普通 tap 不回退。
- 实测 flick 触点能在判定线附近执行短小滑动。

## 风险与回滚

风险：

- 100 像素可能偏长或偏短，需要按实测表现微调。
- `flick_lead_seconds=0.020` 可能偏早或偏晚，需要按 MISS/GOOD 表现微调。
- 如果未来更换 `touch.rotation`，游戏画面向下对应的 touch delta 需要重新确认。

回滚：

- 将 `flick_distance` 调回旧值或通过 CLI 覆盖。
- 将 `flick_lead_seconds` 设为 `0`，保持与 tap 相同触发时间。
