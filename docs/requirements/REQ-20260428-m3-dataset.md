# REQ-20260428-m3-dataset

## 背景/目标

本阶段对应主计划 `m3_dataset`，目标是为 YOLOv8 训练准备第一版真实截图数据集：

- 从 MuMu / `nemu_ipc` 录制 BangDream 打歌画面。
- 按固定策略抽帧，避免保存重复帧。
- 使用 YOLO 格式标注 4 类 note。
- 生成 `data/dataset.yaml`，为后续 m4 训练服务。

第一版目标不是一次覆盖所有复杂 note，而是先得到能训练、能验证、能迭代的数据闭环。

## 范围

本阶段做：

- 新增 `src/bangdream_yolo/tools/record_session.py`，用 `nemu_ipc` 连续截图并保存抽样帧。
- 新增 `src/bangdream_yolo/tools/convert_annotations.py`，把 X-AnyLabeling/LabelMe JSON 转为 YOLO txt。
- 新增 `src/bangdream_yolo/tools/split_dataset.py`，把已标注数据划分为 train/val/test。
- 新增 `data/dataset.yaml`，定义 YOLO 数据集路径与类别名。
- 更新 README，补充录制、标注、划分流程。

本阶段不做：

- 不训练模型。
- 不接入 YOLO 推理。
- 不自动生成标注。
- 不做谱面解析或 bestdori 数据接入。
- 不提交 `data/raw/`、`data/labeled/` 里的图片和标签。

## 类别设计

第一版使用 4 类：

```text
0 tap
1 skill
2 flick
3 green_note
```

说明：

- `tap`：普通单点 note。
- `skill`：黄色/金色技能 note，动作上仍是点击，但外观和普通 tap 不同。
- `flick`：粉色滑键，第一版不区分方向。
- `green_note`：所有清楚可见的绿色长按/slide 实体节点，包括起点、尾点和中间节点。

绿色头尾语义不交给 YOLO 分类；后续 m5/m6 通过连续帧、lane、ETA 和 pointer 状态判断按下、保持、移动、释放。

## 数据目录

目录约定：

```text
data/
  raw/
    session_YYYYMMDD_HHMMSS/
      frame_000001.png
      frame_000002.png
  annotated/
    images/
    labels/
  labeled/
    images/
      train/
      val/
      test/
    labels/
      train/
      val/
      test/
  dataset.yaml
```

Git 约定：

- `data/raw/` 忽略。
- `data/annotated/` 忽略。
- `data/labeled/` 忽略。
- `data/dataset.yaml` 提交。
- 少量用于 README 的示例图片如有需要，后续单独放 `docs/assets/`。

## 录制工具

新增工具：

- `python -m bangdream_yolo.tools.record_session`

参数：

- `--seconds 60`：录制时长，默认 60 秒。
- `--interval 0.1`：保存间隔，默认每 0.1 秒保存 1 帧（约 10 fps 抽样）。
- `--output data/raw/session_YYYYMMDD_HHMMSS`：输出目录，默认自动生成。
- `--warmup 1.0`：开始前等待，方便切到游戏画面。

实现细节：

- 使用 `NemuIpc.screenshot()` 获取 BGR 图像。
- 使用 `cv2.imwrite()` 保存 PNG。
- 文件命名用递增序号，避免时间戳过长。
- 控制台打印保存帧数、总耗时、平均保存 fps。
- 若截图分辨率不是推荐的 `1280x720`，打印警告但不中断。

## 标注流程

推荐使用 X-AnyLabeling 或 Roboflow 本地标注。

标注要求：

- 输出 YOLO txt 格式。
- 每张图片同名 `.txt`。
- 框尽量包住 note 本体，不包含过多光效。
- 只标「可见且足够清楚」的 note；太远、重叠、被角色遮挡严重的先不标。
- 绿色半透明轨迹光带不标，只标绿色 note 实体节点。
- 第一版优先覆盖：
  - 普通 tap
  - skill
  - flick
  - 长按/slide 的绿色实体节点

建议规模：

- 第一轮先录制 300~500 张候选帧。
- 手动挑选并标注约 150~250 张高质量帧。
- 训练后根据 bad case 回流扩充。

## 标注转换工具

新增工具：

- `python -m bangdream_yolo.tools.convert_annotations`

输入：

- X-AnyLabeling/LabelMe JSON 标注目录，例如 `temp/`。
- 每个 JSON 对应的 PNG 图片，优先使用 JSON 的 `imagePath`，路径相对 JSON 所在目录。

输出：

- `data/annotated/images/*.png`
- `data/annotated/labels/*.txt`

实现细节：

- 递归读取源目录下的 `.json` 文件。
- 类别映射与 `data/dataset.yaml` 保持一致：`tap=0`、`skill=1`、`flick=2`、`green_note=3`。
- 每个 shape 的所有点取 min/max 转成 YOLO bbox，并裁剪到图像边界。
- 输出文件名包含源目录信息，避免多个目录里同名 `frame_*.png` 互相覆盖。
- 默认目标目录已存在时报错，支持 `--force` 清空后重建。

## 波及范围

- m4 训练只读取 4 类 `data/dataset.yaml`。
- m5 tracker 接收 `green_note`，不再依赖绿色头尾类别。
- m6 policy 通过连续帧、lane、ETA 和 pointer 状态推断绿色 note 的按下、保持、移动、释放。
- m0-m2 的环境、截图、触控和标定能力不受类别调整影响。

## 数据划分工具

新增工具：

- `python -m bangdream_yolo.tools.split_dataset`

输入：

- 未划分的图片目录，例如 `data/annotated/images`
- 未划分的标签目录，例如 `data/annotated/labels`

输出：

- `data/labeled/images/train|val|test`
- `data/labeled/labels/train|val|test`

默认比例：

- train：80%
- val：10%
- test：10%

实现细节：

- 只处理同时存在图片和同名 label 的样本。
- 使用固定随机种子 `42`，保证可复现。
- 默认复制文件，不移动源文件。
- 如果目标目录已存在，默认报错；支持 `--force` 清空后重建。

## dataset.yaml

新增：

- `data/dataset.yaml`

内容：

```yaml
path: data/labeled
train: images/train
val: images/val
test: images/test
names:
  0: tap
  1: skill
  2: flick
  3: green_note
```

## 验收标准

- `python -m bangdream_yolo.tools.record_session --seconds 5` 能保存若干 PNG 到 `data/raw/session_*`。
- 保存图像能正常打开，方向正确，分辨率符合当前 MuMu 设置。
- `python -m bangdream_yolo.tools.convert_annotations --source temp --output data/annotated` 能导出 YOLO 图片和标签。
- `python -m bangdream_yolo.tools.split_dataset ...` 能生成 train/val/test 目录。
- `data/dataset.yaml` 类别顺序与 REQ 一致。
- `git status` 不出现录制图片、标注图片、标签大批量未跟踪文件。

## 风险与回滚

风险：

- 抽样间隔过密会产生大量重复帧，增加标注负担。
- 4 类检测不直接提供绿色头尾语义，后续 tracker/policy 需要承担时序判断。
- 角色、背景、特效可能遮挡 note，导致标注不一致。

回滚：

- m3 改动限定在 `tools/record_session.py`、`tools/split_dataset.py`、`data/dataset.yaml` 和 README。
- 若类别设计不够用，后续新增 REQ 扩展类别，不直接覆盖旧数据。
