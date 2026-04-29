# REQ-20260429-m4-live-preview

## 背景/目标

本阶段对应 `m4_train` 的模型效果验证。m4 已经训练出第一版 `models/bangdream_yolo_m4.pt`，需要一个可重复启动的实时预览窗口，用 MuMu `nemu_ipc` 截图并叠加 YOLO 检测框，方便肉眼检查漏检、误检和置信度。

目标：

- 用命令启动 OpenCV 预览窗口。
- 实时显示 `tap`、`skill`、`flick`、`green_note` 检测框。
- 不调用 `minitouch`，不产生任何触控输入。

## 范围

本次做：

- 新增 `src/bangdream_yolo/tools/live_preview.py`。
- 支持配置模型路径、置信度阈值、设备、窗口大小、是否置顶。
- 预览窗口允许用户手动拖拽；渲染前按窗口内容区尺寸生成黑底等比画布，画面仍保持原始比例。
- 更新 README 启动命令。
- 连接失败时给出 MuMu/ADB/nemu_ipc 排查提示。

本次不做：

- 不实现 note 跟踪、ETA 或 lane 映射。
- 不实现自动按键。
- 不保存视频或大批量截图。
- 不把预览窗口作为正式 UI 框架。

## 技术细节

新增命令：

```powershell
python -m bangdream_yolo.tools.live_preview --device 0
```

默认参数：

- `--model models/bangdream_yolo_m4.pt`
- `--conf 0.25`
- `--imgsz 640`
- `--device auto`
- `--window-width 1280`
- `--window-height 720`
- `--duration 0`（一直运行，直到按 `q` 或 `Esc`）

实现约定：

- 使用 `NemuIpc.screenshot()` 获取 BGR 图像。
- 使用 Ultralytics `YOLO.predict(...)` 做单帧推理。
- 先在原始截图上绘制检测框、类别、置信度和平均 FPS，再用 OpenCV `imshow` 显示等比 letterbox 画布。
- 首帧截图后按截图宽高比计算窗口尺寸，放入 `--window-width` / `--window-height` 边界内，避免启动时拉伸画面。
- 不依赖 `WINDOW_KEEPRATIO`；窗口使用 `WINDOW_FREERATIO` 接收任意拖拽尺寸，每帧通过 `getWindowImageRect()` 获取当前内容区，并把原始画面等比缩放居中贴到黑底画布，避免横向或纵向压扁。
- `--device auto` 时不显式传 device；传入 `0`、`cpu` 等值时原样转发。
- 设置 `YOLO_CONFIG_DIR=.cache/ultralytics`，避免写入受限用户目录。

## 验收标准

- `python -m bangdream_yolo.tools.live_preview --help` 能显示参数。
- MuMu 已启动且 `nemu_ipc` 可用时，命令能打开实时预览窗口。
- 按 `q` 或 `Esc` 后窗口关闭，进程退出。
- 用户手动拉伸窗口时，预览画面保持截图宽高比，不被横向或纵向压扁。
- 窗口只显示检测结果，不触发任何点击或滑动。

## 风险与回滚

风险：

- MuMu 实例未完全启动时，`nemu_connect` 可能返回 RPC 1722。
- OpenCV GUI 窗口在无桌面或权限受限环境中可能无法显示。
- 实时预览速度受截图、模型、GPU/CPU 状态影响。

回滚：

- 本工具独立于训练和数据集；如窗口不可用，可删除/停用 `live_preview.py`，不影响 m4 模型权重。
