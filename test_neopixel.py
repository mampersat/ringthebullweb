
from machine import Pin
import neopixel
import time

PIN = 28
COUNT = 100
BRIGHTNESS = 30

np = neopixel.NeoPixel(Pin(PIN, Pin.OUT), COUNT)

while True:
    print("RED")
    np.fill((BRIGHTNESS, 0, 0))
    np.write()
    time.sleep(2)

    print("GREEN")
    np.fill((0, BRIGHTNESS, 0))
    np.write()
    time.sleep(2)

    print("BLUE")
    np.fill((0, 0, BRIGHTNESS))
    np.write()
    time.sleep(2)

    print("OFF")
    np.fill((0, 0, 0))
    np.write()
    time.sleep(1)
