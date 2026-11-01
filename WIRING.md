# 空气净化器 GPIO 分配

适用于 CyberBrick 核心板单独使用，不插 X11/X12 底板。
按官方示意图朝向：天线朝上、USB-C 朝下、元件面朝自己。
左侧排针从上往下是 3、4、5、6、7、9、10、GND。
本项目使用同侧的 5、6、10 和 GND，4、7、9 留空。
模式按钮另接右侧 GPIO2。

| 核心板丝印 | GPIO | 任务 | 信号连接 |
| --- | --- | --- | --- |
| 2 | GPIO2 | 模式按钮输入，按下为高电平 | 常开按钮连接 GPIO2 与 3V3，程序启用内部下拉 |
| 5 | GPIO5 | UART1 RX，读取传感器 | 传感器 TX → 核心板 RX（已确认 3.3V UART） |
| 6 | GPIO6 | 风扇 PWM 控制信号 | → 风扇 PWM（已确认 3.3V 电平，输出形式要求待确认） |
| 10 | GPIO10 | 外接 CyberBrick RGB LED / Hub 数据 | → 3.3V 转 5V 电平转换 → Hub DIN |
| GND | — | 公共地 | 对于共地低压接口，连接传感器、LED 电源和风扇接口地 |

用户已确定不接传感器 RX：仅将传感器 TX 接到 GPIO5，接收传感器主动上报的数据。
不分配对传感器发送命令的信号线；GPIO4 留空。
UART 协议按用户提供的图片确定：9600 波特率、8 数据位、无校验、1 停止位。
每帧 32 字节，帧头 42 4D，长度字段 00 1C；最后两字节为前 30 字节的累加和（高字节在前）。
`air_filter_ctrl.py` 校验后打印标准颗粒物和大气环境两组 PM1.0、PM2.5、PM10，单位 µg/m³。
协议标注已屏蔽的颗粒计数和预留字段仅参与校验，不作为有效测量值输出。
UART1 的 RX 指定为 GPIO5，不必使用板上的 R0。
GPIO4～7 同时有外部 JTAG 复用功能；此分配用于目前的 USB / mpremote 开发，
不同时连接使用 GPIO4～7 的外部 JTAG 探针。

## 接口与供电确认

- 用户已确认传感器 UART 信号和风扇 PWM 控制管脚均为 3.3V 电平。
  传感器 TX 可直接连接核心板 GPIO5（RX），电源地与核心板共地。
  传感器的供电电压仍应根据型号确认，不能由信号电压推断。
- GPIO6 只输出 PWM 控制信号。风扇按额定电压单独供电，
  3.3V PWM 输入若允许推挽驱动，可直接连接 GPIO6；如明确要求开漏驱动，
  则需采用相应输出方式 / 接口电路。PWM 频率须根据风扇规格确定。
  两线风扇需使用功率开关驱动电路；不能由 GPIO 直接供电。
- LED Hub 按标识接 5V、GND、DIN；SH 接口的实际针序需确认，不能只按线色判断。
  外接 RGB 使用 GPIO10；板载 RGB 仍是 GPIO8。
  为可靠控制 5V RGB 灯，采用 5V 供电的 74AHCT125 等适用电平转换器。
- GPIO9 接板载 USER KEY，又是启动配置管脚，外设可能影响上电启动，因此留空。
  GPIO7 留空；GPIO10 用于外接 RGB 数据。
- 用户已确认 GPIO2 按下为高电平：`BUTTON_ACTIVE_LEVEL = 1`，程序启用内部下拉，
  高电平稳定 40ms 后计为按下一次。正常应为松开 0、按下 1。
  松开需稳定 40ms 才能再次触发，长按不会连续切换，启动时已按住也不会自动开启。
  `BUTTON_DEBUG = True` 时终端打印 `[BUTTON]` 初始电平及后续原始电平变化。
  此前低电平有效版本推荐的外部上拉电阻不适用于当前按下高电平的接法；
  如松开仍为高电平，应检查已有上拉电阻、开关接法或模块输出。
  GPIO2 是启动配置管脚，官方仍建议复位时上拉；内部下拉仅在程序配置后生效，
  当前运行接法的启动／复位表现需要在实物上验证。
- 风扇 PWM 暂设 25kHz，可通过 `FAN_PWM_FREQ` 按风扇规格修改。
  关闭时输出 0%（持续低电平），不让 PWM 输入悬空；是否能完全停转取决于风扇型号。

程序中统一采用：

```python
SENSOR_UART_ID = 1
SENSOR_RX_PIN = 5
FAN_PWM_PIN = 6
EXTERNAL_LED_PIN = 10
```

传感器已由用户确认实测可读取。新增按钮及风扇联合控制尚待实际板卡验证。

参考：

- [CyberBrick 官方核心板管脚图](https://github.com/CyberBrick-Official/CyberBrick_Controller_Core/blob/master/docs/cyberbrick_core/img/Controller_core.png)
- [CyberBrick UART / PWM 说明](https://github.com/CyberBrick-Official/CyberBrick_Controller_Core/blob/master/docs/cyberbrick_core/quickref.rst)
- [ESP32-C3 数据手册：启动配置与管脚复用](https://documentation.espressif.com/esp32-c3_datasheet_en.html)
