from machine import Pin
import neopixel
import os
import time

# ==========================================
# RING THE BULL - capacitance diagnostic
# ==========================================
# Shows the live read_touch() value as a bar graph on the 22-pixel
# scoreboard. Not the game: no state machine, no scoring.
#
#   Bar length : (reading - BAR_MIN_US) / (BAR_MAX_US - BAR_MIN_US)
#   Bar colour : green  below RELEASE_THRESHOLD
#                amber  between release and grab
#                red    at/above GRAB_THRESHOLD
#   Timeout    : every 4th pixel blinks blue (no charge in 20 ms:
#                open wire / missing 1M / ring shorted low)
#   Hook       : onboard LED on, pixel 21 white while ring touches hook
#   Loaded     : onboard LED blinks 5 times at startup
#
# Logging: every update is appended to LOG_FILE on the Pico as
#   ms,avg_us,min_us,max_us,hook      (T = timeout, H = hook contact)
# so readings can be pulled off later:
#   mpremote cp :readings.csv .     or     ampy -p /dev/ttyACM0 get readings.csv
# Lines starting with # mark each boot. The file stops growing at
# LOG_MAX_BYTES; a file already over the cap is restarted at boot.
#
# Run without installing:  mpremote run diag_capacitance.py
# Readings are also printed over serial, one line each.
# ==========================================

drive = Pin(14, Pin.OUT, value=0)
sense = Pin(15, Pin.IN)
led = Pin("LED", Pin.OUT)

PIXEL_PIN = 28
PIXEL_COUNT = 22
BRIGHTNESS = 0.15

# Bar range in microseconds. Prototype: untouched 50-59, held 90-100.
# 40-100 pinned the bar full when held, so the top is back up to 200 until
# the logged readings show the real held range.
BAR_MIN_US = 40
BAR_MAX_US = 200

# Same values as main.py, to see where they sit against real readings
GRAB_THRESHOLD = 60
RELEASE_THRESHOLD = 45

SAMPLES = 3          # reads averaged per update
TIMEOUT_US = 20000
BLINK_MS = 250

LOG_FILE = "readings.csv"
LOG_MAX_BYTES = 200000
LOG_FLUSH_MS = 5000   # buffered; flash is written at most every few seconds

pixels = neopixel.NeoPixel(Pin(PIXEL_PIN, Pin.OUT), PIXEL_COUNT)


def color(r, g, b):
    return (
        int(r * BRIGHTNESS),
        int(g * BRIGHTNESS),
        int(b * BRIGHTNESS)
    )


OFF = (0, 0, 0)
GREEN = color(0, 255, 0)
AMBER = color(255, 140, 0)
RED = color(255, 0, 0)
BLUE = color(0, 0, 255)
WHITE = color(255, 255, 255)


def read_touch():
    drive.init(Pin.OUT, value=0)
    sense.init(Pin.OUT, value=0)
    time.sleep_ms(10)

    sense.init(Pin.IN)
    start = time.ticks_us()
    drive.value(1)

    while sense.value() == 0:
        if time.ticks_diff(time.ticks_us(), start) > TIMEOUT_US:
            return None

    return time.ticks_diff(time.ticks_us(), start)


def read_hook():
    drive.init(Pin.IN)
    sense.init(Pin.IN, Pin.PULL_UP)
    time.sleep_us(200)

    contact = sense.value() == 0

    sense.init(Pin.IN)
    drive.init(Pin.OUT, value=0)

    return contact


def read_average():
    # returns (avg, min, max) in us, or None if any read timed out
    total = 0
    lo = hi = None
    for _ in range(SAMPLES):
        v = read_touch()
        if v is None:
            return None
        total += v
        lo = v if lo is None or v < lo else lo
        hi = v if hi is None or v > hi else hi
    return total / SAMPLES, lo, hi


def value_color(v):
    if v >= GRAB_THRESHOLD:
        return RED
    if v > RELEASE_THRESHOLD:
        return AMBER
    return GREEN


def draw(value, hook, blink_on):
    pixels.fill(OFF)

    if hook:
        pixels[PIXEL_COUNT - 1] = WHITE
    elif value is None:
        if blink_on:
            for i in range(0, PIXEL_COUNT, 4):
                pixels[i] = BLUE
    else:
        span = BAR_MAX_US - BAR_MIN_US
        lit = int((value - BAR_MIN_US) * PIXEL_COUNT / span + 0.5)
        lit = max(0, min(PIXEL_COUNT, lit))
        # always show at least pixel 0 so a live strip is obvious
        lit = max(lit, 1)
        c = value_color(value)
        for i in range(lit):
            pixels[i] = c

    pixels.write()


# Startup signature: 5 quick onboard LED blinks = this script is running
for _ in range(5):
    led.on()
    time.sleep_ms(100)
    led.off()
    time.sleep_ms(100)

def log_open():
    try:
        if os.stat(LOG_FILE)[6] > LOG_MAX_BYTES:
            os.remove(LOG_FILE)
    except OSError:
        pass
    f = open(LOG_FILE, "a")
    f.write("# boot\n")
    f.flush()
    return f


log = log_open()
log_size = os.stat(LOG_FILE)[6]
log_buf = []
last_flush = time.ticks_ms()

while True:
    hook = read_hook()
    led.value(1 if hook else 0)

    stats = None if hook else read_average()
    value = None if stats is None else stats[0]
    now = time.ticks_ms()
    blink_on = (now // BLINK_MS) % 2 == 0

    draw(value, hook, blink_on)

    if hook:
        line = "%d,H,,,1" % now
        print("HOOK CONTACT")
    elif stats is None:
        line = "%d,T,,,0" % now
        print("TIMEOUT")
    else:
        line = "%d,%.1f,%d,%d,0" % (now, stats[0], stats[1], stats[2])
        print("%.1f us" % stats[0])

    if log_size < LOG_MAX_BYTES:
        log_buf.append(line)

    if time.ticks_diff(now, last_flush) >= LOG_FLUSH_MS and log_buf:
        data = "\n".join(log_buf) + "\n"
        log.write(data)
        log.flush()
        log_size += len(data)
        log_buf = []
        last_flush = now
