---
name: bangdream-yolo-autoplay
overview: 在 MuMu Player 12 上做 BanG Dream! 自动打歌：nemu_ipc 低延迟截图 → YOLOv8 识别 note → 跨帧跟踪估 ETA → minitouch 多指调度。手动录制并标注数据集。
todos:
  - id: m0_env
    content: 里程碑 0：环境与 sanity。创建 requirements.txt（ultralytics, opencv-python, numpy, adbutils, pyyaml, loguru）、README 骨架与免责声明、config.py（MuMu 路径/instance_id/ADB serial），验证 external_renderer_ipc.dll 可加载、adb 可连。
    status: completed
  - id: m1_capture
    content: 里程碑 1：裁剪 ALAS 的 nemu_ipc 实现到 src/bangdream_yolo/capture/nemu_ipc.py（单文件、无 ALAS 依赖），提供 connect/disconnect/screenshot 返回 BGR ndarray。写连续截图 FPS 基准脚本，要求 ≥ 60 fps。
    status: completed
  - id: m1_minitouch
    content: 里程碑 1：minitouch 二进制下载到 third_party/minitouch/，input/minitouch.py 实现 adb push + forward + socket 控制，包装 down/up/move/commit，写多指同时点击的验证脚本（能在模拟器看到 5 个点同时起）。
    status: completed
  - id: m2_calibration
    content: 里程碑 2：geometry/calibration.py + tools/calibrate.py。交互式选 4 点（判定线左/右、轨道远端左/右），保存透视矩阵与 7 lane 中心到 data/calibration.yml。lane.py 提供 screen_xy<->lane_id 双向映射。
    status: completed
  - id: m3_dataset
    content: 里程碑 3：tools/record_session.py 录制选曲 PRO/EX 样本并抽帧。用 X-AnyLabeling 手标 4 类 note（tap/skill/flick/green_note），生成 YOLO 格式标签。8:1:1 划分 train/val/test，写 dataset.yaml。
    status: completed
  - id: m4_train
    content: 里程碑 4：tools/train.py 读取 4 类 data/dataset.yaml，调 yolov8s.pt 预训，imgsz=640，30-50 epochs。评估要求 mAP@0.5 ≥ 0.9，推理 ≤ 20ms (GPU)。导出 best.pt 到 models/。
    status: completed
  - id: m5_tracker
    content: 里程碑 5：detection/postprocess.py 将 YOLO 框转为 Note 实体（lane, type, y, conf；绿色统一为 green_note）。tracker/note_tracker.py 按 lane 分桶跨帧关联，线性回归估 v_y 与 ETA，支持 ≤2 帧丢检续命。
    status: completed
  - id: m6_policy
    content: 里程碑 6：policy/scheduler.py + input/pointer_pool.py。实现 pointer 池；tap/skill/flick/green_note 调度；按 ETA - latency_offset 触发 minitouch，下指/保持/移动/释放由绿色 note 的连续帧和 pointer 状态推断。
    status: in_progress
  - id: m7_loop
    content: 里程碑 7：src/bangdream_yolo/main.py 闭环主循环；viz/overlay.py 可选叠加检测框+ETA 调试窗口，绿色统一显示 green_note；在 EASY 鲁棒谱面跟踪 end-to-end 延迟，标定 latency_offset。
    status: pending
  - id: m8_tune
    content: 里程碑 8：PRO/EX 实战调优；bad case 帧按 4 类口径回流数据集并重训第二版；在 README 补上完整使用、标定、训练、及风险说明。
    status: pending
isProject: false
---


## 技术栈与核心决策（已确认）

- 目标游戏：BanG Dream! Girls Band Party（仅识别下落 note）
- 截图：`nemu_ipc`（`external_renderer_ipc.dll`，低延迟、零拷贝 RGBA）
- 触控：`minitouch` over ADB（多指必需，nemu_ipc 单点不够用）
- 模型：Ultralytics YOLOv8（640 imgsz 训练，1280×720 推理）
- 数据：手动录制抽样帧 + 手动标注 4 类 note（推荐 X-AnyLabeling / Roboflow）
- 模拟器分辨率：1600×900（16:9，参考 autodori 推荐）；游戏内流速固定 8.0、关闭 3D 切入

## 数据流总览

```mermaid
flowchart LR
    Emu[MuMu Player 12] -->|nemu_capture_display| Cap[Capture<br/>~5-10ms]
    Cap -->|"BGR ndarray"| YOLO[YOLOv8<br/>~10-20ms]
    YOLO -->|boxes| Post[Postprocess<br/>"box -> Note(lane,type,y)"]
    Post --> Track[Tracker<br/>ETA = "(jy-y)/v"]
    Track --> Sched[Scheduler<br/>+latency_offset]
    Sched -->|"d/u/m"| MT[Minitouch socket]
    MT -->|adb forward| Emu
    Cal[(Calibration<br/>透视 + lane)] -.-> Post
    Cal -.-> Sched
```

## 仓库结构

```
BangDream_yolo/
├── README.md                       # 风险声明 + 使用说明
├── docs/
│   ├── requirements/               # 每次迭代/功能更新：先写 REQ-*.md，确认后再写代码
│   └── (可选) development-plan.md  # 与 Cursor Plan 同步的路线图副本，便于仓库内查阅
├── requirements.txt
├── data/
│   ├── raw/                        # 录制原始帧（gitignored）
│   ├── labeled/{images,labels}/    # YOLO 数据集
│   ├── dataset.yaml
│   └── calibration.yml             # 透视矩阵 + lane 中心
├── models/                         # 训练权重
├── third_party/
│   └── minitouch/                  # 预编译 minitouch 二进制（多 abi）
├── src/bangdream_yolo/
│   ├── config.py
│   ├── capture/{nemu_ipc.py, recorder.py}
│   ├── input/{minitouch.py, pointer_pool.py}
│   ├── detection/{model.py, postprocess.py}
│   ├── geometry/{calibration.py, lane.py}
│   ├── tracker/{note_tracker.py, state.py}
│   ├── policy/{scheduler.py, flick.py}
│   ├── viz/overlay.py
│   ├── tools/{record_session.py, train.py, evaluate.py, calibrate.py}
│   └── main.py
└── tests/
```

## YOLO 类别（m3 第一版 4 类）

- `tap`（普通单点 note）
- `skill`（黄色/金色技能 note）
- `flick`（粉色滑键，第一版不区分方向）
- `green_note`（所有绿色长按/slide 实体节点；头尾语义由后续时序策略判断）

## 类别调整波及范围

- m3 标注与 `dataset.yaml` 只保留 4 类。
- m4 训练、评估和导出模型均以 4 类为准。
- m5 postprocess/tracker 不读取绿色头尾类别，只接收 `green_note` 并估计 lane/ETA。
- m6 policy 根据连续帧和 pointer 状态推断绿色 note 的按下、保持、移动、释放。
- m7 overlay 调试显示 `green_note`，不显示绿色头尾分类。
- m0-m2 不受影响。

## 关键实现要点

- **nemu_ipc 封装**：参考 [LmeSzinc/AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) 的 [`module/device/method/nemu_ipc.py`](https://github.com/LmeSzinc/AzurLaneAutoScript/blob/master/module/device/method/nemu_ipc.py)，抽出 `NemuIpcImpl` 单文件，去掉 ALAS 依赖。注意输出图像需要 `cv2.flip(img, 0)` 上下翻转 + `cvtColor(BGRA2BGR)`；坐标到 nemu 内部需做 `(x, y) -> (height - y, x)` 旋转。
- **minitouch 协议**：socket 文本协议 `d <id> <x> <y> <pressure>\n` / `u <id>\n` / `m <id> <x> <y> <pressure>\n`，用 `c\n` 提交一帧。同帧多指 down 合并提交以保证同步。预先 `adb push` minitouch 二进制到 `/data/local/tmp/`，`adb forward tcp:1111 localabstract:minitouch`。可直接复用 [EvATive7/minitouch](https://github.com/EvATive7/minitouch) 的二进制（autodori 同款）。
- **外置资源下载**：所有不进 Git 的外置资源（如 minitouch 二进制、后续模型权重、样例素材）统一接入 `python -m bangdream_yolo.tools.fetch_assets`。工具用 Python 标准库下载，按资源清单维护 URL、版本、许可证、目标路径和可选 SHA256；默认跳过已存在文件，支持 `--force` 覆盖。
- **几何标定**：交互式选 4 点（判定线左/右，远端轨道左/右），求透视矩阵；7 lane 中心通过判定线段 8 等分得到。屏幕 note 中心 → 反投影 → lane id + 屏幕 X（最终下指 X 用判定线那一行的实际 X，避免透视偏移）。
- **跟踪与 ETA**：按 lane 分桶，新框关联到上一帧最近 Y 且单调下落的 note；用最近 N 帧线性回归估 v_y(px/s)，ETA = (judge_y - y_now) / v_y。允许连续 ≤2 帧丢检续命。绿色 note 的头尾不依赖 YOLO 类别，由连续帧和 pointer 状态推断。
- **多指调度**：pointer 池管理同时触点；tap/skill 完即归还；flick 比 tap 提前约 20ms 触发，按游戏画面向下滑约 100px，滑动过程约 50ms 后 up；green_note 根据连续帧和当前按住状态决定按下、保持、移动或释放。`latency_offset` 经验值 ~40ms（截图 + 推理 + minitouch RTT），首次跑分时校准。
- **延迟预期**：端到端 30~50ms。EASY/NORMAL/PRO 难度可稳定 AP，EX 大部分谱面能跑通但凹 AP 不现实，SP/凹榜禁止（封号风险）。

## 风险与限制

- 视觉路线 ≠ 读谱路线，**EX/SP AP 几乎不可能**，请将期望对齐到 PRO 稳定 + EX 可玩。
- MuMu Player 12 需 ≥ 3.8.13；MuMuPlayerGlobal 不支持 nemu_ipc。
- README 必须明确：仅作 CV 学习项目，禁止冲榜，使用风险自负。

## 开发与文档流程（与 `.cursor/rules` 对齐）

- **路线图**：以本 Cursor Plan 的里程碑（m0–m8）为唯一开发顺序；开工前明确当前对应哪一条 todo。
- **每次更新**：在 [`docs/requirements/`](docs/requirements/) 新增 `REQ-YYYYMMDD-简短主题.md`，至少包含：背景与目标、范围（做/不做）、技术细节（接口、依赖、配置）、验收标准、已知风险；**与用户确认文档无误后再写实现代码**。
- **代码风格**：写清楚注释（模块意图、非显然分支、对外 API）；**避免**过度抽象、层层封装、为「未来扩展」预留的空架构；优先直线式、可读、可删的实现。
- **持久约定**：上述流程写入仓库 [`.cursor/rules/bangdream-workflow.mdc`](.cursor/rules/bangdream-workflow.mdc)，Agent 默认遵守。
