
from machine import Pin
import time

# ==========================================
# RING THE BULL - Pico W
# ==========================================
#
# GP14 -- 1M ohm resistor -- GP15 -- Ring
# GND ----------------------------- Hook
#
# Terminal: screen, minicom, picocom, etc.
# ANSI escape sequences may not work in Thonny.
# ==========================================

# GPIO
drive = Pin(14, Pin.OUT, value=0)
sense = Pin(15, Pin.IN)
led = Pin("LED", Pin.OUT)

# Touch thresholds (microseconds)
GRAB_THRESHOLD = 80
RELEASE_THRESHOLD = 70

# Debounce times (milliseconds)
GRAB_DEBOUNCE_MS = 150
RELEASE_DEBOUNCE_MS = 250
HOOK_DEBOUNCE_MS = 300
UNHOOK_DEBOUNCE_MS = 100

# Game timing
THROW_TIMEOUT_MS = 5000
POST_THROW_LOCKOUT_MS = 1000

# Sampling / display
SAMPLE_INTERVAL_MS = 20
DISPLAY_INTERVAL_MS = 200

# States
READY = 0
HELD = 1
IN_FLIGHT = 2
LANDED = 3
WAIT_RESET = 4

STATE_NAMES = {
    READY: "READY",
    HELD: "HELD",
    IN_FLIGHT: "IN FLIGHT",
    LANDED: "LANDED",
    WAIT_RESET: "WAIT RESET"
}

# Counters
throws = 0
hits = 0
misses = 0

# State variables
state = READY
hooked = False

touch_candidate_since = None
hook_candidate_since = None
unhook_candidate_since = None

throw_started = None
miss_flash_until = None

last_event = "SYSTEM READY"
last_cap = None
last_contact = False

last_display = time.ticks_ms()

led.off()


# ==========================================
# SENSOR FUNCTIONS
# ==========================================

def read_touch():
    # Discharge the ring
    drive.init(Pin.OUT, value=0)
    sense.init(Pin.OUT, value=0)
    time.sleep_ms(10)

    # Float GP15 and charge via 1M resistor
    sense.init(Pin.IN)

    start = time.ticks_us()
    drive.value(1)

    while sense.value() == 0:
        if time.ticks_diff(
            time.ticks_us(), start
        ) > 20000:
            return None

    return time.ticks_diff(
        time.ticks_us(), start
    )


def read_hook():
    # Float GP14
    drive.init(Pin.IN)

    # Check continuity to grounded hook
    sense.init(Pin.IN, Pin.PULL_UP)
    time.sleep_us(200)

    contact = sense.value() == 0

    # Restore GPIO configuration
    sense.init(Pin.IN)
    drive.init(Pin.OUT, value=0)

    return contact


# ==========================================
# DISPLAY
# ==========================================

def draw_dashboard(now):
    global last_display

    if time.ticks_diff(
        now, last_display
    ) < DISPLAY_INTERVAL_MS:
        return

    last_display = now

    if last_contact:
        cap_text = "GROUNDED"
    elif last_cap is None:
        cap_text = "TIMEOUT"
    else:
        cap_text = "{} us".format(last_cap)

    remaining = 0
    if state == IN_FLIGHT:
        elapsed = time.ticks_diff(
            now, throw_started
        )
        remaining = max(
            0,
            (THROW_TIMEOUT_MS - elapsed) / 1000
        )

    # ANSI: clear screen and move cursor home
    print("\033[2J\033[H", end="")

    print("+--------------------------------------+")
    print("|           RING THE BULL              |")
    print("+--------------------------------------+")
    print()
    print(" State:        {}".format(STATE_NAMES[state]))
    print(" Capacitance:  {}".format(cap_text))
    print(" Touch:        {}".format(
        "YES" if state == HELD else "NO"
    ))
    print(" Hook contact: {}".format(
        "YES" if last_contact else "NO"
    ))
    print(" Hooked:       {}".format(
        "YES" if hooked else "NO"
    ))
    print()
    print(" Throws:       {}".format(throws))
    print(" Hits:         {}".format(hits))
    print(" Misses:       {}".format(misses))

    if state == IN_FLIGHT:
        print(" Time left:    {:.1f}s".format(remaining))
    else:
        print(" Time left:    --")

    print()
    print(" Last event:   {}".format(last_event))
    print()
    print("+--------------------------------------+")


# ==========================================
# MAIN LOOP
# ==========================================

print("Ring the Bull starting...")

while True:
    now = time.ticks_ms()

    # --------------------------------------
    # HOOK CONTACT
    # --------------------------------------

    contact = read_hook()
    last_contact = contact

    if contact:
        unhook_candidate_since = None

        if not hooked:
            if hook_candidate_since is None:
                hook_candidate_since = now

            elif time.ticks_diff(
                now, hook_candidate_since
            ) >= HOOK_DEBOUNCE_MS:
                hooked = True
                hook_candidate_since = None
                last_event = "HOOKED!"

    else:
        hook_candidate_since = None

        if hooked:
            if unhook_candidate_since is None:
                unhook_candidate_since = now

            elif time.ticks_diff(
                now, unhook_candidate_since
            ) >= UNHOOK_DEBOUNCE_MS:
                hooked = False
                unhook_candidate_since = None
                last_event = "UNHOOKED"

    # --------------------------------------
    # CAPACITIVE TOUCH
    # --------------------------------------

    cap = None

    if not contact and not hooked:
        cap = read_touch()

    last_cap = cap

    # --------------------------------------
    # GAME STATE MACHINE
    # --------------------------------------

    if state == READY:

        if cap is not None and cap >= GRAB_THRESHOLD:
            if touch_candidate_since is None:
                touch_candidate_since = now

            elif time.ticks_diff(
                now, touch_candidate_since
            ) >= GRAB_DEBOUNCE_MS:
                state = HELD
                touch_candidate_since = None
                last_event = "GRABBED"

        else:
            touch_candidate_since = None

    elif state == HELD:

        if cap is not None and cap <= RELEASE_THRESHOLD:
            if touch_candidate_since is None:
                touch_candidate_since = now

            elif time.ticks_diff(
                now, touch_candidate_since
            ) >= RELEASE_DEBOUNCE_MS:
                state = IN_FLIGHT
                touch_candidate_since = None

                throws += 1
                throw_started = now
                last_event = "THROWN #{}".format(throws)

        else:
            touch_candidate_since = None

    elif state == IN_FLIGHT:

        if hooked:
            hits += 1
            state = LANDED
            last_event = "HIT! Total: {}".format(hits)

        elif time.ticks_diff(
            now, throw_started
        ) >= THROW_TIMEOUT_MS:
            misses += 1
            state = WAIT_RESET

            miss_flash_until = time.ticks_add(
                now, 600
            )
            last_event = "MISS! Total: {}".format(misses)

    elif state == LANDED:

        if not hooked:
            state = WAIT_RESET
            last_event = "RING REMOVED"

    elif state == WAIT_RESET:

        if time.ticks_diff(
            now, throw_started
        ) >= POST_THROW_LOCKOUT_MS:

            if cap is not None and cap >= GRAB_THRESHOLD:
                if touch_candidate_since is None:
                    touch_candidate_since = now

                elif time.ticks_diff(
                    now, touch_candidate_since
                ) >= GRAB_DEBOUNCE_MS:
                    state = HELD
                    touch_candidate_since = None
                    last_event = "GRABBED"

            else:
                touch_candidate_since = None

    # --------------------------------------
    # LED
    # --------------------------------------

    if hooked:
        led.on()

    elif miss_flash_until is not None:
        if time.ticks_diff(
            now, miss_flash_until
        ) < 0:
            led.value((now // 100) % 2)
        else:
            miss_flash_until = None
            led.off()

    else:
        led.off()

    # --------------------------------------
    # DASHBOARD
    # --------------------------------------

    draw_dashboard(now)

    time.sleep_ms(SAMPLE_INTERVAL_MS)
