# BMET2922 PPG Monitor

按提供的 Req.1–19 架构实现：ESP32 每 20 ms 采集 PPG 和按钮、独立计算心率，
通过 **Bluetooth Classic SPP** 每 50 个样本发送一个固定长度数据帧；Python 使用
**FreeSimpleGUI 单窗口**显示波形、BPM 趋势、数值、报警、研究视图和 CSV 会话。
这是教学原型，不是临床诊断设备。

## 接线与硬件配置

已按用户提供的接线设置 `firmware/ppg_monitor/config.h`：

| 连接 | 配置 |
|---|---|
| PPG 信号线 | GPIO25 |
| PPG 红线 | 3.3 V / 红色电源轨 |
| PPG 黑线 | GND / 蓝色或负电源轨 |
| 按钮 | GPIO33，按下为 HIGH，内部下拉 |
| LED | GPIO32 |

已确认的硬件与按键配置：

- 已通过 USB 识别连接的芯片为 **ESP32-D0WD，revision v1.0，4 MB Flash**。
- GPIO33 在内部下拉模式下，按住按钮时为 HIGH，松开后为 LOW。
  默认配置因此使用 `INPUT_PULLDOWN`、`BUTTON_ACTIVE_LEVEL=HIGH`，适配按下接通高电平的现有接线。
  如果以后改为按钮另一端接 GND，应同时改为 `INPUT_PULLUP` 和 `BUTTON_ACTIVE_LEVEL=LOW`。

仍需根据实物核对的假设：

- LED 通过合适的限流电阻连接，GPIO32 输出 HIGH 时点亮。
- PPG 脉搏向上为正，`PPG_POLARITY=1`；如果传感器输出相反，改为 `-1`。
- 使用支持 Bluetooth Classic SPP 的原版 ESP32，例如 ESP32-WROOM-32。
  ESP32-S3、C3、S2 不能直接运行这份 SPP 固件。
- GPIO25 使用 ADC2，本项目不开启 Wi-Fi。不要直接把 5 V 信号接入 ADC。

以上引脚、电平、输入模式与极性均可在 `config.h` 修改，也支持 `-D` 编译宏覆盖。
固件将 ADC 设为 12 位；需根据实际传感器确认电压范围和 ADC 衰减配置。

## 启动 Python

使用 Python 3.11 或更新版本，并安装 tkinter。
Windows/macOS 的 python.org 安装包通常包含 tkinter；Linux 可能需要发行版的
`python3-tk` 包。

```sh
cd python_app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m ppg_monitor
```

Windows 激活虚拟环境：`.venv\Scripts\activate`。

当前工作目录已准备好 `.venv`，可直接：

```sh
cd python_app
.venv/bin/python -m ppg_monitor
```

1. 先在操作系统蓝牙设置中配对 **BMET2922-PPG**。
2. 在应用中点 **Refresh ports**，选择配对生成的 SPP 串口；也可以直接输入端口。
   Windows 例如 `COM5`，macOS 例如 `/dev/cu.BMET2922-PPG`，Linux 例如 `/dev/rfcomm0`。
   实际名称由操作系统分配；若系统未创建 SPP 端口，需先完成系统侧串口配置。
3. 点 **Connect**。收到第一个有效数据帧后才显示已连接；仅打开串口不代表蓝牙连接成功。
   连接故障或 5 秒没有有效新包后，会持续每隔 1 秒重试。
   手动点 **Disconnect** 才停止自动重连。
4. Monitor 显示 ESP32 和 Host BPM、原始波形、BPM 趋势、心率报警及通信报警。
   主心率报警使用有效的 ESP32 BPM；Host BPM 是独立的滤波后估计。
5. **Apply limits** 设置上下限，默认 50.0 / 120.0 BPM，可按实验目的调整并在报告中说明。
6. **Start recording** 或硬件按钮控制录制；Sessions / CSV 可选择并导出任一录制会话。

不接硬件也能检查界面：

```sh
python -m ppg_monitor --demo
```

此模式明确显示 **SIMULATED DATA**，生成 72.4 BPM 合成数据，经过同一个二进制协议、
解析器、处理器、报警和录制流程；它不能证明真实采样或蓝牙性能。
`--port COM5` 可自动连接指定端口，`--duration 30` 可在 30 秒后关闭以做启动测试。
窗口右上角可以随时切换 **English / 中文**，不会重置连接、录制、阈值或已有数据。
也可以用 `--language zh` 直接以中文启动；课程要求的英文日志与 CSV 字段名称保持稳定。

## 编译 ESP32

Arduino IDE：安装 Espressif 的 **esp32** 开发板包，打开
`firmware/ppg_monitor/ppg_monitor.ino`，选择与实物一致的原版 ESP32 开发板和 USB 端口。
`BluetoothSerial` 随 ESP32 平台提供，不需要安装 NimBLE。

命令行例子（`esp32:esp32:esp32` 表示通用 ESP32 Dev Module，需与实物核对）：

```sh
arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@3.3.12 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/ppg_monitor
arduino-cli upload --fqbn esp32:esp32:esp32 --port YOUR_USB_PORT firmware/ppg_monitor
```

**必须同时更新固件和 Python**：本版是 SPP 协议 v2，与之前 BLE 协议 v1 不兼容。
旧版本使用的 bleak、PySide6、pyqtgraph 和 BLE 服务 UUID 已移除。
已在官方 ESP32 Arduino **3.3.12**、通用 ESP32 Dev Module 目标编译通过。
该平台提示 BluetoothSerial 在未来 4.0 中默认支持会变化，因此复现时使用这里指定的 3.3.12。

串口监视器 / Serial Plotter 使用 **115200 baud**。
默认输出 `ppg`、`threshold`、`button`、`bpm`、`recording`。
调试时间间隔时，可在编译参数中添加 `-DSERIAL_CSV`，输出时间戳和各字段。
USB 调试串口只输出文本，Python 正式接收应选择 **SPP 端口**。

## 模块与行为

| 文件 | 职责 |
|---|---|
| `firmware/ppg_monitor/config.h` | GPIO、按钮/LED 电平、20 ms 周期、设备名 |
| `firmware/ppg_monitor/button.h` | 5 个连续相同样本才确认按钮变化，按下只触发一次 |
| `firmware/ppg_monitor/bpm.h` | 自适应基线/阈值、峰值、回落再武装、300 ms 不应期、IBI 均值 |
| `firmware/ppg_monitor/packet.h` | 固定 117 字节帧，显式小端序，CRC |
| `firmware/ppg_monitor/ppg_monitor.ino` | 采样、SPP 发送任务、控制命令、LED、Serial Plotter |
| `python_app/ppg_monitor/communication.py` | 后台串口线程、收包看门狗、持续重连、主线程事件队列 |
| `python_app/ppg_monitor/protocol.py` | 帧编解码、串口字节流同步、32 位序号检查 |
| `python_app/ppg_monitor/signal_processing.py` | 有状态实时滤波、独立 Host BPM、FFT、信号质量 |
| `python_app/ppg_monitor/alarms.py` | 高/低心率与独立的 5 秒通信报警 |
| `python_app/ppg_monitor/logger.py` | 规定格式的事件日志及文件保存 |
| `python_app/ppg_monitor/controller.py` | 连接、分析、报警、录制和趋势的统一状态 |
| `python_app/ppg_monitor/gui.py` | FreeSimpleGUI 的一个主窗口，Monitor/Researcher/Sessions 页签 |
| `python_app/ppg_monitor/recorder.py` | 每样本 CSV 和有效 Host BPM 统计 |
| `python_app/ppg_monitor/demo.py` | 明确标注的模拟输入 |

采样用 `micros()` 截止时间，正常每 20 ms 读取一次 ADC 与按钮。
循环仅 `delay(1)` 让出 CPU；不使用 `delay(20)` 驱动采样。若错过完整采样周期，
跳过过期时刻、置 `TIMING_GAP` 并重置嵌入式检测器，避免补采一串伪等间隔数据。
SPP 写操作在独立 FreeRTOS 任务中；有界队列满时保留最新帧，序号缺口会暴露丢包。
USB 串口输出空间不足时跳过该条调试输出，避免阻塞 ADC 采集。

LED：SPP 已连接时，常亮表示录制、熄灭表示未录制；无 SPP 客户端时每秒短闪一次。
按钮在启动后也需要五个真实读数确认，按住不会反复切换录制。

Host 使用三阶 **0.5–4 Hz Butterworth SOS 带通**，保留滤波器状态，只处理新到的 50 点。
12 秒窗口用于峰值和 Hann FFT。0.5 Hz 下限抑制慢基线漂移；4 Hz 上限保留脉搏频带，
高于检测器的 200 BPM 上限（约 3.33 Hz）。这些是原型设计参数，需用实际数据论证。
Host BPM 至少需要 5 秒信号、两个有效 IBI、足够幅度、低削顶比例及稳定间期；
FFT BPM 只有在质量 GOOD 且与峰值法一致时显示。该预热不阻止原始波形和 ESP32 BPM 更新。
断线、丢包、时间戳不连续、无接触或采样异常都会重建分析窗口。

GUI 每 50 ms 处理事件，有新包时更新曲线；串口打开、读写和重连均在后台。
重复/乱序帧与损坏帧不重置“有效新包”计时器。通信报警在 5 秒触发，收到有效新包即恢复。
重连是每隔 1 秒持续尝试，实际恢复速度还依赖 OS 配对、驱动和设备，需做 ≤10 秒真机验收。
界面显示的 Host processing 时间只代表计算耗时，不能作为 <2 秒端到端延迟证明。

## 固定长度 SPP 协议 v2

每帧 **117 字节**，全部多字节整数为 little-endian。正常每 50 点（1 秒）产生一帧。
帧采用逐字段编码，不直接发送 C++ struct，避免对齐/填充差异。

| Offset | Bytes | 内容 |
|---:|---:|---|
| 0 | 2 | ASCII `PP` |
| 2 | 1 | 版本 `2` |
| 3 | 4 | uint32 序号，自然回绕 |
| 7 | 4 | 首样本 `millis()` 时间戳，uint32 |
| 11 | 2 | ESP32 BPM × 10，例如 72.4 → 724；`0xFFFF` 表示无有效值 |
| 13 | 1 | 状态位 |
| 14 | 1 | 样本数 `50` |
| 15 | 100 | 50 个 uint16 ADC 样本 |
| 115 | 2 | 前 115 字节的 CRC-16/CCITT，初值 `0xFFFF`，多项式 `0x1021` |

状态位：bit 0 录制、bit 1 BPM 有效、bit 2 按钮按下、bit 3 检测到脉搏幅度、bit 4 采样间隔异常。
控制命令沿反方向写入 SPP：`01 01` 开始录制，`01 00` 停止录制。
主机支持任意分段、粘包、半帧、噪声与 CRC 失败后的重新同步。

## 日志与 CSV

GUI 日志与 `data/logs/system_*.log` 使用以下格式（本地时间，固定英文星期/月）：

```text
Thu Sep 19 17:46:50 2024: Pulse Low
```

只记录状态变化和错误，不逐包记录正常数据。包括 Bluetooth Connected/Lost/Reconnected、
Pulse High/Low/Normal、Communication Lost/Restored、Recording Started/Stopped。

CSV 使用标准库 `csv`，Excel 可打开，无需另装 pandas 或生成 xlsx。
字段包括 UTC 接收时间、序号、设备采样时间、样本索引、raw/filtered PPG、ESP32/Host/FFT BPM、
信号质量、状态位、录制状态、心率报警、时长、平均/最小/最大有效 Host BPM。

- 每个录制帧输出 50 行；未录制帧不加入。
- 统计只包含质量 GOOD 且有限的 Host BPM；每个一秒帧算一次有效心率测量。
- 已停止的会话保留在 Sessions 选择器中，重连后新录制不会覆盖旧会话。
- CSV 要主动导出；关闭应用会释放尚未导出的内存会话。
- 录制状态在每帧结束时取值，启停边界约有一秒粒度。
- `TIMING_GAP` 帧中的逐样本时间按 20 ms 估算；必须结合标志识别其并非精确采集时刻。

## Req.1–19 验收对应

“已实现”表示代码路径存在并完成可执行的软件验证，不能代替真机测量。

| Req | 对应实现 | 验证方式 |
|---:|---|---|
| 1 | ADC 和按钮每 20 ms 截止时间采样 | `SERIAL_CSV` / 逻辑分析仪测周期（需真机） |
| 2 | ESP32 自适应阈值 + IBI 心率 | 固件编译；与参考脉搏源比较（需真机） |
| 3 | debounce count = 5 | `button.h`；抖动/按住/启动按下实验 |
| 4 | Serial Plotter 同时输出 raw 和 threshold | 上传后观察两条曲线 |
| 5 | 按键切换录制，LED 显示录制/断连 | 实物验证 |
| 6 | 一个 FreeSimpleGUI 主窗口 | 实际启动测试 |
| 7 | PPG 波形与 ESP32/Host BPM 趋势 | GUI 渲染测试、模拟演示 |
| 8 | 50 ms 事件循环，每个新包更新 | GUI / 后台线程测试，真机检查刷新 |
| 9 | 36 pt 大号 ESP32 和 Host BPM | GUI 测试 |
| 10 | BPM 文本恰好一位小数 | `format_bpm` 与 GUI 测试 |
| 11 | 可调整上下限，独立 HIGH/LOW 视觉报警 | 边界、阈值变化、事件去重测试 |
| 12 | 后台收包 + 一秒帧 + GUI 及时更新 | **<2 s 须真机端到端测量** |
| 13 | 固定英文时间格式与事件日志 | 示例精确比对、磁盘写入测试 |
| 14 | 5 秒无有效新包报警，恢复即清除 | 4.999 / 5.000 s 边界及坏包测试 |
| 15 | ESP32 BluetoothSerial + pySerial SPP | 固件编译；配对/端口/无线收发需真机 |
| 16 | 持续自动重试直到手动停止 | 连续失败、主动断开、恢复测试 |
| 17 | 1 秒重试间隔 | 模拟设备恢复测试；**≤10 s 须真机测量** |
| 18 | 117 字节：BPM×10、50 samples、uint32 seq、CRC | 字节序、任意切分、丢包/乱序/回绕测试 |
| 19 | 有状态 0.5–4 Hz 带通，过滤低频漂移 | 合成脉搏、漂移抑制和滤波连续性测试 |

运行软件测试：

```sh
cd python_app
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

测试使用模拟串口和无显示器 GUI 替身；另运行实际桌面演示测试：

```sh
.venv/bin/python -m ppg_monitor --demo --duration 30
```

本次验证结果（2026-10-08）：49 项软件测试全部通过，无跳过；`pip check` 通过。
英文 30 秒与中文 12 秒的原生 FreeSimpleGUI 演示均正常退出。
ESP32 Arduino 3.3.12、`esp32:esp32:esp32` 目标的普通输出与 `SERIAL_CSV`
两种配置都编译成功，程序约占 81% Flash、全局变量约占 12% RAM。
上述 2026-10-08 验证没有上传固件或连接实物；软件测试中的重连恢复时间来自模拟串口，不能作为无线实测结果。

2026-10-11 真机测试进度：已备份原固件，烧录并校验 PPG 的 `SERIAL_CSV` 版本。
两段采样记录中连续时间戳间隔均为 20 ms；这仅证明这两段 USB 调试记录的设备时间戳，
尚未验证蓝牙通信时的采样和端到端延迟。用户确认未连接蓝牙时 LED 闪烁。
手指测试有 55/1082 个样本达到 ADC 上限，Host 判断信号质量差，心率稳定性尚未通过。
GPIO33 上拉/下拉诊断确认现有按钮按下为高电平，已修正默认配置并重新烧录校验。
复测记录到 0.44 秒和 3.04 秒两次按下，录制恰好切换两次，松开及持续按住均未重复触发。
这验证了本次短按/按住行为，不能单独证明消抖窗口恰好为五个采样点。
本轮 USB 调试记录的启动阶段另有一次 40 ms 时间戳间隔，尚未区分调试输出丢行与实际采样延迟；
SPP 首次连接收到了 15 个连续、CRC 有效的数据帧，每帧 50 点，设备帧时间戳间隔均为 1000 ms，
主机收包间隔为 0.982–1.020 秒，未出现 `TIMING_GAP` 标志。
随后 macOS 虚拟 SPP 串口重新打开却没有数据，系统仍显示设备未连接，GUI 触发通信报警。
已修正软件状态：收到有效新帧才报告已连接，避免把打开串口误报为连接成功；新增回归测试后共 51 项通过。
单独使用 macOS 原生 RFCOMM 的诊断程序三次打开均收到了数据，但该接口尚未集成到应用中，
不能视为应用自动重连已通过。用户选择暂时跳过蓝牙测试，继续模拟模式的软件录制与 CSV 验证。
连接后 LED 录制指示、蓝牙负载下的逐点采样时序、应用自动重连和端到端延迟仍待实物验收。

2026-10-11 模拟模式的桌面 GUI 验证：录制并导出 20 秒模拟信号，共 1000 行采样数据、
20 个连续数据帧、17 列字段。每帧 50 点，设备时间戳逐点增加 20 ms，录制标志、滤波结果及
会话统计均通过导出文件检查。模拟源为 72.4 BPM，本段 Host 平均估计为 73.17 BPM，不能作为真实心率精度结论。
用户逐项确认高心率报警、恢复正常、低心率报警、再次恢复正常；事件日志分别记录
`Pulse High`、`Pulse Normal`、`Pulse Low`、`Pulse Normal`。
用户确认研究分析页面显示滤波波形和 FFT，以及中英文切换正常；切换期间数据序号继续递增。
另在真实桌面 GUI 中暂停模拟数据 7 秒：距最后一个包约 5.037 秒触发通信报警，旧心率显示清空；
事件循环持续运行，收到恢复后的第一个包即解除报警，日志各记录一次 Lost / Restored。
恢复后重新收集信号，质量回到 GOOD；这里的暂停与恢复由模拟源控制，不证明无线重连或端到端延迟。
这些结果验证桌面软件的模拟流程，不替代 ESP32 无线通信、真实信号质量或硬件显示扩展验收。

2026-10-11 16:14 的第二轮手指实测：USB 保存 1581 点，设备时间跨度 31.62 秒。
其中 722 点（45.67%）达到或接近 ADC 上限，Host 的 31 个分析块中 30 个为 POOR、1 个为 NO SIGNAL，
未产生有效 Host BPM。ESP32 仍会输出 BPM 估计，但尚未与参考值对比，不能认定准确。
时间戳包含 1579 次 20 ms 间隔和 1 次 40 ms 间隔；该文件无法区分 USB 文本丢行与实际采样漏点。
本轮原始数据和分析保存在本地 `data/recordings/`，未推送个人测量数据。

## 按用户模块清单核对（2026-10-11）

当前结论：核心代码路径均存在，整机尚未全部验收。再次运行 51 项软件测试全部通过，
`pip check` 未发现依赖冲突。下表的模拟通过、短时实测和整机通过不可混用。

| 模块 | 当前状态与证据 | 剩余验收 |
|---|---|---|
| ESP32 sampling | PPG 和按钮同一次 20 ms 调度读取；实测绝大多数 USB 时间戳间隔为 20 ms | 解释 40 ms 记录间隔，测无线负载下两路采样时序及抖动 |
| ESP32 BPM | ESP32 独立计算并放入每帧；首次 SPP 已接收到 BPM 字段 | 解决真实信号削顶、验证检测稳定性并与参考值比较 |
| Button | 代码接受连续 5 个相同样本；实际短按和持续按住各只切换一次录制 | 补测原始按键抖动到确认状态的采样计数 |
| LED | 明确区分断连闪烁、已连接录制亮灯、已连接未录制熄灭；断连闪烁已确认 | 实测连接后的两种录制状态 |
| Serial Plotter | 默认输出带标签的 raw 和 threshold；CSV 诊断输出也含两字段 | 在 Arduino Serial Plotter 中确认两条曲线；当前板子烧录的是 CSV 诊断构建 |
| Bluetooth | 使用 Classic SPP；首次成功接收 15 帧 | macOS 虚拟串口重新打开无数据，稳定连接尚未通过 |
| Packet | 固定 117 字节，BPM、50 点 raw、uint32 序号和 CRC；15 帧序号连续、设备帧间隔 1000 ms | 补做更长时间及异常恢复后的真机收包检查 |
| Reconnect | 后台持续重试逻辑及模拟测试通过 | 真机重新打开无数据的故障未修复，设备恢复后不超过 10 秒的要求未通过 |
| GUI | 一个 FreeSimpleGUI 主窗口；实际桌面启动和中英文切换通过 | 无线连接整机运行验收 |
| PPG display | 模拟输入的实时波形显示已确认；真实 USB 波形已离线绘图 | 真实传感器经 SPP 到 GUI 的连续实时显示 |
| BPM display | 趋势图、36 pt 大号数值及一位小数显示通过 | 真实 BPM 准确性与链路验收 |
| Alarm | 模拟输入触发 HIGH、LOW，并均恢复 NORMAL；日志和用户观察吻合 | 配合稳定真实信号检查整机行为 |
| Latency | 接收在后台，GUI 使用 50 ms 事件轮询 | 实际事件到 GUI 小于 2 秒尚未实测，处理耗时不等于端到端延迟 |
| System log | 英文星期/月及规定时间格式通过精确比对、文件记录与桌面检查 | 无 |
| Packet-loss alarm | 单元边界测试通过；桌面模拟暂停后约 5.037 秒报警，首个恢复包解除 | 真机断流到恢复的完整路径 |
| Signal processing | 有状态 0.5–4 Hz 带通，低频漂移抑制及滤波连续性测试通过 | 真实信号质量当前不合格，滤波不能恢复已经削顶的信息 |
| Data recording | start/stop 和 CSV 实际 GUI 导出通过，20 秒模拟数据为 1000 点、17 列 | 真实蓝牙录制、掉线后会话保留及恢复录制的整机验证 |
| Extra feature | Researcher 含滤波波形、FFT、主频、质量说明；模拟显示已确认 | 稳定真实信号上的演示与运行验收；此前另行要求的 OLED/LCD、双击/长按尚未实现 |

真机验收至少完成：正常 20 ms 间隔、五样本消抖、LED/录制、Serial Plotter、参考 BPM、
人为干扰后的质量变化、5 秒报警、断连后持续重连、设备恢复 ≤10 秒、真实变化到 GUI <2 秒、
停止/重启录制与 CSV 行数。未拿到实物测量前，不应在报告里把这三项时序指标写成实测通过。

本次范围包含核心 19 条、研究/记录功能，以及中英文界面切换。
用户已要求继续实现 OLED/LCD 和多功能按键；这两项仍等待显示器型号/接口/接线与双击、
长按行为定义，尚未实现，不应在验收表中标为完成。3D 外壳需要另行提供机械设计约束。
团队应在最终报告中填写真实贡献者姓名，代码不虚构作者。

## 官方接口参考

- [Espressif BluetoothSerial / SPP](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/bluetooth.html)
- [FreeSimpleGUI API](https://freesimplegui.readthedocs.io/en/stable/call%20reference/)
- [pySerial 读写超时与串口 API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html)
- [SciPy sosfilt](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfilt.html)
