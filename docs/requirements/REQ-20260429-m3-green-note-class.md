# REQ-20260429-m3-green-note-class

## 背景/目标

本修正对应主计划 `m3_dataset`。在首批标注中发现：绿色长按/slide 的头、尾、中间节点在单帧画面里长相高度相似，强行拆成 `hold_head` 与 `hold_tail_or_slide` 会给 YOLO 提供矛盾监督。

本阶段目标是把第一版数据集类别收敛为更稳定的视觉检测任务：

- YOLO 只检测绿色 note 实体节点，不判断头尾语义。
- 绿色长按/slide 的按下、保持、移动、释放交给后续 m5/m6 通过时序和 pointer 状态判断。
- 当前 temp 标注 JSON 中的绿色标签统一改为 `green_note`。

## 范围

本次做：

- 将 m3 第一版类别从 5 类改为 4 类。
- 更新 `data/dataset.yaml`、README、m3 REQ 与主计划副本中的类别描述。
- 将当前 temp 标注 JSON 中的旧绿色标签批量重命名为 `green_note`。
- 明确绿色轨迹光带不标，只标绿色 note 实体节点。

本次不做：

- 不训练模型。
- 不引入新的导出/转换工具。
- 不自动推断绿色 note 的头、尾或 slide 语义。
- 不重标轨迹光带、边缘光效或过远过小的 note。

## 技术细节

第一版 YOLO 类别固定为 4 类：

```text
0 tap
1 skill
2 flick
3 green_note
```

说明：

- `tap`：普通单点 note。
- `skill`：黄色/金色技能 note，动作上仍是点击。
- `flick`：粉色滑键，第一版不区分方向。
- `green_note`：所有清楚可见的绿色长按/slide 实体节点，包括起点、尾点和中间节点。

标注边界：

- 绿色半透明轨迹光带不标。
- 粉/绿边缘光效不标。
- 只标有效检测区域内、清楚可见且能框准的 note。
- 过远、过小、模糊、严重遮挡或无法稳定框准的 note 不标；该规则需要在同一批数据中保持一致。

## 波及范围

- **m3_dataset**：标注和 `data/dataset.yaml` 统一为 4 类，所有绿色实体节点使用 `green_note`。
- **m4_train**：训练脚本直接读取 4 类 `data/dataset.yaml`，导出的模型只输出 `tap`、`skill`、`flick`、`green_note`。
- **m5_tracker**：postprocess/tracker 接收 `green_note`，不再依赖 YOLO 输出绿色头、尾或 slide 子类。
- **m6_policy**：scheduler/pointer_pool 根据连续帧、lane、ETA、当前是否已有按住 pointer 来推断绿色 note 的操作阶段。
- **m7_loop / viz**：调试叠加层显示 `green_note`，不再显示绿色头尾分类。
- **不波及 m0-m2**：环境、截图、minitouch、标定和 lane 映射不需要改。

## 验收标准

- `data/dataset.yaml` 只包含 4 个类别，最大类别 id 为 `3`。
- 当前 temp 标注 JSON 中只出现 `tap`、`skill`、`flick`、`green_note`。
- 当前 temp 标注 JSON 中不再出现旧绿色拆分类别。
- README、m3 REQ 与主计划副本的类别描述一致。
- 绿色轨迹光带继续保持不标。

## 风险与回滚

风险：

- YOLO 无法直接输出绿色 note 的头尾语义，m5/m6 需要承担更多时序判断。
- 如果绿色节点漏检，长按/slide 策略可能提前释放或无法按下。
- 4 类模型更稳定，但策略精度依赖后续 tracker 和 pointer 状态机。

回滚：

- 若后续证明绿色头尾在视觉上可稳定区分，可新增 REQ 扩展类别，不直接覆盖当前 4 类数据。
- 若需要兼容旧标注，可在导出前临时映射旧标签名，但主数据集以 `green_note` 为准。
