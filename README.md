# CyberBrick 智能空气净化器

本工程使用 CyberBrick ESP32-C3 核心板读取颗粒物传感器数据，根据空气质量控制风扇和 RGB 灯。通过 USB 把程序保存到板卡后，再次上电即可运行。

本文按 Windows＋VS Code 说明，涵盖首次准备、保存净化器程序、保留原厂备份，以及恢复原厂 RC 启动。

## 1. 下载工程并准备工具

- 装有原厂 MicroPython 固件的 CyberBrick 多功能核心板。
- 支持数据传输的 USB 数据线。
- Windows 电脑、Python 3 和 VS Code；本项目曾在 Python 3.13 环境验证。
- 风扇、传感器、RGB 灯和模式按钮。首次测试可以只接 USB，观察板载灯。

从 GitHub 下载：打开仓库，点击 **Code → Download ZIP**，然后解压。使用 VS Code 的“文件 → 打开文件夹”，打开**整个工程文件夹**，其中应能看到 `air_filter_ctrl.py`、`requirements.txt` 和 `tools`。

```text
air_filter_cyberbrick/
├── README.md                        # 本使用说明
├── air_filter_ctrl.py                # 净化器程序
├── requirements.txt                 # 电脑下载工具依赖
├── WIRING.md                        # 详细接线说明
├── .vscode/
│   └── tasks.json                   # VS Code 运行、保存和恢复入口
├── tools/
│   ├── save_autostart.py             # 自动备份并保存开机程序
│   └── restore_factory.py            # 恢复原厂 RC 启动
└── backups/
    └── 20261018-122213-109661/        # 作者提供的备用原厂启动备份
        ├── boot.py
        └── manifest.json
```

## 2. 第一次在电脑上准备环境

在 VS Code 点击“终端 → 新建终端”，确认当前所在目录是工程文件夹，依次执行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r requirements.txt
```

第一行创建本工程的独立 Python 工具环境，第二行安装 USB 通信工具 `mpremote`。通常只需首次准备时执行，日后下载程序不用重新安装。

如果安装失败，先检查网络和完整报错。本命令已经指定官方 PyPI 下载源；不要因为连接失败就随意修改依赖版本号。

## 3. 接线与选择串口

完整接线见 [WIRING.md](WIRING.md)。本程序使用：

| 管脚 | 接什么 |
| --- | --- |
| GPIO2 | 模式按钮，按钮另一端接 3V3，按下为高电平 |
| GPIO5 | 传感器 TX，UART 9600、8N1；传感器 RX 不接 |
| GPIO6 | 风扇 PWM 控制信号，25kHz |
| GPIO10 | 外接 RGB 灯数据输入 |
| GPIO8 | 核心板自带 RGB 灯，无需接线 |
| GND | 各低压接口公共地 |

传感器和风扇控制信号需符合本项目的 3.3V 接口要求；外设电源按各自规格提供。风扇供电不接 GPIO，RGB 灯供电及电平转换按接线说明处理。

用 USB 连接核心板，关闭 CyberBrick 软件和其他占用串口的工具。在 VS Code 选择：

**终端 → 运行任务 → CyberBrick：查看串口**

通过插拔前后变化确认核心板的 COM 端口，例如 COM5。COM5 只是任务默认值，其他电脑可能不同，按实际情况填写。

## 4. 保存净化器程序，同时备份原厂启动文件

### 在 VS Code 菜单中操作

1. 选择“终端 → 运行任务 → **CyberBrick：保存空气净化器为开机程序（先备份）**”。
2. 输入实际串口，按回车。
3. 工具先把板卡当前启动文件保存到电脑 `backups/日期时间/`，再把净化器程序写入板卡。
4. 等待出现下面的成功提示，任务结束后再按 RST，或断电重新供电：

```text
Startup backup saved to: .../backups/日期时间
Saved and verified: air_filter_ctrl.py -> /main.py.
```

**第一次下载前板卡若仍是原厂 RC 启动，这次自动备份就是自己的原厂启动备份。请把该文件夹另外复制一份保管。**

工具把 `air_filter_ctrl.py` 保存为板上 `/main.py`，并修改 `/boot.py`，使原厂 RC 应用让出开机入口。MicroPython 底层固件、原厂应用目录保留；原厂 RC 遥控程序暂时不再开机启动。

以后修改代码，再执行相同的“保存”任务即可更新。后续备份可能已经是净化器程序，因此不能用“最新备份”代替“第一次原厂备份”。

### 用终端执行也可以

```powershell
.\.venv\Scripts\python.exe tools/save_autostart.py --port COM5 --source air_filter_ctrl.py
```

### 认识自己的备份

```text
backups/自己的日期时间/
├── boot.py
├── manifest.json
└── main.py         # 只有备份时板上原本存在，才会有这个文件
```

- `boot.py` 保存当时的启动程序。
- `manifest.json` 记录文件内容及文件是否原本存在，恢复时要一起保留。
- `main.py` 不存在不一定是备份失败；若记录为 `null`，表示原厂当时就没有该文件。

这里的“原厂备份”指**启动文件备份，不是整片 Flash 的完整固件镜像**。它依赖板上的原厂应用和底层固件仍然存在。

## 5. 上电后怎样使用

| 从程序启动开始计时 | GPIO8 板载灯 | GPIO10 外接灯 |
| --- | --- | --- |
| 前 3 秒 | 白色 | 白色 |
| 3～30 秒 | 跟随外接灯的颜色、开关和闪烁 | 按当前运行模式工作 |
| 满 30 秒后 | 保持熄灭 | 继续按当前运行模式工作 |

**初始模式是关闭。未按按钮时，白灯亮 3 秒后两灯熄灭，这是正常现象。**只接 USB、不接外设，也能用板载白灯确认程序已开始运行。

每按一次 GPIO2 按钮，依次切换：

| 按下次数 | 模式 | 风扇 PWM | 灯光 |
| --- | --- | --- | --- |
| 第一次 | 自动 | 空气质量优／中等／差，对应 40%／70%／100% | 绿／黄／红灯常亮 |
| 第二次 | 关闭 | 0% | 熄灭 |
| 第三次 | 全速 | 100% | 按空气质量显示颜色，每秒闪一次 |
| 第四次 | 关闭 | 0% | 熄灭 |
| 第五次起 | 按上述顺序循环 | — | — |

自动／全速模式连续 5 秒收不到有效传感器数据，显示蓝灯；关闭模式仍灭灯。自动模式需要形成有效空气质量等级后才输出对应风扇档位。这里的空气质量分级是颗粒物提示。

## 6. 用自己的备份恢复原厂 RC 启动

恢复前，停止净化器工作、断电并断开风扇、传感器、外接灯和按钮，再用 USB 连接核心板。关闭占用串口的 CyberBrick 软件或其他工具。

1. 确认自己的原厂备份仍在工程的 `backups` 目录中。
2. 选择“终端 → 运行任务 → **CyberBrick：恢复原厂RC启动（选择自己的备份）**”。
3. 输入实际串口。
4. 在底部终端中，选择属于自己板卡的原厂备份编号，按回车。直接回车可取消。
5. 等待成功提示：

```text
Restored and verified: factory RC startup.
```

6. 按 RST 或重新供电，再打开 CyberBrick 软件连接板卡。需要使用原厂遥控项目时，按其要求接回底板、配对并发送配置。

也可以在项目终端执行，再按提示选择备份：

```powershell
.\.venv\Scripts\python.exe tools/restore_factory.py --port COM5
```

恢复工具先把当前文件另存到 `backups/before_rc_restore_日期时间/`，校验待恢复文件，再恢复启动入口。如果备份中原本没有 `main.py`，当前净化器的该文件会改名保留，不再作为开机入口；如果原本存在，则恢复对应内容。恢复后已有 JSON 配置和配对信息保留，净化器不再自动启动。

## 7. 如果忘记保留自己的原厂备份

本工程附带作者的备用启动备份：

**[backups/20261018-122213-109661](backups/20261018-122213-109661)**

该备份来自作者的 CyberBrick 核心板，RC 应用版本为 **01.00.00.21**，包括 `boot.py` 和 `manifest.json`；当时原厂没有 `main.py`。

**优先使用自己的备份。个人备份丢失时，可以尝试作者备用备份恢复同款 CyberBrick 核心板的原厂 RC 启动，前提是板上的原厂 `app`、`bbl` 目录和兼容的 MicroPython 固件仍然保留。其他原厂应用版本不保证兼容。**

操作步骤与上一节相同，但在 VS Code 选择：

**终端 → 运行任务 → CyberBrick：恢复原厂RC启动（作者备用备份）**

输入实际串口后，工具直接使用上面的备用文件夹。若使用终端，完整命令是：

```powershell
.\.venv\Scripts\python.exe tools/restore_factory.py --port COM5 --backup backups/20261018-122213-109661
```

等出现 `Restored and verified: factory RC startup.`，再按 RST／重新供电。成功提示确认文件写入与读回校验，仍需用 CyberBrick 软件检查是否能连接并正常使用。

**作者备用备份无法修复已清空的 Flash、被删除的原厂应用目录，或被其他固件覆盖的底层环境。**遇到原厂文件缺失、启动报错或版本不兼容，应保留错误记录，按官方恢复方法处理。

## 8. 常见问题

| 现象 | 处理方法 |
| --- | --- |
| 找不到 `.venv/Scripts/python.exe` | 在当前工程目录执行第 2 节的环境准备命令；其他工程的 `.venv` 不能代替当前目录的环境。 |
| 安装工具时连接失败 | 检查网络和错误信息，使用第 2 节指定官方源的命令重试。 |
| 串口找不到或被占用 | 确认 USB 线能传数据、COM 端口正确，并关闭其他串口软件。 |
| 提示 `No module named machine` | 板卡程序被放到电脑 Python 中执行了。请使用本工程的“临时运行”或“保存开机程序”任务。 |
| 白灯 3 秒后灭了，风扇不转 | 默认关闭，需要按一次 GPIO2 按钮。没有接按钮时不会自行进入自动模式。 |
| 终端显示 `No valid frame for 5s` | 尚未收到有效传感器帧。没接传感器时属于预期；接好后检查供电、共地、GPIO5 和串口协议。 |
| 临时运行正常，断电后没有保留 | “临时运行”不会保存文件；要执行“保存空气净化器为开机程序（先备份）”，并等待成功提示。 |
| 恢复时没有找到自己的原厂备份 | 先找回自己的备份；确实丢失时按第 7 节评估并使用作者备用备份。 |
| 恢复提示文件与 manifest 不一致 | 备份可能被改动，使用完整副本，不要手动修改 manifest 来跳过校验。 |

需要修改净化器功能时，编辑 `air_filter_ctrl.py`，保存后重新下载即可。想从原厂 RC 再切回净化器，也可以重新执行“保存空气净化器为开机程序”任务。

## 发布者说明

上传 GitHub 时保留代码、工具、`.vscode`、说明文件，以及 `backups/20261018-122213-109661` 这份作者备用备份。不要把 `.venv`、缓存和后续生成的个人备份一起发布。

随附 `.gitignore` 已保留作者备用备份的上传规则，并忽略其他本地备份；网页手动上传时，仍需自行选择正确文件。

参考：[GitHub 下载 ZIP](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives)、[MicroPython mpremote](https://docs.micropython.org/en/v1.27.0/reference/mpremote.html)、[CyberBrick 官方代码库](https://github.com/CyberBrick-Official/CyberBrick_Controller_Core)。
