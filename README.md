**本项目没有参考任何开源项目，包括硬件实现、3D打印建模、软件实现。仅在作品构思阶段参考了一些现有成品的原理及作者反馈的问题。**

# 超声参量阵定向音响

> 文档版本：v5.2（2026-09-26）
> 当前实施基线：120 个换能器、12 路 TC4428 功率驱动、GPIO4 单相位扇出、二维机械云台和电脑视觉控制。

本项目将可听音频调制到 40 kHz 超声载波，通过 120 阵元同相发射获得窄声束，并由视觉跟踪和二维云台改变指向。当前版本不做电子相位转向或逐阵元聚焦。

```text
摄像头 → YOLO 人体检测 / ByteTrack 跟踪 → PI 控制 → 二维云台
音源   → 电脑端 DSP → 8 kHz PCM → ESP32 调制 → GPIO4
GPIO4  → SN74HC125 扇出 12 路 → 12 片 TC4428 → 120 个 TCT40-16T
```
## 0.原创性说明

本项目没有参考任何开源项目，包括硬件实现、3D打印建模、软件实现。仅在作品构思阶段参考了一些现有成品的原理及作者反馈的问题。

## 1. 项目入口点

| 入口 | 文件 | 用途 |
|---|---|---|
| 桌面端主程序 | `src/vision_gimbal/__main__.py` | PySide6 UI、人体跟踪、云台、实时音频和声场显示 |
| 桌面端组合根 | `src/vision_gimbal/bootstrap.py` | 组装摄像头、YOLO、控制、串口、音频和 UI |
| 主配置 | `configs/vision_gimbal.toml` | 摄像头、模型、云台、串口、音频与可选声场参数 |
| ESP32 正式固件 | `src/full_size/full_size.ino` | 120 阵元单 GPIO 调制、二维舵机、Flash/实时音频和二进制协议 |
| 独立音频测试 | `utils/mic_stream_cli.py` | 不启动视觉和 UI，单独测试麦克风/电脑音频串流 |
| 文件串流诊断 | `utils/audio_stream_probe.py` | 把内置 PCM 原字节发给 ESP32，排查传输与调制问题 |
| Flash 音频转换 | `utils/wav_to_audio_header.py` | 把 PCM WAV 转为固件的 `audio_data.h` |
| 离线声学校准 | `utils/audio_calibration/calibrate.py` | 生成实验 PCM、拟合固定非线性模型、评估和预失真；不启动 Qt 或串口 |
| 单音录音试训 | `utils/audio_calibration/tone_pilot.py` | 对无配对输入的单音 WAV 拟合录音谐波轮廓；详见 `docs/16-单音录音试训.md` |
| 手机录音带通诊断 | `utils/audio_calibration/bandpass_wav.py` | 离线保留 250–3000 Hz，输出滤波 WAV 与频带电平报告；见 `docs/16-手机录音带通诊断.md` |

正式桌面端使用 `python -m vision_gimbal`。`src/cv_test_deprecated` 和 `src/esp32_s3_4x3_min_test_deprecated` 只是历史实现，不是当前入口。

## 2. 运行环境

电脑端建议使用：

- Windows 10/11；“静音无关回环”音源使用 Windows WASAPI；
- Python 3.11，项目支持 Python 3.10～3.12；
- [uv](https://docs.astral.sh/uv/)；
- UVC USB 摄像头；
- 连接硬件时需要 ESP32-S3 的 COM 口。

从仓库根目录同步锁定依赖：

```powershell
uv sync --locked --python 3.11
```

这会同时安装测试依赖。默认为 CPU 推理，并关闭可选的深度/声场分析。

### 可选推理后端

NVIDIA CUDA：

```powershell
uv sync --locked --python 3.11 --extra cuda
```

Intel XPU：

```powershell
uv sync --locked --python 3.11 --extra xpu
```

`cuda` 和 `xpu` 互斥，不能同时安装。`uv sync` 会以本次命令指定的 extra 同步环境，以后重新同步时应重复写出仍需要的 extra。

## 3. 启动桌面端

### 3.1 只运行视觉和云台仿真

在 PowerShell 中从仓库根目录执行：

```powershell
$env:PYTHONPATH = ".\src"
uv run python -m vision_gimbal --camera-index 0
```

这种方式不打开串口，但会运行摄像头、人体检测、目标选择和控制计算。如果第一个摄像头不是索引 `0`，修改 `--camera-index`。

### 3.2 连接 ESP32 完整启动

先烧录第 5 节的正式固件，然后确认 Windows 设备管理器中的 COM 口。例如 ESP32 是 `COM5`：

```powershell
$env:PYTHONPATH = ".\src"
uv run python -m vision_gimbal --camera-index 0 --serial-port COM5
```

可选的命令行覆盖：

```text
--config PATH       指定 TOML 配置
--serial-port COM5  指定 ESP32 串口
--baudrate 460800   覆盖串口波特率
--camera-index 0    覆盖摄像头索引
--device cpu        覆盖 YOLO 推理设备，也可使用 cuda:0 或 xpu:0
```

程序启动后：

1. 在追踪画面中单击人体框；
2. 单击“开始追踪”才会进入自动云台闭环；
3. 停止追踪时可用 `W/A/S/D` 手动控制；
4. 串口连接后选择音源，再单击“开始音频链路”。

### 连续调节音量

先烧录本仓库最新的 `src/full_size/full_size.ino` 固件，再启动桌面程序。串口连接并完成协议握手后，“音频与超声阵列”面板中的“主音量”滑块会启用；拖动它可在播放中调节麦克风、立体声混音或电脑声音，音频链路不会重启。默认音量为 50%，可在 `configs/vision_gimbal.toml` 的 `[audio.volume] default_percent` 修改。

0% 会在短暂渐变后关闭 GPIO4 超声 PWM；100% 等于原有最大音频调制幅度。滑块只衰减音频，不改变固定载波和测试纯音命令。界面的频谱与可选录音仍显示音量调节前的输入音频。若面板提示“固件需更新”，请先烧录新固件；旧固件的音频启动会被禁止，以免设定音量未生效。

不用桌面程序时，可在 460800 波特率串口监视器中发送 `V30` 后按回车，把内置 Flash 音频设为 30%；再发送 `P` 播放一次或 `L` 循环播放。`V0` 为音量静音，`V100` 恢复原有幅度，播放过程中也可调整。此命令仅在没有桌面端二进制协议会话时使用。音量静音不等于断开 12 V 电源。

默认音源是“电脑声音（静音无关回环）”。helper 不存在或其源码更新后，程序会自动调用 `utils/build_wasapi_process_loopback.ps1`，需要 MinGW-w64 `g++` 已在 `PATH` 中。也可提前编译：

```powershell
.\utils\build_wasapi_process_loopback.ps1
```

运行期间若 Windows 音频资源重配、helper 异常退出或 PCM 管道卡住，程序会自动重建回环采集和设备音频流；真实数字静音仍按活动门限关闭阵列 PWM。

不需要 WASAPI 进程回环时，可在 UI 中改选“麦克风”或“立体声混音”。用下列命令查看 PortAudio 设备名称：

```powershell
uv run python -m sounddevice
```

### 人物再次出现时的编号

视觉流水线会为合格的人体检测框提取服饰颜色特征，并在本次运行期间维护人物编号。新轨迹会立即抽样，最多取四次合格特征确定编号；已编号的轨迹默认每 1 秒再抽样一次，Kalman 预测框不会抽样。与历史人物连续两次匹配后，新轨迹会复用原编号。身份库默认保留离开画面人物 120 秒，程序关闭后清空。

这一路径只使用 CPU 和现有 OpenCV，不需要下载模型。它主要适用于同一摄像头、同一场次且衣着未变的情况；相似衣着、强遮挡或换装时可能认错或无法认回。人物未取得可靠特征前，框上显示 `ID ?`，不能选为自动追踪目标。目标丢失超过 0.8 秒后仍会停止自动追踪；人物被再次认出时可直接点击“开始追踪”，不会自行重启云台。参数在 `configs/vision_gimbal.toml` 的 `[vision.appearance]` 中调整。

## 4. 可选的深度与声场显示

此功能只做低频率可视化，不向云台、音频或 ESP32 发送指令。默认关闭。

1. 安装 OpenVINO 可选依赖：

   ```powershell
   uv sync --locked --python 3.11 --extra spatial
   ```

2. 确认模型目录 `models/yolo26n-depth_openvino_model` 存在。
3. 在 `configs/vision_gimbal.toml` 中设置：

   ```toml
   [spatial_field]
   enabled = true

   [spatial_field.depth]
   device = "intel:gpu"
   ```

如果需要同时使用 Intel XPU 跑人体跟踪，同步时同时传入两个 extra：

```powershell
uv sync --locked --python 3.11 --extra xpu --extra spatial
```

要在 CPU 上运行声场分析，还需将 `device` 改为 `cpu`，并设置 `allow_cpu_fallback = true`。

## 5. 编译和启动 ESP32 正式固件

仓库当前的唯一正式烧录入口是：

```text
src/full_size/full_size.ino
```

当前已验证的环境为 Arduino-ESP32 3.3.10。Arduino IDE 设置：

| 选项 | 值 |
|---|---|
| Board | `ESP32S3 Dev Module` |
| Upload Speed | `115200` |
| Flash Size | `16MB` |
| PSRAM | `8MB OPI`，以实际 ESP32-S3-WROOM-1-N16R8 菜单为准 |
| USB CDC On Boot | `Disabled`（当前 CH340X 链路） |
| 串口监视器 | `460800` baud |

打开 `.ino` 后编译并上传。上电后固件会把云台指令设为逻辑 `(0,0)`，但超声 PWM 保持关闭。在不连接桌面端时，可在串口监视器发送：

```text
A            连续固定载波
T            1 kHz 包络测试
P / L        播放一次 / 循环播放 Flash 音频
0 + 回车     停止 GPIO4 切换
H            显示完整帮助
```

详细命令、烧录和首次上电步骤见 [`src/full_size/README.md`](src/full_size/README.md)；120 阵元接线以 [`docs/09-当前120阵元单GPIO接线.md`](docs/09-当前120阵元单GPIO接线.md) 为准。

## 6. 独立诊断与音频工具

只测试麦克风到 ESP32 的音频链：

```powershell
$env:PYTHONPATH = ".\src"
uv run python .\utils\mic_stream_cli.py --serial-port COM5
```

使用当前 Flash PCM 测试串口传输：

```powershell
uv run python .\utils\audio_stream_probe.py --inspect-only
uv run python .\utils\audio_stream_probe.py --serial-port COM5 --processing raw --drive standard
```

把 PCM WAV 更换为固件内置音频：

```powershell
uv run python .\utils\wav_to_audio_header.py `
  .\input.wav `
  .\src\full_size\src\data\audio_data.h
```

生成后需要重新编译和烧录 ESP32。

## 7. 测试

从仓库根目录执行：

```powershell
uv sync --locked --python 3.11
uv run python -m pytest -q
uv run python -m compileall -q src utils
```

pytest 只收集 `tests/`，不会运行两个 `_deprecated` 历史目录。

## 8. 当前文档

- [原理、公式与能力边界](docs/01-原理与公式.md)
- [120 阵元整机与硬件实施](docs/02-系统方案与硬件.md)
- [当前软件架构与接口](docs/03-软件架构.md)
- [参考资料与证据边界](docs/04-开源参考.md)
- [实施计划与分工](docs/05-计划与分工.md)
- [采购、备件与到货验收](docs/06-采购清单.md)
- [版本验收、风险与演示](docs/07-版本阶梯与风险.md)
- [历史 12 阵元原型](docs/08-当前12阵元原型.md)
- [120 阵元单 GPIO 接线](docs/09-当前120阵元单GPIO接线.md)
- [当前项目完整数据流](docs/10-当前项目完整数据流.md)
- [视觉云台跟踪系统](docs/11-视觉云台跟踪系统.md)
- [实时音源与音频流协议](docs/12-实时麦克风与音频流协议.md)
- [实时音频传输排查](docs/13-实时音频传输排查.md)
- [连续音量控制设计与实现](docs/连续音量控制设计提案.md)

`docs/01`～`docs/07` 已按当前 120 阵元机械转向基线重写；`docs/08` 是历史 12 阵元台架记录。任何电子相控研究都必须单独标记为未来方案，不得覆盖当前施工文档。

## 9. 安全边界

- 任何改线、插拔芯片或连接示波器之前，必须物理断开 12 V 功率电源。
- 串口 `0`、关闭音频链路或停止追踪都不等于物理急停。
- MG996R 舵机使用独立 5～6 V 大电流电源，与 ESP32 共地；不得从 ESP32 3.3 V 引脚供电。
- 不要把耳朵靠近阵面，不要用手机分贝 App 判断 40 kHz 超声暴露安全。
- 首次上电必须按正式固件 README 的单片、单换能器到全阵的顺序逐级验证。
