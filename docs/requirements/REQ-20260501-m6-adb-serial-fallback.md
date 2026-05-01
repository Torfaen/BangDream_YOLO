# REQ-20260501-m6-adb-serial-fallback

## 背景/目标

m6 真实触控时发现 MuMu ADB serial 会在重启或 ADB server 重新枚举后变化：项目默认 `127.0.0.1:16384` 不在线，但 `adb devices` 中存在可用设备 `emulator-5554`。这会导致 `policy_preview --enable-touch` 在 `adb push minitouch` 阶段失败。

目标是让工具在不改变截图、YOLO、tracker 和 policy 逻辑的前提下，自动选择当前唯一在线的 ADB 设备，减少 MuMu 端口变化造成的中断。

## 范围

本次做：

- 新增 ADB 设备列表解析逻辑。
- 当配置 serial 不在线时，自动回退到 `adb devices` 中唯一 `device` 状态的 serial。
- 在回退时打印提示，便于用户知道实际使用了哪个 serial。
- 接入通用 ADB helper 与 `MinitouchClient`。

本次不做：

- 不修改 MuMu `nemu_ipc` 实例 ID、截图连接方式。
- 不自动连接任意历史端口，例如主动遍历 `127.0.0.1:*`。
- 不在多设备在线时猜测目标设备；这种情况必须由用户设置 `BANGDREAM_ADB_SERIAL`。
- 不改变 minitouch 协议、坐标映射、policy 参数。

## 技术细节

新增逻辑：

```text
resolve_adb_serial(mumu_path, preferred_serial) -> str
```

代码归属：

- ADB 可执行文件查找、`adb devices -l` 解析、serial 自动兜底放在 `src/bangdream_yolo/android.py`。
- `MinitouchClient` 只负责 minitouch 二进制、forward、socket 和文本协议；启动时调用上述 ADB helper 获取实际 serial。
- `check_env`、`fetch_assets`、`test_multitouch` 复用同一套 ADB helper，不各自复制查找逻辑。

规则：

1. 使用 MuMu 自带 adb 或 PATH 中的 adb 执行 `adb devices -l`。
2. 如果 `preferred_serial` 存在且状态为 `device`，直接返回。
3. 否则收集所有状态为 `device` 的在线设备。
4. 如果在线设备只有一个，返回该 serial，并打印：

```text
[adb] configured serial 127.0.0.1:16384 is offline; using emulator-5554
```

5. 如果没有在线设备，报错并输出当前 `adb devices` 内容。
6. 如果多个在线设备，报错提示用户通过 `BANGDREAM_ADB_SERIAL` 指定。

边界：

- `offline`、`unauthorized`、空状态均不视为可用设备。
- 如果用户通过环境变量显式指定 serial，但它不在线，仍允许在只有一个在线设备时兜底；多设备时不猜。
- 解析只依赖 `adb devices -l` 的前两列：`serial status`。

## 验收标准

- 当前只有 `emulator-5554` 在线时，默认配置 `127.0.0.1:16384` 能自动回退到 `emulator-5554`。
- `python -m bangdream_yolo.tools.check_env` 能显示实际可用 serial。
- `python -m bangdream_yolo.tools.test_multitouch --single` 不需要手动设置 `$env:BANGDREAM_ADB_SERIAL` 也能连接当前唯一在线设备。
- `policy_preview --enable-touch` 的 minitouch push 阶段不再因为旧 serial 找不到设备而失败。
- 多设备在线且默认 serial 不在线时，工具明确报错，不随机选择。

## 风险与回滚

风险：

- 如果用户同时开了多个模拟器或手机，自动选择可能存在误操作风险，因此多设备场景必须报错。
- 如果 `adb devices` 输出格式异常，解析可能失败，需要回到手动设置 `BANGDREAM_ADB_SERIAL`。

回滚：

- 代码改动限定在 ADB helper、minitouch 初始化和环境检查展示。
- 回滚后仍可用旧方式：手动设置 `$env:BANGDREAM_ADB_SERIAL="emulator-5554"`。
