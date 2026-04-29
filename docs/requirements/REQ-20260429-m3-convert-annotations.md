# REQ-20260429-m3-convert-annotations

## 背景/目标

本修正对应主计划 `m3_dataset`。当前标注产物是 X-AnyLabeling/LabelMe 风格 JSON，后续 YOLO 训练需要同名 `.txt` 标签文件。因此需要一个本地转换工具，把已标注 JSON 和对应 PNG 整理到未划分数据目录，再交给 `split_dataset` 划分。

目标：

- 将 `temp/**/*.json` 转成 YOLO txt。
- 复制对应图片到 `data/annotated/images/`。
- 输出标签到 `data/annotated/labels/`。
- 转换时检查非法标签、缺失图片和文件名冲突。

## 范围

本次做：

- 新增 `src/bangdream_yolo/tools/convert_annotations.py`。
- 支持递归读取一个或多个源目录。
- 支持 `tap`、`skill`、`flick`、`green_note` 四类。
- 将 rectangle/polygon 点集转成 YOLO bbox。
- 更新 README 与 m3 REQ 的数据流程。

本次不做：

- 不训练模型。
- 不做自动标注。
- 不修改框的位置或类别判断。
- 不把 `data/annotated/`、`data/labeled/` 或 `temp/` 数据提交进 Git。

## 技术细节

新增命令：

```powershell
python -m bangdream_yolo.tools.convert_annotations `
  --source temp `
  --output data/annotated `
  --force
```

转换规则：

- 类别映射固定为：
  - `tap` -> `0`
  - `skill` -> `1`
  - `flick` -> `2`
  - `green_note` -> `3`
- JSON 中每个 shape 使用所有 points 的 min/max 得到 bbox。
- bbox 裁剪到 `[0, image_width]` 与 `[0, image_height]`。
- YOLO txt 行格式为：`class_id x_center y_center width height`，坐标均归一化到 `0..1`。
- 输出文件名包含源目录 slug 和短 hash，避免不同目录下同名 `frame_*.png` 冲突。
- 默认目标目录存在时报错；`--force` 清空后重建。

## 验收标准

- 能从当前 `temp/` 导出 `data/annotated/images/*.png` 与 `data/annotated/labels/*.txt`。
- 导出的 label 最大类别 id 为 `3`。
- 转换统计能打印样本数和每类框数量。
- 再运行 `split_dataset` 能生成 `data/labeled/images|labels/train|val|test`。
- `git status` 不把 `data/annotated/`、`data/labeled/`、`temp/` 数据作为未跟踪文件列出。

## 风险与回滚

风险：

- 标注 JSON 和图片不在同目录会导致缺失图片错误。
- 同名帧来自不同目录时，如果不改名会互相覆盖。
- 原始框若超出图片边界，裁剪可能轻微改变 bbox。

回滚：

- 本工具只生成可删除的 `data/annotated/` 输出，不修改源图片。
- 如转换规则不合适，可删除 `data/annotated/` 后调整脚本重新导出。
