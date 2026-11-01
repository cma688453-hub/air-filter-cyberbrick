"""GPIO2 按钮、GPIO5 传感器、GPIO6 风扇；GPIO8 在前 30 秒跟随 GPIO10 灯。"""


LED_PIN = 10
LED_COUNT = 1  # 单颗 RGB 灯；使用转接板时接 OUT1。
ONBOARD_LED_PIN = 8
ONBOARD_MIRROR_MS = 30000  # 从程序启动计时，前 30 秒跟随外接灯，之后保持熄灭。
GREEN = (0, 20, 0)  # (红, 绿, 蓝)，先使用低亮度。
YELLOW = (20, 20, 0)
RED = (20, 0, 0)
WHITE = (20, 20, 20)
BLUE = (0, 0, 20)
OFF = (0, 0, 0)
STARTUP_WHITE_MS = 3000
SENSOR_FAULT_WHEN_OFF = False  # True 可在关闭模式也用蓝灯提示传感器无数据。

# CyberBrick 官方外接灯驱动使用的时序，单位为纳秒。
# 顺序：0 的高电平、0 的低电平、1 的高电平、1 的低电平。
LED_TIMING = (400, 1000, 1000, 400)

SENSOR_UART_ID = 1
SENSOR_RX_PIN = 5
SENSOR_BAUDRATE = 9600
FRAME_HEADER = b"\x42\x4d"
FRAME_SIZE = 32
FRAME_DATA_LENGTH = 28  # 帧内长度字段：数据 + 校验，不含前四字节。
NO_DATA_NOTICE_MS = 5000

# 本项目的实时颗粒物提示等级，使用 ATM 浓度，单位 µg/m³。
# 数值参考 WHO 2021 的 24 小时指南值及过渡目标 IT-2；
# 以下短时平滑结果不是 24 小时平均值，也不是正式 AQI 或全面室内空气评价。
PM25_GOOD_MAX = 15
PM10_GOOD_MAX = 45
PM25_MODERATE_MAX = 50
PM10_MODERATE_MAX = 100
AVERAGE_SAMPLES = 5
LEVEL_CONFIRM_SAMPLES = 3
QUALITY_COLORS = {"GOOD": GREEN, "MODERATE": YELLOW, "POOR": RED}

BUTTON_PIN = 2
BUTTON_ACTIVE_LEVEL = 1  # 按钮接 3V3，内部下拉；按下为高电平。
BUTTON_DEBOUNCE_MS = 40  # 按下、释放都需稳定 40ms；长按只触发一次。
BUTTON_DEBUG = True  # 排查按钮接线时打印原始电平变化，稳定后可改为 False。
FAN_PWM_PIN = 6
FAN_PWM_FREQ = 25000  # 先按常见四线 PWM 风扇设置；以实际风扇规格为准。
FAN_AUTO_PERCENT = {"GOOD": 40, "MODERATE": 70, "POOR": 100}
TURBO_FLASH_HALF_MS = 500  # 亮 0.5 秒、灭 0.5 秒，每秒闪一次。


class DebouncedButton:
    """确认稳定的按下沿；启动时已按住需先释放，防止上电误启动。"""

    def __init__(self, initial_level, now_ms, elapsed):
        self.raw_level = initial_level
        self.stable_level = initial_level
        self.changed_ms = now_ms
        self.elapsed = elapsed  # 板上用 ticks_diff，正确处理计时器回绕。
        self.armed = initial_level != BUTTON_ACTIVE_LEVEL

    def update(self, level, now_ms):
        if level != self.raw_level:
            self.raw_level = level
            self.changed_ms = now_ms
        if (self.raw_level == self.stable_level
                or self.elapsed(now_ms, self.changed_ms) < BUTTON_DEBOUNCE_MS):
            return False
        self.stable_level = self.raw_level
        if self.stable_level != BUTTON_ACTIVE_LEVEL:
            self.armed = True
        elif self.armed:
            self.armed = False
            return True
        return False


class OperatingMode:
    """两个 OFF 保留各自循环位置：AUTO → OFF → TURBO → OFF → AUTO。"""

    STEPS = ("AUTO", "OFF", "TURBO", "OFF")

    def __init__(self):
        self.step = 3  # 上电关闭，第一次按下进入 AUTO。

    def advance(self):
        self.step = (self.step + 1) % len(self.STEPS)
        return self.name()

    def name(self):
        return self.STEPS[self.step]

    def outputs(self, quality_level, turbo_visible=True):
        """返回风扇占空比百分数和灯色；传感器缺数据时颜色保持未知／熄灭。"""
        mode = self.name()
        color = QUALITY_COLORS.get(quality_level, OFF)
        if mode == "AUTO":
            return FAN_AUTO_PERCENT.get(quality_level, 0), color
        if mode == "TURBO":
            return 100, color if turbo_visible else OFF
        return 0, OFF


def percent_to_duty(percent):
    """将百分数转为 MicroPython PWM 的 0～65535，占空比四舍五入。"""
    return (percent * 65535 + 50) // 100


def indicator_color(mode_name, normal_color, startup_active, sensor_missing):
    """白灯自检优先；随后用蓝灯提示连续五秒没有有效传感器数据。"""
    if startup_active:
        return WHITE
    if sensor_missing and (mode_name != "OFF" or SENSOR_FAULT_WHEN_OFF):
        return BLUE
    return normal_color


def classify_air(pm25, pm10):
    """任一指标超出上限就取较差等级，边界值包含在较好等级中。"""
    if pm25 > PM25_MODERATE_MAX or pm10 > PM10_MODERATE_MAX:
        return "POOR"
    if pm25 > PM25_GOOD_MAX or pm10 > PM10_GOOD_MAX:
        return "MODERATE"
    return "GOOD"


class AirQuality:
    """最近五帧均值；变更等级需连续三次判定一致，减少灯色来回跳动。"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.samples = []
        self.pm25_average = None
        self.pm10_average = None
        self.level = None
        self.candidate = None
        self.candidate_count = 0

    def update(self, reading):
        self.samples.append((reading["pm25_atmospheric"], reading["pm10_atmospheric"]))
        self.samples = self.samples[-AVERAGE_SAMPLES:]
        count = len(self.samples)
        self.pm25_average = sum(item[0] for item in self.samples) / count
        self.pm10_average = sum(item[1] for item in self.samples) / count
        if count < AVERAGE_SAMPLES:
            return  # 收满五帧前保持未知，灯熄灭。

        target = classify_air(self.pm25_average, self.pm10_average)
        if self.level is None:
            self.level = target
        if target == self.level:
            self.candidate = None
            self.candidate_count = 0
        else:
            if target != self.candidate:
                self.candidate = target
                self.candidate_count = 0
            self.candidate_count += 1
            if self.candidate_count >= LEVEL_CONFIRM_SAMPLES:
                self.level = target
                self.candidate = None
                self.candidate_count = 0

    def color(self):
        return QUALITY_COLORS.get(self.level, OFF)

    def expire(self, elapsed_ms):
        """超过有效数据等待时限后清空旧均值和等级；恢复时重新收集五帧。"""
        if elapsed_ms >= NO_DATA_NOTICE_MS and self.samples:
            self.reset()


def read_u16(data, offset):
    """协议中的两个字节按高字节在前组合，例如 0x01 0x02 = 258。"""
    return (data[offset] << 8) | data[offset + 1]


class SensorParser:
    """保留未收完的帧，处理半包、连续多帧及错误数据后的重新同步。"""

    def __init__(self):
        self.buffer = bytearray()
        self.bad_length = 0
        self.bad_checksum = 0

    def feed(self, data):
        self.buffer.extend(data)
        readings = []
        while True:
            start = self.buffer.find(FRAME_HEADER)
            if start < 0:
                # 末尾的 0x42 可能是下一帧帧头的第一个字节。
                if self.buffer and self.buffer[-1] == 0x42:
                    self.buffer = bytearray(b"\x42")
                else:
                    self.buffer = bytearray()
                break
            if start:
                # 板上的 MicroPython 不支持 del bytearray，改为保留剩余切片。
                self.buffer = self.buffer[start:]
            if len(self.buffer) < 4:
                break
            if read_u16(self.buffer, 2) != FRAME_DATA_LENGTH:
                self.bad_length += 1
                self.buffer = self.buffer[1:]
                continue
            if len(self.buffer) < FRAME_SIZE:
                break

            frame = self.buffer[:FRAME_SIZE]
            if sum(frame[:30]) != read_u16(frame, 30):
                self.bad_checksum += 1
                # 逐字节重新寻找帧头，避免丢掉错位数据中的有效帧。
                self.buffer = self.buffer[1:]
                continue

            readings.append({
                "pm1_standard": read_u16(frame, 4),
                "pm25_standard": read_u16(frame, 6),
                "pm10_standard": read_u16(frame, 8),
                "pm1_atmospheric": read_u16(frame, 10),
                "pm25_atmospheric": read_u16(frame, 12),
                "pm10_atmospheric": read_u16(frame, 14),
            })
            # BYTE16～27 是协议标注已屏蔽的颗粒计数，BYTE28～29 为预留。
            # 它们参与校验，但不作为可用测量值输出。
            self.buffer = self.buffer[FRAME_SIZE:]
        return readings


def print_reading(number, reading, quality):
    """通过 USB 开发终端打印，不向传感器串口发送数据。"""
    print(
        "[PM #%d] ATM: PM1.0=%d PM2.5=%d PM10=%d ug/m3 | "
        "STD: PM1.0=%d PM2.5=%d PM10=%d ug/m3"
        % (number,
           reading["pm1_atmospheric"], reading["pm25_atmospheric"],
           reading["pm10_atmospheric"], reading["pm1_standard"],
           reading["pm25_standard"], reading["pm10_standard"])
    )
    if quality.level is None:
        print("[AIR] Collecting samples: %d/%d, LED OFF"
              % (len(quality.samples), AVERAGE_SAMPLES))
    else:
        print("[AIR] %s | avg PM2.5=%.1f PM10=%.1f ug/m3 | pending=%s"
              % (quality.level, quality.pm25_average, quality.pm10_average,
                 quality.candidate or "none"))


def main():
    # 硬件模块在板上运行时加载，便于在电脑上单独测试协议解析。
    from machine import Pin, PWM, UART
    from neopixel import NeoPixel
    from time import sleep_ms, ticks_ms, ticks_diff, ticks_add

    fan_pin = Pin(FAN_PWM_PIN, Pin.OUT, value=0)
    fan_pwm = None
    led = None
    onboard_led = None
    uart = None
    parser = SensorParser()
    quality = AirQuality()
    mode = OperatingMode()
    received_bytes = 0
    frame_count = 0
    print("Air filter: GPIO10 LED: GOOD=green, MODERATE=yellow, POOR=red.")
    print("Button GPIO2: AUTO -> OFF -> TURBO -> OFF. Startup: OFF.")
    print("Fan GPIO6: %d Hz; AUTO=40/70/100%%; TURBO=100%%; OFF=0%%."
          % FAN_PWM_FREQ)
    print("Particle indicator only. Average=5 frames; confirm changes=3 frames.")
    print("Sensor: UART1 RX=GPIO5, 9600 baud, 8N1. Waiting for 42 4D frames.")
    print("ATM=atmospheric, STD=standard particles; unit: ug/m3. Ctrl+C to stop.")

    try:
        fan_pwm = PWM(fan_pin, freq=FAN_PWM_FREQ, duty_u16=0)
        led = NeoPixel(Pin(LED_PIN, Pin.OUT, value=0), LED_COUNT, timing=LED_TIMING)
        onboard_led = NeoPixel(Pin(ONBOARD_LED_PIN, Pin.OUT, value=0), 1)
        button_pull = Pin.PULL_UP if BUTTON_ACTIVE_LEVEL == 0 else Pin.PULL_DOWN
        button_pin = Pin(BUTTON_PIN, Pin.IN, button_pull)
        last_button_level = button_pin.value()
        button = DebouncedButton(last_button_level, ticks_ms(), ticks_diff)
        print("[BUTTON] GPIO%d initial=%d active=%d pull=%s debounce=%dms"
              % (BUTTON_PIN, last_button_level, BUTTON_ACTIVE_LEVEL,
                 "UP" if BUTTON_ACTIVE_LEVEL == 0 else "DOWN", BUTTON_DEBOUNCE_MS))
        # 仅接收：传感器 TX 接 GPIO5，传感器 RX 不接，不调用 uart.write()。
        uart = UART(SENSOR_UART_ID, baudrate=SENSOR_BAUDRATE,
                    bits=8, parity=None, stop=1, rx=Pin(SENSOR_RX_PIN),
                    rxbuf=1024, timeout=0, timeout_char=2)
        led_color = WHITE
        led.fill(led_color)
        led.write()
        onboard_led.fill(led_color)
        onboard_led.write()
        last_valid_frame = ticks_ms()
        startup_started_ms = last_valid_frame
        startup_active = True
        onboard_mirror_active = True
        print("[LED] WHITE for 3 seconds; GPIO8 mirrors GPIO10 for 30 seconds.")
        last_notice = last_valid_frame
        blink_changed_ms = last_valid_frame
        turbo_visible = True
        fan_percent = 0

        while True:
            now = ticks_ms()
            button_level = button_pin.value()
            if button_level != last_button_level:
                if BUTTON_DEBUG:
                    print("[BUTTON] GPIO%d raw=%d" % (BUTTON_PIN, button_level))
                last_button_level = button_level
            if button.update(button_level, now):
                mode.advance()
                turbo_visible = True
                blink_changed_ms = now
                print("[MODE] step=%d mode=%s" % (mode.step + 1, mode.name()))

            quality.expire(ticks_diff(ticks_ms(), last_valid_frame))
            if uart.any():
                data = uart.read(256)
                if data:
                    received_bytes += len(data)
                    for reading in parser.feed(data):
                        frame_count += 1
                        last_valid_frame = ticks_ms()
                        quality.update(reading)
                        print_reading(frame_count, reading, quality)

            now = ticks_ms()
            if mode.name() == "TURBO":
                elapsed = ticks_diff(now, blink_changed_ms)
                if elapsed >= TURBO_FLASH_HALF_MS:
                    phases = elapsed // TURBO_FLASH_HALF_MS
                    if phases % 2:
                        turbo_visible = not turbo_visible
                    blink_changed_ms = ticks_add(
                        blink_changed_ms, phases * TURBO_FLASH_HALF_MS)

            new_percent, new_color = mode.outputs(quality.level, turbo_visible)
            if startup_active and ticks_diff(now, startup_started_ms) >= STARTUP_WHITE_MS:
                startup_active = False
                print("[LED] Startup white finished.")
            new_color = indicator_color(
                mode.name(), new_color, startup_active,
                ticks_diff(now, last_valid_frame) >= NO_DATA_NOTICE_MS)
            if new_percent != fan_percent:
                # OFF 用 0% 保持低电平，不让控制脚悬空。
                fan_pwm.duty_u16(percent_to_duty(new_percent))
                fan_percent = new_percent
                print("[FAN] mode=%s PWM=%d%%" % (mode.name(), fan_percent))
            if (onboard_mirror_active
                    and ticks_diff(now, startup_started_ms) >= ONBOARD_MIRROR_MS):
                onboard_mirror_active = False  # 锁定关闭，计时器回绕后也不重新跟随。
                onboard_led.fill(OFF)
                onboard_led.write()
                print("[LED] GPIO8 mirror finished; onboard LED OFF.")
            if new_color != led_color:
                led.fill(new_color)
                led.write()
                led_color = new_color
                if onboard_mirror_active:
                    onboard_led.fill(new_color)
                    onboard_led.write()

            if (ticks_diff(now, last_valid_frame) >= NO_DATA_NOTICE_MS
                    and ticks_diff(now, last_notice) >= NO_DATA_NOTICE_MS):
                print("[UART] No valid frame for 5s. RX bytes=%d, "
                      "bad length=%d, bad checksum=%d"
                      % (received_bytes, parser.bad_length, parser.bad_checksum))
                last_notice = now

            # 短暂让出执行时间，每轮都处理串口。
            sleep_ms(10)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        # 中断或异常时先关闭风扇信号，再熄灯并释放串口。
        try:
            try:
                if fan_pwm is not None:
                    fan_pwm.deinit()
            finally:
                fan_pin.init(Pin.OUT, value=0)
        finally:
            try:
                if led is not None:
                    led.fill(OFF)
                    led.write()
            finally:
                try:
                    if onboard_led is not None:
                        onboard_led.fill(OFF)
                        onboard_led.write()
                finally:
                    if uart is not None:
                        uart.deinit()


if __name__ == "__main__":
    main()
