from machine import Pin
import time

drive = Pin(14, Pin.OUT)
sense = Pin(15, Pin.IN)

def read_touch():
    # Discharge both pins
    drive.value(0)
    sense.init(Pin.OUT, value=0)
    time.sleep_ms(10)

    # Float the sensing pin
    sense.init(Pin.IN)

    # Charge through the 1 MΩ resistor
    start = time.ticks_us()
    drive.value(1)

    while sense.value() == 0:
        if time.ticks_diff(time.ticks_us(), start) > 20000:
            return None

    return time.ticks_diff(time.ticks_us(), start)

while True:
    print(read_touch())
    time.sleep_ms(100)