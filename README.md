# BangDream YOLO

这是一个学习用途的计算机视觉项目，目标是在 MuMu Player 12 上通过截图识别 BanG Dream! Girls Band Party 的下落 note，并在后续阶段接入多指触控调度。

## 当前阶段

当前对应主计划 `m6_policy`：基于 m5 的 lane、track_id 与 ETA，设计 pointer 池和触控调度策略。

已完成：

- 基础项目结构
- 依赖清单
- MuMu / ADB / `external_renderer_ipc.dll` 环境检查
- `nemu_ipc` 截图封装
- 截图 FPS 基准工具
- `minitouch` 多指输入封装
- 单点/5 指点击测试工具
- 几何标定工具（4 点标定，输出 `data/calibration.yml`）
- m3 录制与数据集划分工具
- m4 训练入口、5 类 green_bar 模型与实时检测预览窗口
- m5 检测后处理、跨帧追踪与 ETA 调试叠加

本阶段暂不做：

- 自动打歌闭环

## 环境准备

### 新用户最快启动

本项目提供 Windows 一键启动脚本，适合 clone 后快速准备环境并启动：

```powershell
Copy-Item .\config.example.yml .\config.yml
notepad .\config.yml
```

在 `config.yml` 中集中配置本机路径与启动参数，重点检查：

- `mumu_path`：MuMu Player 12 安装根目录
- `adb_serial`：目标模拟器 ADB serial，默认 `emulator-5554`
- `model_path`：默认模型 `models/bangdream_yolo_m4_green_bar.pt`
- `calibration_path`：标定文件，默认 `data/calibration.yml`
- `asset_abi`：MuMu Player 12 常用 `x86_64`
- `enable_touch`：`true` 会真实发送 minitouch 触控事件

确认 MuMu 实例和游戏画面已启动后，双击根目录的 `一键启动.bat`。脚本会自动创建 `.venv`、安装依赖、安装本项目、下载 `minitouch`、运行环境检查，并按 `config.yml` 启动。

首次真实触控前建议先运行单点测试，确认 minitouch 后端可用：

```powershell
.\.venv\Scripts\python.exe -m bangdream_yolo.tools.test_multitouch --single
```

如需只看识别窗口、不触控，可把 `config.yml` 中的 `mode` 改为 `live_preview`，或把 `enable_touch` 改为 `false`。

### 手动准备

建议使用 Python 3.11：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

运行环境检查：

```powershell
python -m bangdream_yolo.tools.check_env
```

运行截图基准：

```powershell
python -m bangdream_yolo.tools.benchmark_capture --frames 300
```

下载外置资源（例如 `minitouch`，二进制不提交到 Git）：

```powershell
python -m bangdream_yolo.tools.fetch_assets
```

工具会优先通过 ADB 读取设备 ABI，并把资源保存到约定目录；若自动读取失败，可手动指定：

```powershell
python -m bangdream_yolo.tools.fetch_assets --abi x86_64
```

运行 minitouch 单点 smoke test：

```powershell
python -m bangdream_yolo.tools.test_multitouch --single
```

单点能成功后，再运行 5 指触控测试：

```powershell
python -m bangdream_yolo.tools.test_multitouch
```

运行几何标定：

```powershell
python -m bangdream_yolo.tools.calibrate
```

按顺序点击：判定线左端、判定线右端、远端轨道左边界、远端轨道右边界。按 `s` 保存，`r` 重置，`q` 退出。

录制待标注截图：

```powershell
python -m bangdream_yolo.tools.record_session --seconds 60 --interval 0.1
```

默认输出到 `data/raw/session_YYYYMMDD_HHMMSS/`。录制图片不提交到 Git。

转换 X-AnyLabeling/LabelMe 标注为 YOLO 数据：

```powershell
python -m bangdream_yolo.tools.convert_annotations `
  --source temp `
  --output data/annotated `
  --force
```

默认会递归读取源目录下的 JSON，复制对应 PNG，并生成 `data/annotated/images/` 与 `data/annotated/labels/`。

划分已标注 YOLO 数据：

```powershell
python -m bangdream_yolo.tools.split_dataset `
  --images data/annotated/images `
  --labels data/annotated/labels `
  --output data/labeled
```

当前类别：`tap`、`skill`、`flick`、`green_note`、`green_bar`。绿色长按/slide 由 m6 的 `green_bar` 状态机处理：底部 `green_bar` 到线后按住并持续跟随，终点 `green_note` 到线时松开，终点 `flick` 到线时复用 held pointer 划出；`green_bar` 本身不作为释放终点，数据集配置见 `data/dataset.yaml`。

类别调整波及范围：m4 训练、m5 跟踪、m6 调度和 m7 调试叠加都按 5 类处理；m6 绿色触控由 `green_bar` 驱动，m0-m2 的环境、截图、触控和标定不受影响。

运行 m4 冒烟训练：

```powershell
python -m bangdream_yolo.tools.train --epochs 1 --name m4_smoke_e1
```

正式训练可改用 `--model yolov8s.pt --epochs 50`，并用 `--copy-best models/bangdream_yolo_m4_green_bar.pt` 保存 best 权重。GPU 训练需要当前 Python 环境安装 CUDA 版 PyTorch，可用 `--device 0` 强制使用第 0 张显卡。`runs/` 不提交到 Git；仓库已包含当前默认运行所需的 `models/` 权重。

当前实时预览和策略预览默认使用 5 类 green_bar 模型：`models/bangdream_yolo_m4_green_bar.pt`；如需临时回退 flick 旧模型，可显式传 `--model models/bangdream_yolo_m4_flick.pt`。

启动实时识别预览窗口（只显示检测框，不会触控）：

```powershell
python -m bangdream_yolo.tools.live_preview --device 0 --topmost
```

按 `q` 或 `Esc` 退出。若提示 `nemu_connect` 失败，先确认 MuMu 实例和游戏画面已经启动，再运行 `python -m bangdream_yolo.tools.check_env` 排查连接状态。

预览窗口会在首帧截图后按画面比例调整到 `--window-width` / `--window-height` 范围内，默认 1280×720；用户手动拉伸窗口时会用黑边等比居中显示，游戏画面不会被压扁。

开启 m5 跟踪调试叠加（显示 lane、track_id、ETA，不会触控）：

```powershell
python -m bangdream_yolo.tools.live_preview --device 0 --topmost --show-tracks
```

`--show-tracks` 需要先完成 `data/calibration.yml` 标定；本阶段只验证追踪和 ETA，自动触控留到 m6。

运行 m6 策略预览（默认 dry-run，只显示和打印动作，不触控）：

```powershell
python -m bangdream_yolo.tools.policy_preview --device 0 --topmost
```

确认动作时机后，如需真实发送 minitouch 事件，必须显式启用：

```powershell
python -m bangdream_yolo.tools.policy_preview --device 0 --topmost --enable-touch
```

真实触控启动时会打印 minitouch banner，例如 `max_contacts/max_x/max_y/max_pressure/pid`；若首个 `commit` 后仍断开，先用 `test_multitouch --single` 判断是否为 minitouch 后端、权限、ABI 或已有连接占用问题。

当前外置资源：`minitouch-prebuilt@1.2.0`（Apache-2.0，来源 [npm minitouch-prebuilt](https://www.npmjs.com/package/minitouch-prebuilt)，上游 [openstf/minitouch](https://github.com/openstf/minitouch)）。后续模型权重、样例素材等也会统一接入 `fetch_assets`。

## 已确认的本机默认配置

- MuMu 安装根目录：`C:\Program Files\Netease\MuMu`
- ADB serial：`emulator-5554`
- MuMu 实例 ID：`0`
- 推荐 MuMu 分辨率：`1280x720`
- `external_renderer_ipc.dll` 实测路径：`C:\Program Files\Netease\MuMu\nx_device\12.0\shell\sdk\external_renderer_ipc.dll`

## 风险声明

本项目仅用于计算机视觉、自动化输入与实时系统延迟控制的学习研究。请不要用于冲榜、破坏游戏公平性或任何违反游戏服务条款的用途。使用本项目可能导致账号或数据风险，后果由使用者自行承担。
