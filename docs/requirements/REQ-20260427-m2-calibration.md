# REQ-20260427-m2-calibration

## 背景/目标

本阶段对应主计划 `m2_calibration`，目标是在固定 MuMu 分辨率下建立 BangDream 轨道几何标定：

- 截图画面中的 note 坐标可以转换为 7 条 lane。
- 判定线位置可以被稳定保存和复用。
- 后续 YOLO 检测框可以落到正确 lane，并得到用于下指的判定线坐标。

当前项目推荐标准分辨率：

- MuMu 横屏截图：`1280x720`
- ADB / minitouch 触控坐标可能表现为竖屏：`720x1280`

因此 m2 需要显式处理 **截图坐标系** 与 **触控坐标系** 的差异。

## 范围

本阶段做：

- 新增 `src/bangdream_yolo/geometry/calibration.py`，保存和读取标定数据。
- 新增 `src/bangdream_yolo/geometry/lane.py`，提供屏幕点到 lane 的基础映射。
- 新增 `src/bangdream_yolo/tools/calibrate.py`，从 `nemu_ipc` 截图中交互式选择 4 个关键点。
- 输出 `data/calibration.yml`，供后续检测、跟踪、触控模块共用。
- 更新 README，补充标定流程。

本阶段不做：

- 不接入 YOLO 模型。
- 不实现 note 跟踪与 ETA。
- 不实现自动打歌策略。
- 不做复杂曲面/非线性标定。
- 不做 UI 工具，先用 OpenCV 窗口完成点击选点。

## 技术细节

### 坐标系

本阶段明确两套坐标：

1. **capture 坐标系**
   - 来源：`NemuIpc.screenshot()` 返回的 OpenCV BGR 图像。
   - 预期分辨率：`1280x720`。
   - 原点：左上角。
   - X 向右，Y 向下。

2. **touch 坐标系**
   - 来源：`adb shell wm size` 与 `minitouch`。
   - MuMu 横屏时可能仍返回 `720x1280`。
   - 后续下指前需要从 capture 坐标转换到 touch 坐标。

初版转换规则：

- 若 touch 尺寸是 capture 尺寸的旋转或转置形态（例如 capture `1280x720`、touch `720x1280`），使用可配置映射。
- m2 会保存转换方向字段 `touch_rotation`，初始支持：
  - `none`
  - `clockwise`
  - `counterclockwise`
  - `transpose`
- 旧版默认按 MuMu 推断使用 `counterclockwise` 映射：
  - `touch_x = capture_y`
  - `touch_y = capture_width - capture_x`
- 2026-05-01 实测当前 MuMu 12 使用 `clockwise` 更符合触点位置：
  - `touch_x = capture_height - capture_y`
  - `touch_y = capture_x`
- 若后续实测方向不同，在 `data/calibration.yml` 中改为对应映射。

### 4 点标定

`tools/calibrate.py` 从实时截图中选择 4 个点：

1. `judge_left`：判定线最左端。
2. `judge_right`：判定线最右端。
3. `track_top_left`：远端轨道左边界。
4. `track_top_right`：远端轨道右边界。

操作方式：

- 打开一帧截图。
- 鼠标左键按顺序点击 4 个点。
- 每次点击在图上画点与标签。
- 按 `r` 重置。
- 按 `s` 保存。
- 按 `q` 退出不保存。

### lane 映射

BangDream 为 7 lane。

初版 lane 中心计算：

- 判定线从 `judge_left` 到 `judge_right` 按 7 等分。
- lane 中心位于每段中心：
  - `lane_center_i = judge_left + (i + 0.5) / 7 * (judge_right - judge_left)`
  - `i` 范围：`0..6`

点到 lane 的映射：

- 先基于 4 点构造透视变换，把轨道四边形映射到归一化矩形。
- 归一化 X 落到 `[0, 1]` 后：
  - `lane = floor(x_norm * 7)`
  - clamp 到 `0..6`

判定下指点：

- 对于某个 lane，默认使用判定线上的 lane center。
- 输出 capture 坐标和 touch 坐标，供 `minitouch` 使用。

### 输出文件

保存到：

- `data/calibration.yml`

字段草案：

```yaml
version: 1
capture:
  width: 1280
  height: 720
touch:
  width: 720
  height: 1280
  rotation: counterclockwise
points:
  judge_left: [120, 650]
  judge_right: [1160, 650]
  track_top_left: [500, 260]
  track_top_right: [780, 260]
lanes:
  count: 7
```

注意：

- 上述点位只是示例，不作为默认值。
- `data/calibration.yml` 应提交到 Git，作为本机/默认标定样例；若后续多人协作需要区分机器，可再引入 `data/calibration.local.yml` 并加入 `.gitignore`。

### 验证工具

m2 先只提供基础验证：

- `python -m bangdream_yolo.tools.calibrate`
- 保存后在控制台打印：
  - capture 分辨率
  - touch 分辨率
  - 7 个 lane 判定线中心（capture + touch）

后续 m3/m5 再把 YOLO 框接入 lane 映射验证。

## 验收标准

- `python -m bangdream_yolo.tools.calibrate` 能打开 `nemu_ipc` 截图窗口。
- 能按顺序选择 4 个点并保存 `data/calibration.yml`。
- 保存文件包含 capture/touch 分辨率、旋转方向、4 个点、lane 数。
- 控制台能打印 7 个 lane 的判定线中心坐标。
- 若 MuMu 未启动、截图失败、ADB 无法读取 touch 尺寸，应给出明确错误提示。
- 不引入复杂 UI 框架或额外配置系统。

## 风险与回滚

风险：

- MuMu 的截图坐标和 minitouch 坐标方向可能因窗口/渲染设置而变化。
- 4 点手动点击误差会影响 lane 判断和后续下指位置。
- 1280×720 下远端轨道较窄，远端点需要尽量选在清晰位置。

回滚：

- m2 改动限定在 `geometry/`、`tools/calibrate.py`、`data/calibration.yml` 和 README。
- 若触控方向判断错误，可只修改 `data/calibration.yml` 的 `touch.rotation` 字段。
- 若 4 点透视方案不够稳定，可在后续 REQ 中升级为更多点或固定模板标定。
