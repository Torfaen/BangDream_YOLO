# REQ-20260429-m5-tracker

## 背景/目标

本阶段对应主计划 `m5_tracker`。m4 已经产出第一版 4 类 YOLO 模型，并提供实时检测预览窗口；但当前输出仍只是单帧检测框，不能直接用于后续自动触控调度。

目标是把 YOLO 检测框转换为可跨帧追踪的 note 实体：

- 为每个检测框计算 `lane`、中心点、类别、置信度和轨道归一化位置。
- 按 lane 和类别做跨帧关联，生成稳定的 `track_id`。
- 根据最近若干帧位置估算下落速度 `v_y` 和到判定线的 `ETA`。
- 允许短暂丢检续命，减少模型偶发漏检对后续 m6 调度的影响。

## 范围

本次做：

- 新增 `src/bangdream_yolo/detection/postprocess.py`，负责把 Ultralytics YOLO result 转为项目内 `NoteDetection`。
- 新增 `src/bangdream_yolo/tracker/state.py`，定义追踪用的数据结构。
- 新增 `src/bangdream_yolo/tracker/note_tracker.py`，实现轻量跨帧 tracker。
- 扩展 `src/bangdream_yolo/tools/live_preview.py`，增加 tracker 调试叠加开关，显示 lane、track_id、ETA。
- 增加面向 postprocess/tracker 的小型测试或可重复验证脚本。
- 更新 README 的 m5 使用说明。

本次不做：

- 不调用 `minitouch`，不产生任何触控输入。
- 不实现 m6 的 pointer 池、按下、保持、移动、释放调度。
- 不把 `green_note` 区分为头、尾或 slide 节点；绿色 note 仍只作为统一类别追踪。
- 不引入复杂多目标追踪框架，不做卡尔曼滤波、匈牙利匹配等重型设计。
- 不把 tracker 作为正式闭环主程序；m5 只提供调试预览和后续 m6 可调用的模块。

## 技术细节

### 输入与边界

- 输入图像来自 `NemuIpc.screenshot()`，坐标系仍为 capture-space BGR ndarray 坐标。
- YOLO 输出来自 Ultralytics `model.predict(frame, ...)` 的单帧 result。
- 几何信息读取 `data/calibration.yml`，复用：
  - `load_calibration(...)`
  - `point_to_lane(...)`
  - `normalize_capture_point(...)`
- 类别顺序沿用 m3/m4：

```text
0 tap
1 skill
2 flick
3 green_note
```

### `NoteDetection`

建议字段：

- `note_type: str`：`tap` / `skill` / `flick` / `green_note`
- `lane: int`：0 到 `lane_count - 1`
- `bbox: tuple[float, float, float, float]`：`x1, y1, x2, y2`
- `center_x: float`
- `center_y: float`
- `track_x: float`：透视变换后的归一化轨道 X
- `track_y: float`：透视变换后的归一化轨道 Y，判定线约为 `1.0`
- `confidence: float`

`postprocess.py` 只做确定性转换和过滤：

- 忽略未知 class id。
- 忽略低于 `conf_threshold` 的框。
- 用检测框中心点做 lane 映射。
- 不在 postprocess 里判断是否该点击。

### `TrackedNote`

建议字段：

- `track_id: int`
- `note_type: str`
- `lane: int`
- `latest: NoteDetection`
- `history: list[tuple[float, float]]`：`timestamp, track_y`
- `missed_frames: int`
- `velocity_y: float | None`：归一化轨道坐标每秒下落速度
- `eta_seconds: float | None`：到判定线的剩余秒数
- `is_active: bool`

ETA 计算：

- 用最近 `history_size` 个点做简单线性回归，默认 6 个点。
- 判定线使用归一化 `track_y = 1.0`。
- 当 `velocity_y <= min_velocity_y` 或历史点不足时，`eta_seconds = None`。
- 否则 `eta_seconds = (1.0 - latest.track_y) / velocity_y`。
- ETA 可以为负，表示已经越过判定线；m5 只展示，不触发操作。

### 数学过程：透视坐标、拟合速度与 ETA

m5 采用纯 ETA 路线，不使用 hitbox 碰撞触发。整体链路是：

```text
YOLO bbox -> bbox center -> perspective transform -> track_x/track_y -> lane -> track -> velocity_y -> ETA
```

坐标系：

- `capture-space`：原始截图像素坐标，左上角为 `(0, 0)`，右下角为 `(capture_width, capture_height)`。
- `track-space`：透视变换后的归一化轨道坐标，远端轨道边界约为 `track_y = 0.0`，判定线约为 `track_y = 1.0`。

YOLO 检测框中心点：

```text
center_x = (x1 + x2) / 2
center_y = (y1 + y2) / 2
```

透视变换使用 m2 标定得到的 4 个点，把截图里的轨道四边形映射到单位矩形：

```text
track_top_left  -> (0, 0)
track_top_right -> (1, 0)
judge_right     -> (1, 1)
judge_left      -> (0, 1)
```

矩阵形式：

```text
[u, v, w]^T = H * [center_x, center_y, 1]^T
track_x = u / w
track_y = v / w
```

其中 `H` 是 OpenCV `getPerspectiveTransform(...)` 由 4 对点求出的 3x3 单应性矩阵。除以 `w` 是齐次坐标到普通二维坐标的归一化步骤。

lane 映射：

```text
lane_raw = floor(track_x * lane_count)
lane = clamp(lane_raw, 0, lane_count - 1)
```

`floor` 表示向下取整，用来判断点落在 7 等分中的哪一段；`clamp` 用来避免 YOLO 框中心稍微跑出轨道时得到 `-1` 或 `7` 这样的非法 lane。

同一个 `track_id` 保存最近 N 个历史点：

```text
(t1, y1), (t2, y2), ..., (tn, yn)
```

其中 `t` 是 `time.perf_counter()` 秒数，`y` 是 `track_y`。线性拟合假设短时间内同一个 note 在 track-space 里近似匀速下落：

```text
track_y = velocity_y * t + b
```

斜率计算：

```text
mean_t = average(ti)
mean_y = average(yi)
velocity_y = sum((ti - mean_t) * (yi - mean_y)) / sum((ti - mean_t)^2)
```

ETA 计算使用拟合线在当前时间的估计位置，减少单帧 YOLO bbox 抖动影响：

```text
fitted_y_now = mean_y + velocity_y * (now - mean_t)
eta_seconds = (1.0 - fitted_y_now) / velocity_y
```

有效性条件：

- 历史点少于 3 个时，`velocity_y = None` 且 `eta_seconds = None`。
- `velocity_y <= min_velocity_y` 时，不输出 ETA。
- ETA 可以为负数，表示 note 已经过判定线。
- m5 只显示 ETA，不根据 ETA 触发点击；触控调度留到 m6。

### 跨帧关联

第一版 tracker 使用直接、可删改的规则：

- 每帧输入 `timestamp` 和一组 `NoteDetection`。
- 按 `lane` 分桶，只在同 lane 内匹配。
- 优先匹配相同 `note_type`；避免普通键和绿键互相抢 track。
- 对每个 detection，找最近的未匹配 active track。
- 匹配距离优先使用 `abs(detection.track_y - predicted_track_y)`；没有速度估计时使用 `abs(detection.track_y - latest.track_y)`。
- 默认 `max_track_y_distance = 0.12`，超过则新建 track。
- 未匹配 track 的 `missed_frames += 1`；超过 `max_missed_frames = 2` 后标记为 inactive。
- 已越过判定线较多的 track 可在 `track_y > 1.10` 后清理。

绿色 note 处理：

- `green_note` 只参与检测和追踪。
- m5 不根据绿色连续帧推断按下/释放。
- 后续 m6 根据 `green_note` 的 lane、ETA、连续存在状态和 pointer 状态判断动作语义。

### 实时调试

在 `live_preview.py` 增加开关：

```powershell
python -m bangdream_yolo.tools.live_preview --device 0 --show-tracks
```

开启后：

- 加载 `data/calibration.yml`。
- 每帧把 YOLO result 转为 `NoteDetection`，送入 tracker。
- 在预览窗口叠加 `lane`、`track_id`、`ETA`。
- 保留现有检测框绘制、FPS、窗口等比显示逻辑。
- 未开启 `--show-tracks` 时，m4 预览行为保持不变。

### 配置默认值

第一版使用模块常量或 CLI 参数，避免过度配置化：

- `history_size = 6`
- `max_missed_frames = 2`
- `max_track_y_distance = 0.12`
- `min_velocity_y = 0.05`
- `stale_track_y = 1.10`

如实测 ETA 抖动明显，再在 m8 调优阶段调整。

## 验收标准

- `python -m bangdream_yolo.tools.live_preview --help` 能看到 `--show-tracks`。
- `--show-tracks` 未开启时，实时预览仍只显示 m4 检测框，行为不变。
- `--show-tracks` 开启且 `data/calibration.yml` 存在时，预览窗口能显示 lane、track_id、ETA。
- 同一个下落 note 在连续帧中保持相同 `track_id`，偶发 1 到 2 帧漏检后仍可续命。
- ETA 在 note 下落过程中整体递减，到判定线附近接近 0。
- `tap`、`skill`、`flick`、`green_note` 都能被转换为 `NoteDetection`，绿色不再拆分头尾。
- 测试或验证脚本覆盖：
  - class id 到 note 类型映射；
  - 检测框中心点到 lane 映射；
  - 合成连续帧能得到稳定 `track_id`；
  - 丢检不超过 2 帧时 track 不立即消失。

## 风险与回滚

风险：

- 标定点不准会直接影响 lane 和 ETA。
- 归一化轨道 Y 只能近似表示视觉下落进度，实际 ETA 仍可能抖动。
- 同 lane 内连续密集 note 可能出现 track 交换。
- YOLO 漏检或误检会造成 track 短暂中断或幽灵 track。

回滚：

- m5 模块独立于 m4 训练和模型权重；如 tracker 效果不好，可关闭 `--show-tracks` 回到纯检测预览。
- `live_preview.py` 保留默认纯检测行为；m5 失败不影响 m4 模型验证。
- 后续可通过调小/调大 `max_track_y_distance`、`history_size`、`max_missed_frames` 做局部修正。

## 已确认决策

- m5 采用“轻量贪心关联 + 线性回归 ETA”，暂不引入更复杂的跟踪算法。
- m5 调试入口放在现有 `live_preview.py --show-tracks`，不新增独立 `track_preview.py`。
- m5 不使用 hitbox 碰撞触发；后续 m6 使用 ETA 和 `latency_offset` 做触控时机。
