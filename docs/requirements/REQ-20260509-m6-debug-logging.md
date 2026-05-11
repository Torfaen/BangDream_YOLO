# REQ-20260509-m6-debug-logging

## 背景/目标

m6 实机调试 green_bar / green_note / flick 时，单靠窗口叠字和终端动作日志很难复盘：需要同时看到当前帧原图、YOLO 检测、tracker 状态、policy 触控动作，以及绿色状态机为什么释放或忽略某个节点。

本次新增 `policy_preview.py` 的调试日志模式。默认在 `logs/` 下为每次运行创建独立 session，持续写入结构化 JSONL，并在关键事件帧保存原图与标注图，方便事后按帧回看。

## 范围

本次做：

- 新增 `--debug-log`，只在显式开启时记录。
- 默认采用事件优先截图：每帧写轻量 JSONL；有动作、warning、绿色状态机事件或手动截图时保存图片。
- 日志只接入 `policy_preview.py`，不影响 `live_preview.py`。
- 使用标准库 JSON/pathlib/datetime 与现有 `cv2.imwrite`，不新增依赖。

本次不做：

- 不做自动视频合成。
- 不把日志产物提交进 Git；`logs/` 已在 `.gitignore`。
- 不改变现有触控调度语义。

## 技术细节

新增 CLI 参数：

```text
--debug-log
--debug-log-dir logs
--debug-log-screenshots event|all|none
--debug-log-every N
```

每次运行目录：

```text
logs/policy_YYYYMMDD_HHMMSS/
  meta.json
  frames.jsonl
  events.jsonl
  raw/frame_000123.png
  overlay/frame_000123.png
```

`frames.jsonl` 每帧记录：

- `frame_index`、`timestamp`、`fps`、`touch_enabled`。
- detections：`type/conf/bbox/center/track_x/track_y/lane`。
- tracks：`track_id/type/lane/track_y/eta/velocity/missed_frames/history_len`。
- policy actions、warnings。
- green hold 快照。

`events.jsonl` 记录关键事件：

- 当前帧有 `down/move/up/commit` 动作。
- 当前帧有 warning。
- green hold 创建、跟随、green_note 释放、flick 终点、兜底释放。
- green_note 被忽略，并记录 reason：`start_echo`、`pre_bar_transition`、`near_visible_unstable_echo`、`not_ready`。
- 用户按 `s` 手动保存当前帧。

截图策略：

- `event`：只在有事件时保存原图与标注图。
- `all`：按 `--debug-log-every` 采样保存所有帧。
- `none`：只写 JSONL；按 `s` 仍保存当前帧，便于人工抓现场。

## 验收标准

- `python -m bangdream_yolo.tools.policy_preview --help` 显示新增参数。
- 开启 `--debug-log` 后创建 session 目录、`meta.json`、`frames.jsonl`、`events.jsonl`、`raw/`、`overlay/`。
- `frames.jsonl` 和 `events.jsonl` 每行均可被 `json.loads` 解析。
- `event` 模式下，无事件帧不保存截图；有动作/warning/绿色事件帧保存原图与标注图。
- `s` 键保存当前帧并写入 `manual_snapshot` 事件。
- 单元测试和全量 `unittest discover` 通过。

## 风险与回滚

风险：

- `all` 截图模式会明显增加磁盘写入与 FPS 压力，只建议短时间复现。
- 事件截图如果绿色状态机每帧都有 move，仍可能产生较多图片。

回滚：

- 不传 `--debug-log` 即完全关闭该功能。
- 可用 `--debug-log-screenshots none` 保留 JSONL、关闭自动截图。
