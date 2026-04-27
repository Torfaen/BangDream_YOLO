# BangDream YOLO

这是一个学习用途的计算机视觉项目，目标是在 MuMu Player 12 上通过截图识别 BanG Dream! Girls Band Party 的下落 note，并在后续阶段接入多指触控调度。

## 当前阶段

当前对应主计划 `m0_env`：环境与可行性验证。

本阶段只做：

- 基础项目结构
- 依赖清单
- MuMu / ADB / `external_renderer_ipc.dll` 环境检查

本阶段暂不做：

- YOLO 推理
- nemu_ipc 截图主逻辑
- minitouch 多指控制
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

## 已确认的本机默认配置

- MuMu 安装根目录：`C:\Program Files\Netease\MuMu`
- ADB serial：`127.0.0.1:16384`
- MuMu 实例 ID：`0`
- `external_renderer_ipc.dll` 实测路径：`C:\Program Files\Netease\MuMu\nx_device\12.0\shell\sdk\external_renderer_ipc.dll`

## 风险声明

本项目仅用于计算机视觉、自动化输入与实时系统延迟控制的学习研究。请不要用于冲榜、破坏游戏公平性或任何违反游戏服务条款的用途。使用本项目可能导致账号或数据风险，后果由使用者自行承担。
