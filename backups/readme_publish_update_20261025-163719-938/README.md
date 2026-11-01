# 空气净化器 USB 开机程序

打开整个项目文件夹，在 VS Code 选择“终端 → 运行任务 → CyberBrick：保存空气净化器为开机程序（先备份）”，输入实际串口（当前板卡为 COM5）。等待 `Saved and verified: air_filter_ctrl.py -> /main.py.` 后按 RST 或重新供电。

下载工具先备份板上的 boot.py 和 main.py，再把空气净化器程序保存为 main.py，并让 boot.py 不再启动原厂 RC 应用。MicroPython 底层固件保留。备份位于 backups，尤其要保留首次原厂备份。

## 上电后看到什么

- GPIO8 板载灯和 GPIO10 外接灯先显示低亮度白色 3 秒。
- 初始模式为关闭，未按按钮时，3 秒后两灯熄灭，风扇 PWM 为 0%。
- 从程序启动计时的前 30 秒，板载灯跟随外接灯的颜色、开关和闪烁。
- 满 30 秒后板载灯保持熄灭，外接灯及净化器功能继续运行；下次复位／上电重新计时。
- 按 GPIO2 按钮依次切换：自动 → 关闭 → 全速 → 关闭，再循环。按钮接 GPIO2 与 3V3，按下为高电平。
- 自动模式按空气质量输出 40%／70%／100% PWM，灯色为绿／黄／红。全速模式 PWM 为 100%，空气质量灯色每秒闪一次。
- 自动／全速模式连续 5 秒没有有效传感器数据时蓝灯常亮；关闭模式仍灭灯。

只接 USB、没有接外设，也能看到板载灯白色亮 3 秒。没有 GPIO2 按钮时不会进入自动模式，没有传感器时终端报告无有效帧属于预期现象。

## 新电脑首次准备

安装 Python 3 和 VS Code，在项目文件夹的终端执行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r requirements.txt
```

用可传输数据的 USB 线连接装有 MicroPython 的 CyberBrick 核心板，关闭其他占用串口的软件。通过“CyberBrick：查看串口”确认端口，再执行保存任务。

“运行空气净化器”只临时执行；“保存空气净化器为开机程序”才会断电保留。修改电脑源码后，需要重新保存到板卡。
