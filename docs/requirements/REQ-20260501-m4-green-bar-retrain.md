# REQ-20260501-m4-green-bar-retrain

## 背景/目标

m6 实机验证发现，仅靠 `green_note` 节点无法稳定处理带转向点的绿条。用户已在 `temp` 下三份标注目录补充 `green_bar` 标签，希望用完整 5 类标注数据重新训练模型，让 YOLO 同时识别绿色节点和绿条。

本次目标是将数据集从 4 类扩展到 5 类，并用已补标的三份数据重新转换、划分和重新训练。

## 范围

本次做：

- 类别顺序扩展为：

```text
0 tap
1 skill
2 flick
3 green_note
4 green_bar
```

- 更新 `convert_annotations.py`、`data/dataset.yaml`、推理后处理和预览颜色表。
- 使用以下三份已补标目录生成数据集：

```text
temp/session_20260428_131448_01 1
temp/session_20260501_173103
temp/新建文件夹
```

- 以 YOLOv8 预训练权重为起点重新训练，输出新模型 `models/bangdream_yolo_m4_green_bar.pt`。

本次不做：

- 不实现新的绿条按住策略。
- 不恢复绿色头/尾分类。
- 不使用颜色阈值识别绿条。

## 技术细节

`green_bar` 表示判定线附近或轨道上的绿色长条实体，后续策略会在限定 ROI 内使用其检测框中心作为按住位置。`green_note` 仍表示绿色实体节点。

当前三份标注目录统计：

```text
tap: 180
skill: 14
flick: 29
green_note: 123
green_bar: 64
```

训练命令使用 YOLOv8 预训练权重作为初始模型：

```powershell
python -m bangdream_yolo.tools.train `
  --model yolov8s.pt `
  --epochs 50 `
  --device 0 `
  --name m4_green_bar_retrain `
  --copy-best models/bangdream_yolo_m4_green_bar.pt
```

## 验收标准

- `convert_annotations` 能接受 `green_bar`。
- `data/dataset.yaml` 含 5 类，`green_bar` id 为 `4`。
- 导出的 YOLO txt 中最大类别 id 为 `4`。
- 训练能从 YOLOv8 预训练权重启动并复制 best 到 `models/bangdream_yolo_m4_green_bar.pt`。
- `postprocess_detections` 能保留 class `4` 为 `green_bar`；m6 只在已有 active green pointer 时使用 `green_bar` 驱动 move，不让它单独触发 `down` / `up`。

## 风险与回滚

风险：

- 三份数据量仍偏小，`green_bar` 可能过拟合当前歌曲/场景。
- 本次不是继承旧 4 类模型，旧模型里的 flick 实测调参经验不会直接继承，只依赖当前完整 5 类数据重新学习。
- m6 会使用判定线附近 `green_bar` 中心跟随 active green pointer；如果框中心偏差明显，还需要继续补数据或调 ROI/匹配策略。

回滚：

- 预览或策略运行时显式使用旧模型：`--model models/bangdream_yolo_m4_flick.pt`。
- 如 5 类效果不稳定，可继续补标更多 `green_bar` 后再次微调。
