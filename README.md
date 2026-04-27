# BangDream YOLO

这是一个学习用途的计算机视觉项目，目标是在 MuMu Player 12 上通过截图识别 BanG Dream! Girls Band Party 的下落 note，并在后续阶段接入多指触控调度。

## 当前阶段

当前对应主计划 `m1_capture` / `m1_minitouch`：截图与多指输入验证。

已完成：

- 基础项目结构
- 依赖清单
- MuMu / ADB / `external_renderer_ipc.dll` 环境检查
- `nemu_ipc` 截图封装
- 截图 FPS 基准工具
- `minitouch` 多指输入封装
- 5 指点击测试工具
- 几何标定工具（4 点标定，输出 `data/calibration.yml`）

本阶段暂不做：

- YOLO 推理
- 自动打歌闭环

## 环境准备

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

运行 5 指触控测试：

```powershell
python -m bangdream_yolo.tools.test_multitouch
```

运行几何标定：

```powershell
python -m bangdream_yolo.tools.calibrate
```

按顺序点击：判定线左端、判定线右端、远端轨道左边界、远端轨道右边界。按 `s` 保存，`r` 重置，`q` 退出。

当前外置资源：`minitouch-prebuilt@1.2.0`（Apache-2.0，来源 [npm minitouch-prebuilt](https://www.npmjs.com/package/minitouch-prebuilt)，上游 [openstf/minitouch](https://github.com/openstf/minitouch)）。后续模型权重、样例素材等也会统一接入 `fetch_assets`。

## 已确认的本机默认配置

- MuMu 安装根目录：`C:\Program Files\Netease\MuMu`
- ADB serial：`127.0.0.1:16384`
- MuMu 实例 ID：`0`
- 推荐 MuMu 分辨率：`1280x720`
- `external_renderer_ipc.dll` 实测路径：`C:\Program Files\Netease\MuMu\nx_device\12.0\shell\sdk\external_renderer_ipc.dll`

## 风险声明

本项目仅用于计算机视觉、自动化输入与实时系统延迟控制的学习研究。请不要用于冲榜、破坏游戏公平性或任何违反游戏服务条款的用途。使用本项目可能导致账号或数据风险，后果由使用者自行承担。
