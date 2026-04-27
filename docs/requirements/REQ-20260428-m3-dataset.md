# REQ-20260428-m3-dataset

## 背景/目标

本阶段对应主计划 `m3_dataset`，目标是为 YOLOv8 训练准备第一版真实截图数据集：

- 从 MuMu / `nemu_ipc` 录制 BangDream 打歌画面。
- 按固定策略抽帧，避免保存重复帧。
- 使用 YOLO 格式标注 5 类 note。
- 生成 `data/dataset.yaml`，为后续 m4 训练服务。

第一版目标不是一次覆盖所有复杂 note，而是先得到能训练、能验证、能迭代的数据闭环。

## 范围

本阶段做：

- 新增 `src/bangdream_yolo/tools/record_session.py`，用 `nemu_ipc` 连续截图并保存抽样帧。
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

第一版使用 5 类：

```text
0 tap
1 skill
2 flick
3 hold_head
4 hold_tail_or_slide
```

说明：

- `tap`：普通单点 note。
- `skill`：黄色/金色技能 note，动作上仍是点击，但外观和普通 tap 不同。
- `flick`：粉色滑键，第一版不区分方向。
- `hold_head`：绿色长按或 slide 的起点，需要按下。
- `hold_tail_or_slide`：绿色长按尾、slide 中间节点、slide 尾点先合并，降低第一版标注难度。

后续 m5/m6 若需要更精细策略，再扩展为 9 类。

## 数据目录

目录约定：

```text
data/
  raw/
    session_YYYYMMDD_HHMMSS/
      frame_000001.png
      frame_000002.png
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
- 第一版优先覆盖：
  - 普通 tap
  - skill
  - flick
  - 长按/slide 的绿色起点和后续点

建议规模：

- 第一轮先录制 300~500 张候选帧。
- 手动挑选并标注约 150~250 张高质量帧。
- 训练后根据 bad case 回流扩充。

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
  3: hold_head
  4: hold_tail_or_slide
```

## 验收标准

- `python -m bangdream_yolo.tools.record_session --seconds 5` 能保存若干 PNG 到 `data/raw/session_*`。
- 保存图像能正常打开，方向正确，分辨率符合当前 MuMu 设置。
- `python -m bangdream_yolo.tools.split_dataset ...` 能生成 train/val/test 目录。
- `data/dataset.yaml` 类别顺序与 REQ 一致。
- `git status` 不出现录制图片、标注图片、标签大批量未跟踪文件。

## 风险与回滚

风险：

- 抽样间隔过密会产生大量重复帧，增加标注负担。
- 5 类合并会让后续策略不够精细，但能降低第一版训练难度。
- 角色、背景、特效可能遮挡 note，导致标注不一致。

回滚：

- m3 改动限定在 `tools/record_session.py`、`tools/split_dataset.py`、`data/dataset.yaml` 和 README。
- 若类别设计不够用，后续新增 REQ 扩展类别，不直接覆盖旧数据。
