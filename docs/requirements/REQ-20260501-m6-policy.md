# REQ-20260501-m6-policy

## 背景/目标

本阶段对应主计划 `m6_policy`。m5 已经能把 YOLO 检测框转换为 `NoteDetection`，并跨帧输出 `TrackedNote`、`lane`、`track_id` 与 `ETA`。m6 的目标是把这些追踪结果转换为可执行的触控调度决策。

目标：

- 实现 pointer 池，管理同时按住的触点。
- 根据 `ETA - latency_offset` 判断 tap/skill/flick/green_note 的触发时机。
- 第一版先提供 dry-run 调试模式，输出将要发送的 down/move/up 事件。
- 真实 `minitouch` 写入必须显式启用，避免默认误触。

## 范围

本次做：

- 新增 `src/bangdream_yolo/input/pointer_pool.py`，管理 pointer 分配、占用、释放。
- 新增 `src/bangdream_yolo/policy/scheduler.py`，把 `TrackedNote` 转换为调度动作。
- 新增 `src/bangdream_yolo/policy/flick.py`，集中 flick 的短滑参数与轨迹计算。
- 新增一个 m6 调试入口 `src/bangdream_yolo/tools/policy_preview.py`：
  - 默认 dry-run，只打印/叠加计划动作，不触控。
  - 显式 `--enable-touch` 后才连接 `MinitouchClient` 并发送命令。
- 复用 `data/calibration.yml` 的 `lane_touch_points(...)`，得到每条 lane 的判定线 touch 坐标。
- 更新 README 的 m6 使用说明。

本次不做：

- 不实现完整自动打歌闭环主程序；m7 再做 `main.py` 连续闭环整合。
- 不做复杂谱面级预测，不读取谱面文件。
- 不区分绿色头、尾或 slide 子类；仍只接收 `green_note`。
- 不默认启用真实触控。
- 不追求 EX/AP 调优，m6 只验证调度链路和触控时机。

## 技术细节

### 输入与边界

输入来自 m5 tracker：

- `track_id`
- `note_type`
- `lane`
- `latest.track_y`
- `eta_seconds`
- `is_active`

触控坐标来自 m2 标定：

- `lane_touch_points(calibration)` 返回每条 lane 的 capture/touch 判定线中心。
- m6 下指位置默认使用对应 lane 的 touch 判定线中心。

触控发送使用 m1 的 `MinitouchClient`：

- `down(pointer_id, x, y, pressure=100)`
- `move(pointer_id, x, y, pressure=100)`
- `up(pointer_id)`
- `commit()`

`--enable-touch` 进入真实触控前，必须先做 minitouch 诊断：

- 读取并解析 minitouch banner：
  - `v <version>`：协议版本；
  - `^ <max_contacts> <max_x> <max_y> <max_pressure>`：最大触点数、坐标上限、压力上限；
  - `$ <pid>`：minitouch 进程 pid。
- 启动成功后在控制台打印 banner 摘要，便于判断当前二进制、ABI 和坐标系是否正常。
- 若 banner 暂时没有返回，允许继续运行，但打印“未读取到 banner”；此时无法做完整边界校验。
- 若连接后 banner 阶段立刻空关闭，但 minitouch 进程仍存活，视为启动期 localabstract socket 尚未准备好，应关闭本次 socket 并重试；只有进程退出时才判定为启动失败。
- 启动前和退出时都应清理远端残留 `minitouch` 进程，避免旧进程占用 localabstract socket 导致后续连接拿不到 banner 或触控无效。

### 触控坐标实测修正

2026-05-01 实测：发送 minitouch 单点 `(360, 921)` 后，通过 MuMu 截图与 Android `pointer_location` 叠加观察，触点实际出现在 capture 约 `(920, 360)`。这个点在 `transpose` 与 `clockwise` 下结果相同，不能单独判定方向。随后发送暂停按钮探针 `touch=(52, 1235)`，实际落在 capture 约 `(1235, 667)`，确认当前 MuMu 12 环境应使用 `clockwise` 映射：

```text
touch_x = capture_height - capture_y
touch_y = capture_x
```

m6 真实触控前应使用 `touch.rotation: clockwise`。若后续不同模拟器版本表现不同，仍可通过 `data/calibration.yml` 的 `touch.rotation` 切换。
- 发送 `down/move` 前校验：
  - `0 <= pointer_id < max_contacts`；
  - `0 <= x <= max_x`；
  - `0 <= y <= max_y`；
  - `0 <= pressure <= max_pressure`。
- 若设备 banner 返回 `max_pressure=0`，表示该触控设备不报告压力轴；此时不做压力上限校验，但仍保留发送的正 pressure 值，避免 down 被设备当成无效按压。
- 如果坐标或压力越界，直接抛出 `MinitouchError`，不把非法命令发给模拟器。
- 一批 scheduler 动作应尽量拼成一段 minitouch 文本后一次 `sendall`，减少 `down` 和 `commit` 分开发送时的中间状态，也方便输出完整失败上下文。
- 如果 `commit` 后仍然出现 `WinError 10053`，优先判断为 minitouch 后端、Android 输入权限、已有连接占用、ABI 或模拟器输入设备问题，而不是 YOLO / ETA / scheduler 本身错误。

### 配置默认值

第一版使用模块常量和 CLI 参数，避免过度配置化：

- `latency_offset = 0.040` 秒
- `tap_hold_seconds = 0.030`
- `flick_duration = 0.050` 秒
- `flick_distance = 100` touch 像素
- `flick_lead_seconds = 0.020` 秒
- `trigger_window_before = 0.025` 秒
- `trigger_window_after = 0.080` 秒
- `green_release_grace = 0.120` 秒
- `pressure = 100`（参考 ALAS 的 minitouch click 默认压力；若设备 banner 返回 `max_pressure=0`，仍保留正 pressure 发送）
- `max_pointers = 10`

触发窗口含义：

```text
fire_time = now + eta_seconds - latency_offset
```

当某个未触发 track 满足：

```text
-trigger_window_after <= eta_seconds - latency_offset <= trigger_window_before
```

则认为它到达可触发窗口。超过 `trigger_window_after` 仍未触发的 track 视为过期，不再补打，避免明显晚按。

### Pointer 池

建议数据结构：

- `PointerSlot`
  - `pointer_id: int`
  - `track_id: int | None`
  - `lane: int | None`
  - `note_type: str | None`
  - `is_down: bool`
  - `down_time: float | None`
  - `x: int | None`
  - `y: int | None`

`PointerPool` 行为：

- `acquire(track_id, lane, note_type, x, y, now) -> PointerSlot | None`
- `release(track_id) -> PointerSlot | None`
- `get_by_track(track_id) -> PointerSlot | None`
- `active_slots() -> list[PointerSlot]`

如果没有可用 pointer，scheduler 记录 warning 并跳过该 track，不抛出导致主循环退出的异常。

### Scheduler 输出

为了 dry-run 和真实触控共用同一套策略，scheduler 先产出动作列表：

```text
TouchAction(kind, pointer_id, x, y, track_id, note_type)
```

`kind` 取值：

- `down`
- `move`
- `up`
- `commit`

dry-run 模式只打印动作；真实模式把动作转换为 `MinitouchClient` 调用。手动 `MinitouchClient.tap(...)` 按 ALAS 风格拼成一个 payload：`down -> commit -> wait -> up -> commit -> sendall`。

### tap / skill

`tap` 和 `skill` 第一版动作相同：

1. 进入 ETA 触发窗口后分配 pointer。
2. 在 lane 判定线 touch 坐标 `down`。
3. 同一批动作最后 `commit`。
4. 保持 `tap_hold_seconds` 后 `up`。
5. 再 `commit`。
6. 标记该 `track_id` 已触发，避免重复点击。

### flick

`flick` 第一版不区分方向，统一按游戏画面向下短滑：

1. 进入 ETA 触发窗口后分配 pointer。
2. 在 lane 判定线 touch 坐标 `down`。
3. 比普通 tap 提前 `flick_lead_seconds` 进入触发窗口。
4. 在 `flick_duration` 内跨多帧逐步 `move` 到滑动终点。
5. 到达 `flick_duration` 后 `up`。
6. 标记该 `track_id` 已触发。

当前 `touch.rotation: clockwise` 下，游戏画面向下对应 `touch_x - flick_distance`，`touch_y` 不变。若后续切换模拟器或旋转配置，需要重新确认 flick delta。

### green_note

绿色 note 第一版不依赖 YOLO 头尾分类，使用 pointer 状态推断：

- 若 `green_note` 进入 ETA 触发窗口，且当前 lane 没有绿色 pointer，则 `down` 并保持。
- 若同 lane 已有绿色 pointer，且继续看到 `green_note`，则保持；必要时按 lane 判定线 touch 坐标 `move`。
- 若某个绿色 pointer 对应 lane 在 `green_release_grace` 内没有新的 `green_note` 续上，或相关 track 已经 inactive 且 ETA 明显为负，则 `up`。
- 第一版只支持按 lane 保持，不追求复杂 slide 横向移动；如果后续看到绿色 slide 需要跨 lane 移动，再在 m7/m8 调整策略。

### 调试入口

建议命令：

```powershell
python -m bangdream_yolo.tools.policy_preview --device 0 --dry-run
```

默认行为：

- 启动截图、YOLO、m5 tracker。
- 加载 calibration。
- 在窗口叠加检测框、track、ETA 和即将触发的动作。
- 控制台打印 dry-run touch actions。
- 不连接 `MinitouchClient`。

真实触控必须显式：

```powershell
python -m bangdream_yolo.tools.policy_preview --device 0 --enable-touch
```

`--enable-touch` 启用后：

- 启动 `MinitouchClient`。
- 发送 scheduler 产出的 down/move/up/commit。
- 按 `q` 或 `Esc` 停止时释放所有 active pointer。
- 如果 `minitouch` socket 中途断开，工具应包装为 `MinitouchError` 并优雅退出；若连接已经失效，退出清理阶段不再二次发送释放动作。

## 验收标准

- `python -m bangdream_yolo.tools.policy_preview --help` 能显示参数。
- 默认 dry-run 模式不会连接或调用 `minitouch`。
- `--enable-touch` 启动后控制台会打印 minitouch banner 摘要。
- 真实触控发送前会根据 banner 拦截越界 pointer、坐标或 pressure。
- `python -m bangdream_yolo.tools.test_multitouch --single` 可作为独立于 YOLO/policy 的 minitouch smoke test。
- `tap` / `skill` 进入 ETA 触发窗口时只触发一次 down/up。
- `flick` 进入 ETA 触发窗口时产生 down/move/up。
- `green_note` 能在连续帧中保持 pointer，并在断续超过 `green_release_grace` 后释放。
- pointer 池不会重复把同一个 pointer 分配给多个 active track。
- 无可用 pointer 时记录 warning，主循环继续运行。
- 所有退出路径释放 active pointer。
- 单元/合成测试覆盖：
  - pointer acquire/release；
  - tap/skill 去重；
  - flick 动作序列；
  - green_note 保持与超时释放；
  - 过期 ETA 不补打。

## 风险与回滚

风险：

- `latency_offset` 默认值可能偏早或偏晚，需要 m7 实测校准。
- flick 方向可能因 touch 坐标旋转变化与预期相反。
- green_note 头尾语义仍是推断，长按/slide 可能提前释放或释放过晚。
- 真实触控可能影响游戏状态，必须先用 dry-run 验证。
- `minitouch` 进程可能因 ABI、权限或输入设备异常中途断开 socket。

回滚：

- `policy_preview.py` 默认 dry-run，真实触控由 `--enable-touch` 控制。
- m6 模块独立于 m5 预览；如策略异常，可继续使用 `live_preview --show-tracks` 验证检测和 ETA。
- 若真实触控异常，优先关闭 `--enable-touch`，只保留动作日志调试。
- 若 socket 已断开，工具关闭 adb forward 和 minitouch shell 进程，不再尝试继续发送触控命令。

## 已确认决策

- m6 先新增独立 `policy_preview.py`，不直接改成正式 `main.py` 闭环。
- 真实触控必须显式 `--enable-touch`，默认只 dry-run。
- flick 第一版统一按游戏画面向下短滑；当前 `clockwise` 映射下为 touch 坐标 `x - flick_distance`。
- green_note 第一版只按 lane 保持与释放，不处理复杂跨 lane slide。
