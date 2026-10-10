"""English/Chinese UI; course-format logs and CSV field names stay stable."""
LANGUAGES = ("English", "中文")
ZH = {
    "BMET2922 / PPG Monitor": "BMET2922 / PPG 心率监测",
    "ESP32 BPM": "ESP32 心率", "Host BPM": "电脑端心率", "Signal quality": "信号质量",
    "Raw PPG · ADC counts": "原始 PPG 波形 · ADC 读数",
    "BPM trend · ESP32 (green) / Host (orange)": "心率趋势 · ESP32（绿色）/ 电脑端（橙色）",
    "Low BPM": "心率下限", "High BPM": "心率上限", "Apply limits": "应用阈值",
    "Start recording": "开始录制", "Stop recording": "停止录制",
    "Stateful Butterworth band-pass · 0.5–4 Hz · 50 Hz sampling": "实时 Butterworth 带通 · 0.5–4 Hz · 50 Hz 采样",
    "Hann-window FFT · frequency (Hz)": "Hann 窗 FFT · 频率（Hz）",
    "Dominant pulse frequency: --": "脉搏主频：--", "Waiting for data": "等待数据",
    "Recording": "录制会话", "Session {number}": "会话 {number}",
    "CSV destination": "CSV 保存位置", "Browse": "浏览", "Save CSV": "保存 CSV",
    "Stopped sessions are retained here until the app closes. Save each session before exiting.": "已停止的会话会保留到应用关闭。退出前请保存需要的会话。",
    "SIMULATED DATA": "模拟数据", "SIMULATED": "模拟模式", "Bluetooth Classic SPP": "经典蓝牙 SPP",
    "SPP serial port": "SPP 串口", "Refresh ports": "刷新串口", "Connect": "连接", "Disconnect": "断开",
    "Pair BMET2922-PPG in OS Bluetooth settings first.": "请先在系统蓝牙设置中配对 BMET2922-PPG。",
    "Monitor": "实时监测", "Researcher": "研究分析", "Sessions / CSV": "会话 / CSV", "System log": "系统日志",
    "Educational prototype · local times in log / UTC in CSV": "教学原型 · 日志为本地时间 / CSV 为 UTC · 日志保留课程规定英文格式",
    "DISCONNECTED": "未连接", "CONNECTING": "连接中", "CONNECTED": "已连接", "RECONNECTING": "重连中",
    "GOOD": "良好", "POOR": "较差", "NO SIGNAL": "无信号",
    "NORMAL": "正常", "HIGH": "偏高", "LOW": "偏低", "UNAVAILABLE": "暂无有效值",
    "Pulse: {state}": "心率：{state}", "Communication: {state}": "通信：{state}",
    "ALARM — no packet for 5 s": "报警 — 5 秒未收到数据", "OK": "正常", "WAITING": "等待数据", "IDLE": "未启动",
    "Waiting for fresh samples": "等待新的采样数据", "Host processing: {ms:.1f} ms": "电脑端处理：{ms:.1f} ms",
    "Dominant pulse: {hz:.2f} Hz / {bpm:.1f} BPM": "脉搏主频：{hz:.2f} Hz / {bpm:.1f} BPM",
    "Time (s)": "时间（s）", "Frequency (Hz)": "频率（Hz）",
    "Duration": "时长", "Average valid host BPM": "平均有效电脑端心率",
    "Minimum valid host BPM": "最低有效电脑端心率", "Maximum valid host BPM": "最高有效电脑端心率",
    "Valid measurements": "有效测量数", "Samples": "采样点数",
    "No usable pulse variation detected": "未检测到可用的脉搏变化",
    "Sampling timing gap; rebuilding a uniform-rate analysis window": "采样时间间隔异常，正在重建分析窗口",
    "Signal is clipped at the ADC input range": "信号达到 ADC 边界，发生削顶",
    "Collecting at least 5 seconds of signal": "正在收集至少 5 秒的信号",
    "Filtered pulse amplitude is too small": "滤波后脉搏幅度过小", "Too few reliable beat intervals": "可靠的心搏间期不足",
    "Beat intervals are unstable": "心搏间期不稳定", "Pulse intervals are stable": "心搏间期稳定",
    "Log file could not be written: {error}": "日志文件写入失败：{error}",
}


def translate(message: str, language="English", **values) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    return (ZH.get(message, message) if language == "中文" else message).format(**values)
