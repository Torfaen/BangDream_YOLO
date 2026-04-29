# REQ-20260427-m1-capture-minitouch

## 背景/目标

本阶段对应主计划 `m1_capture` 与 `m1_minitouch`，目标是把项目从环境检查推进到两条基础能力验证：

- 通过 MuMu Player 12 的 `nemu_ipc` 获取实时截图。
- 通过 `minitouch` over ADB 实现多指触控。

这两项是后续 YOLO 推理、note 跟踪和自动打歌闭环的底座。

## 范围

本阶段做：

- 新增 `src/bangdream_yolo/capture/nemu_ipc.py`，封装 MuMu IPC 连接、断开、截图。
- 新增 `src/bangdream_yolo/tools/benchmark_capture.py`，连续截图并统计 FPS / 单帧耗时。
- 新增 `src/bangdream_yolo/input/minitouch.py`，封装 minitouch 启动、ADB forward、socket 协议写入。
- 新增 `src/bangdream_yolo/tools/test_multitouch.py`，验证多指同时点击。
- 更新 README，补充 m1 使用方法与常见问题。

本阶段不做：

- 不接入 YOLO 模型。
- 不做 note 分类、跟踪、ETA 估计。
- 不做 BangDream 判定线、lane 几何标定。
- 不做自动打歌策略。
- 不内置大型二进制或模型权重到 Git 仓库。

## 技术细节

### nemu_ipc 截图

参考 [AzurLaneAutoScript 的 `nemu_ipc.py`](https://github.com/LmeSzinc/AzurLaneAutoScript/blob/master/module/device/method/nemu_ipc.py)，但只裁剪本项目需要的最小逻辑：

- 加载 `external_renderer_ipc.dll`。
- `nemu_connect(nemu_folder, instance_id)` 建立连接。
- `nemu_disconnect(connect_id)` 断开连接。
- `nemu_capture_display(connect_id, display_id, length, width_ptr, height_ptr, pixels_ptr)` 获取画面。

实现约定：

- `nemu_folder` 使用 m0 已确认的 MuMu 安装根目录：`C:\Program Files\Netease\MuMu`。
- DLL 搜索顺序：
  - `shell/sdk/external_renderer_ipc.dll`
  - `nx_device/12.0/shell/sdk/external_renderer_ipc.dll`
- 截图原始数据在当前 MuMu 环境实测为 RGBA 风格的 4 通道数组，且图像上下倒置。
- 对外返回 `np.ndarray`，格式为 OpenCV 常用的 **BGR**。
- 输出前执行：
  - `np.ctypeslib.as_array(...).reshape((height, width, 4))`
  - `cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)`
  - `cv2.flip(image, 0)`
- 本阶段只封装截图，不实现 nemu_ipc 单点触控，因为音游需要多指。

### 截图性能基准

新增工具：

- `python -m bangdream_yolo.tools.benchmark_capture`

默认行为：

- 连接 MuMu。
- 连续截图 `300` 帧。
- 打印：
  - 分辨率
  - 总耗时
  - 平均 FPS
  - 平均单帧耗时
  - 最慢单帧耗时

验收目标：

- 能稳定获取画面。
- 目标 FPS：`>= 60 fps`。
- 若低于目标，先记录结果，不在本阶段做复杂性能优化。

### minitouch 多指输入

本阶段采用 `minitouch` over ADB 作为多指触控方案。

原因：

- `nemu_ipc` 常见公开接口只有单触点 `nemu_input_event_touch_down/up`，不足以覆盖 BangDream 同时多键和长按。
- `minitouch` 支持多 pointer，同帧提交，适合音游输入。

实现约定：

- `third_party/minitouch/` 目录只保留 `.gitkeep`。
- minitouch 二进制不提交 Git，统一通过 `python -m bangdream_yolo.tools.fetch_assets` 下载到本地目录。
- 后续所有不适合入 Git 的外置资源（模型权重、第三方二进制、样例素材等）也统一接入同一个 `fetch_assets` 工具，README 只保留这一种主流程。
- m1 先支持 Windows + MuMu 的 ADB 连接。
- 使用 m0 已确认的 ADB serial：`127.0.0.1:16384`。
- 使用 MuMu 自带 ADB 优先，找不到再使用 PATH 中的 `adb`。

### 外置资源下载入口

新增工具：

- `python -m bangdream_yolo.tools.fetch_assets`

设计约定：

- 使用 Python 标准库下载，不新增额外依赖。
- 默认下载当前项目必需的外置资源：`minitouch`。
- 读取设备 ABI：优先通过 `adb shell getprop ro.product.cpu.abi` 自动判断；失败时允许 `--abi x86_64` 手动指定。
- 资源清单在代码中用简单数据结构维护，包含：资源名、版本、许可证、来源 URL、目标路径、可选 SHA256。
- 下载前检查目标文件是否已存在；默认跳过，支持 `--force` 覆盖。
- 下载后打印保存路径、文件大小与 SHA256，便于排错和复现。

当前 m1 资源：

- `minitouch-prebuilt@1.2.0`
- 来源：[npm minitouch-prebuilt](https://www.npmjs.com/package/minitouch-prebuilt)
- x86_64 URL：`https://cdn.jsdelivr.net/npm/minitouch-prebuilt@1.2.0/prebuilt/x86_64/bin/minitouch`
- 目标路径：`third_party/minitouch/<abi>/minitouch`

minitouch 启动流程：

1. 根据设备 ABI 选择对应 minitouch 二进制。
2. `adb push` 到 `/data/local/tmp/minitouch`。
3. `adb shell chmod 755 /data/local/tmp/minitouch`。
4. `adb shell /data/local/tmp/minitouch` 启动服务。
5. `adb forward tcp:1111 localabstract:minitouch`。
6. 本地 socket 连接 `127.0.0.1:1111`。

minitouch 协议封装：

- `d <pointer_id> <x> <y> <pressure>\n`
- `m <pointer_id> <x> <y> <pressure>\n`
- `u <pointer_id>\n`
- `c\n`

本阶段提供直白函数：

- `down(pointer_id, x, y, pressure=50)`
- `move(pointer_id, x, y, pressure=50)`
- `up(pointer_id)`
- `commit()`
- `tap(pointer_id, x, y, duration=0.03)`

暂不实现复杂 pointer 分配器，留到 `m6_policy`。

### 多指测试

新增工具：

- `python -m bangdream_yolo.tools.test_multitouch`

默认行为：

- 在屏幕中下部构造 5 个点。
- 同一帧发送 5 个 `down`。
- 保持约 `0.5s`。
- 同一帧发送 5 个 `up`。

验收目标：

- MuMu 开启「显示点按操作反馈」后，能看到 5 个点几乎同时按下。
- 脚本退出后触点全部释放。

## 配置项

沿用 `src/bangdream_yolo/config.py`：

- `mumu_path`
- `instance_id`
- `display_id`
- `adb_serial`
- `screen_width`
- `screen_height`

m1 可新增：

- `minitouch_port`，默认 `1111`
- `minitouch_remote_path`，默认 `/data/local/tmp/minitouch`

如需本地覆盖，仍优先使用环境变量，不引入复杂配置系统。

## 验收标准

- `python -m bangdream_yolo.tools.benchmark_capture` 可以成功连接 MuMu 并输出截图 FPS。
- 截图输出维度与 MuMu 分辨率一致，颜色方向正确，无上下颠倒。
- `python -m bangdream_yolo.tools.test_multitouch` 可以完成 5 指同时按下/释放。
- 脚本出错时给出明确提示，例如 DLL 不存在、MuMu 未启动、ADB 未连接、minitouch 二进制不存在。
- 不把录屏帧、权重、minitouch 二进制提交进 Git。

## 风险与回滚

风险：

- MuMu 版本变化导致 `external_renderer_ipc.dll` 接口不可用。
- `nemu_capture_display` 偶发卡死，需要后续加超时线程包装。
- minitouch 二进制 ABI 与模拟器不匹配。
- ADB 设备同时出现 `emulator-5554` 与 `127.0.0.1:16384`，需要固定 serial。

回滚：

- m1 所有改动限定在 `capture/`、`input/`、`tools/` 和 README。
- 若 nemu_ipc 不稳定，可暂时回退到截图模块未启用状态，不影响 m0 环境检查。
- 若 minitouch 不稳定，可保留截图基准能力，后续再切换到 scrcpy-server 控制协议。
