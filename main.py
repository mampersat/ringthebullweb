
from machine import Pin
import math
import neopixel
import os
import time
from records import Records

# ==========================================
# RING THE BULL - Pico W
# ==========================================
#
# GP14 -- 1M resistor -- GP15 -- Ring
# GND -------------------------- Hook
# GP28 ------------------------- NeoPixel DIN
#
# Pixel 0: current state
# Pixels 1+: throw history
# ==========================================

# ------------------------------------------
# HARDWARE
# ------------------------------------------

drive = Pin(14, Pin.OUT, value=0)
sense = Pin(15, Pin.IN)
led = Pin("LED", Pin.OUT)

PIXEL_PIN = 28
PIXEL_COUNT = 100
BRIGHTNESS = 0.07

pixels = neopixel.NeoPixel(
    Pin(PIXEL_PIN, Pin.OUT), PIXEL_COUNT
)


def color(r, g, b):
    return (
        int(r * BRIGHTNESS),
        int(g * BRIGHTNESS),
        int(b * BRIGHTNESS)
    )


OFF = (0, 0, 0)
RED = color(255, 0, 0)
GREEN = color(0, 255, 0)
BLUE = color(0, 0, 255)
WHITE = color(255, 255, 255)
# Capacitance pixel keeps its own (brighter) scale, independent of BRIGHTNESS
PURPLE_BRIGHTNESS = 0.15
PURPLE = (
    int(160 * PURPLE_BRIGHTNESS),
    0,
    int(255 * PURPLE_BRIGHTNESS)
)

# ------------------------------------------
# CONFIGURATION
# ------------------------------------------

# Capacitive sensing
GRAB_THRESHOLD = 500
RELEASE_THRESHOLD = 300
GRAB_DEBOUNCE_MS = 150
GRAB_GLITCH_MS = 250   # dropout bridged while confirming a grab
GRAB_MIN_HITS = 3     # highs needed within the debounce window
RELEASE_DEBOUNCE_MS = 450

# Hook sensing
HOOK_DEBOUNCE_MS = 300
HOOK_REGRAB_GUARD_MS = 600   # no regrab/miss this soon after hook contact
UNHOOK_DEBOUNCE_MS = 100

# Throw cycle
MIN_FLIGHT_MS = 250
THROW_TIMEOUT_MS = 3000
POST_THROW_LOCKOUT_MS = 250

# Triple-tap reset
RESET_TAPS = 3
RESET_WINDOW_MS = 2000
RESET_CONTACT_MS = 150
RESET_RELEASE_MS = 150

# Attract mode
ATTRACT_PIXELS = 22
ATTRACT_INTERVAL_MS = 180
ATTRACT_IDLE_MS = 5 * 60 * 1000

ATTRACT_MAIN = 0.07
ATTRACT_NEIGHBOR = 0.018
ATTRACT_OUTER = 0.006

ATTRACT_COLORS = (
    (255, 0, 0),
    (255, 255, 255),
    (0, 0, 255)
)

# Score pixels: the next free pixel shows capacitance as purple
# brightness (log scale, us)
SCORE_PIXELS = 22
CAP_PIXEL_MIN_US = 50
CAP_PIXEL_MAX_US = 5000
CAP_PIXEL_FLOOR = 0.05

# Debug log (set LOG_ENABLED = False to turn off)
LOG_ENABLED = True
LOG_FILE = "game_log.csv"
LOG_MIN_FREE_BYTES = 150000   # stop logging (never delete) below this
LOG_FLUSH_MS = 1000           # lose at most ~1 s if unplugged
LOG_IDLE_MS = 1000            # idle rows are thinned to one per second

# Loop timing
SAMPLE_INTERVAL_MS = 20
DISPLAY_INTERVAL_MS = 200
PIXEL_INTERVAL_MS = 50
BLINK_INTERVAL_MS = 250

# ------------------------------------------
# STATES
# ------------------------------------------

READY = 0
HELD = 1
IN_FLIGHT = 2
LANDED = 3
WAIT_RESET = 4
WAIT_RELEASE = 5
COMPLETE = 6
GAME_SHOTS = 21

STATE_NAMES = {
    READY: "READY",
    HELD: "HELD",
    IN_FLIGHT: "IN FLIGHT",
    LANDED: "LANDED",
    WAIT_RESET: "WAIT RESET",
    COMPLETE: "COMPLETE",
    WAIT_RELEASE: "WAIT RELEASE"
}

# ------------------------------------------
# GAME VARIABLES
# ------------------------------------------

throws = 0
hits = 0
misses = 0
history = []
last_completed = None
previous_completed = None
completed_held = False
records = Records()

state = READY
hooked = False

touch_candidate_since = None
touch_last_high = None
touch_high_count = 0
last_contact_time = None
hook_candidate_since = None
unhook_candidate_since = None

throw_started = None

score_boot = __import__("binascii").hexlify(os.urandom(8)).decode()
score_event = 0
score_sound = None
last_event = "SYSTEM READY"
last_cap = None
cap_baseline = None  # Diagnostic idle estimate only; never used for scoring.
last_contact = False

now = time.ticks_ms()

last_display = now
last_pixel_update = now
last_attract_update = now

# Start in attract mode
last_activity = time.ticks_add(
    now, -ATTRACT_IDLE_MS
)

attract_position = 0
attract_color_index = 0

# Reset gesture tracking
reset_tap_count = 0
reset_first_tap = None
reset_contact_since = None
reset_release_since = None
reset_contact_latched = False
reset_armed = True

led.off()
pixels.fill(OFF)
pixels.write()


# ==========================================
# SENSOR FUNCTIONS
# ==========================================

def read_touch():
    drive.init(Pin.OUT, value=0)
    sense.init(Pin.OUT, value=0)
    time.sleep_ms(10)

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
    drive.init(Pin.IN)
    sense.init(Pin.IN, Pin.PULL_UP)
    time.sleep_us(200)

    contact = sense.value() == 0

    sense.init(Pin.IN)
    drive.init(Pin.OUT, value=0)

    return contact


# A held ring reads in bursts (e.g. 1700, 30, 1700, 7000, 50) rather than
# steadily, so a grab is confirmed by repeated highs with short dropouts
# bridged, not by an unbroken run of highs.
def grab_confirmed(cap, now):
    global touch_candidate_since, touch_last_high, touch_high_count

    if cap is not None and cap >= GRAB_THRESHOLD:
        if touch_candidate_since is None:
            touch_candidate_since = now
            touch_high_count = 0

        touch_last_high = now
        touch_high_count += 1

        return (
            touch_high_count >= GRAB_MIN_HITS
            and time.ticks_diff(
                now, touch_candidate_since
            ) >= GRAB_DEBOUNCE_MS
        )

    if (
        touch_candidate_since is not None
        and time.ticks_diff(now, touch_last_high) > GRAB_GLITCH_MS
    ):
        touch_candidate_since = None

    return False


# ==========================================
# RESET HANDLING
# ==========================================

def reset_game(flash=True, preserve_records=True):
    global throws, hits, misses, history
    global state, hooked, completed_held
    global touch_candidate_since, touch_last_high, touch_high_count
    global last_contact_time
    global hook_candidate_since
    global unhook_candidate_since
    global throw_started
    global last_event, last_activity
    global reset_tap_count, reset_first_tap
    global reset_contact_since, reset_release_since
    global reset_contact_latched, reset_armed
    global attract_position, attract_color_index

    if preserve_records:
        records.reset()

    throws = 0
    hits = 0
    misses = 0
    history = []

    state = WAIT_RELEASE
    hooked = False
    completed_held = False

    touch_candidate_since = None
    touch_last_high = None
    touch_high_count = 0
    last_contact_time = None
    hook_candidate_since = None
    unhook_candidate_since = None

    throw_started = None

    reset_tap_count = 0
    reset_first_tap = None
    reset_contact_since = None
    reset_release_since = None
    reset_contact_latched = False
    reset_armed = False

    attract_position = 0
    attract_color_index = 0

    # Attract immediately after reset
    last_activity = time.ticks_add(
        time.ticks_ms(), -ATTRACT_IDLE_MS
    )

    last_event = "GAME RESET!"
    led.off()

    if not flash:
        return

    for _ in range(3):
        pixels.fill(WHITE)
        pixels.write()
        time.sleep_ms(120)

        pixels.fill(OFF)
        pixels.write()
        time.sleep_ms(120)


def update_reset_gesture(now, contact):
    global reset_tap_count, reset_first_tap
    global reset_contact_since, reset_release_since
    global reset_contact_latched, reset_armed

    # Allow reset while held, but not during flight
    if state == IN_FLIGHT:
        reset_tap_count = 0
        reset_first_tap = None
        reset_contact_since = None
        reset_release_since = None
        reset_contact_latched = False
        reset_armed = not contact
        return False

    # Expire incomplete sequence
    if reset_first_tap is not None:
        if time.ticks_diff(
            now, reset_first_tap
        ) > RESET_WINDOW_MS:
            reset_tap_count = 0
            reset_first_tap = None

    if contact:
        reset_release_since = None

        if not reset_armed or reset_contact_latched:
            return False

        if reset_contact_since is None:
            reset_contact_since = now

        elif time.ticks_diff(
            now, reset_contact_since
        ) >= RESET_CONTACT_MS:
            reset_contact_latched = True
            reset_armed = False

            if reset_tap_count == 0:
                reset_first_tap = now

            reset_tap_count += 1

            if reset_tap_count >= RESET_TAPS:
                reset_game()
                return True

    else:
        reset_contact_since = None

        if not reset_armed:
            if reset_release_since is None:
                reset_release_since = now

            elif time.ticks_diff(
                now, reset_release_since
            ) >= RESET_RELEASE_MS:
                reset_armed = True
                reset_contact_latched = False

    return False


# ==========================================
# NEOPIXELS - GAME
# ==========================================

def cap_level():
    # 0.0-1.0 on a log scale (CAP_PIXEL_MIN_US..CAP_PIXEL_MAX_US)
    if last_cap is None:
        return 0.0

    fraction = (
        math.log(max(last_cap, CAP_PIXEL_MIN_US) / CAP_PIXEL_MIN_US)
        / math.log(CAP_PIXEL_MAX_US / CAP_PIXEL_MIN_US)
    )
    return min(fraction, 1.0)


def update_pixels(now):
    global last_pixel_update

    if time.ticks_diff(
        now, last_pixel_update
    ) < PIXEL_INTERVAL_MS:
        return

    last_pixel_update = now

    pixels.fill(OFF)

    blinking = (
        (now // BLINK_INTERVAL_MS) % 2
    ) == 0

    # Finished throws: locked green (hit) / red (miss)
    for i, result in enumerate(history):
        pixels[i % SCORE_PIXELS] = GREEN if result else RED

    # The next score location shows the live status
    slot = len(history) % SCORE_PIXELS

    if state == IN_FLIGHT:
        pixels[slot] = BLUE

    elif hooked or state == LANDED:
        # Ring still on the hook: next location blinks white until grabbed
        pixels[slot] = WHITE if blinking else OFF

    elif last_cap is not None:
        # Purple brightness follows capacitance
        pixels[slot] = scale_color(
            PURPLE,
            CAP_PIXEL_FLOOR
            + (1 - CAP_PIXEL_FLOOR) * cap_level()
        )

    pixels.write()


# ==========================================
# NEOPIXELS - ATTRACT
# ==========================================

def scale_color(rgb, brightness):
    return tuple(
        int(c * brightness) for c in rgb
    )


def update_attract(now):
    global attract_position
    global attract_color_index
    global last_attract_update

    if time.ticks_diff(
        now, last_attract_update
    ) < ATTRACT_INTERVAL_MS:
        return

    last_attract_update = now

    pixels.fill(OFF)

    base = ATTRACT_COLORS[
        attract_color_index
    ]

    limit = min(
        ATTRACT_PIXELS, PIXEL_COUNT
    )

    # Main moving pixel
    pixels[attract_position] = scale_color(
        base, ATTRACT_MAIN
    )

    # Dim pixels ahead and behind
    for offset, intensity in (
        (-1, ATTRACT_NEIGHBOR),
        (1, ATTRACT_NEIGHBOR),
        (-2, ATTRACT_OUTER),
        (2, ATTRACT_OUTER)
    ):
        index = attract_position + offset

        if 0 <= index < limit:
            pixels[index] = scale_color(
                base, intensity
            )

    pixels.write()

    # Advance position
    attract_position += 1

    if attract_position >= limit:
        attract_position = 0
        attract_color_index = (
            attract_color_index + 1
        ) % len(ATTRACT_COLORS)


# ==========================================
# TERMINAL DASHBOARD
# ==========================================

def draw_dashboard(now, attracting):
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

    if state == IN_FLIGHT:
        elapsed = time.ticks_diff(
            now, throw_started
        )
        remaining = max(
            0,
            (THROW_TIMEOUT_MS - elapsed) / 1000
        )
        time_text = "{:.1f}s".format(remaining)
    else:
        time_text = "--"

    print("\033[H\033[2J", end="")
    print("+--------------------------------------+")
    print("|           RING THE BULL              |")
    print("+--------------------------------------+")
    print()
    print(" State:        {}".format(
        "ATTRACT MODE" if attracting
        else STATE_NAMES[state]
    ))
    print(" Capacitance:  {}".format(cap_text))
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
    print(" Time left:    {}".format(time_text))
    print()
    print(" Reset taps:   {}/{}".format(
        reset_tap_count, RESET_TAPS
    ))
    print(" Last event:   {}".format(last_event))
    print("+--------------------------------------+")


# ==========================================
# MAIN LOOP
# ==========================================

# Boot signature: 5 quick onboard LED blinks = firmware loaded, ready
for _ in range(5):
    led.on()
    time.sleep_ms(100)
    led.off()
    time.sleep_ms(100)

# Debug log: ms,state,cap_us,contact,hooked,event  (event only on change)
# Pull with: mpremote cp :game_log.csv .
log = None
log_buf = []
log_last_flush = time.ticks_ms()
log_last_event = None

log_last_row = time.ticks_ms()

def log_free():
    st = os.statvfs("/")
    return st[0] * st[3]

if LOG_ENABLED:
    log = open(LOG_FILE, "a")
    log_marked = False

# Optional network UI; failures leave the offline game running.
def web_status():
    return {
        "hits": hits, "misses": misses, "throws": throws,
        "state": STATE_NAMES[state], "history": history,
        "hook": last_contact, "complete": len(history) == GAME_SHOTS,
        "score_event": score_event, "score_sound": score_sound, "score_boot": score_boot,
        "last_completed": last_completed,
        "best": records.values[0], "longest_streak": records.values[1],
        "records_error": records.error,
        "can_undo": bool(history) and state != IN_FLIGHT,
    }


def sensor_status():
    return {
        "raw": last_cap, "baseline": cap_baseline,
        "delta": None if last_cap is None or cap_baseline is None else last_cap - cap_baseline,
        "grab_threshold": GRAB_THRESHOLD, "release_threshold": RELEASE_THRESHOLD,
        "grabbed": state == HELD or (state == COMPLETE and completed_held),
        "hook_contact": last_contact,
    }


def web_action(action):
    global history, throws, hits, misses, last_completed
    if action == 'reset':
        reset_game(flash=False)
        return True
    if action != 'undo' or not history or state == IN_FLIGHT:
        return False
    if len(history) == GAME_SHOTS:
        last_completed = previous_completed
    shortened = history[:-1]
    # Reuse the existing reset trackers; preserve the prior-games record baseline.
    reset_game(flash=False, preserve_records=False)
    history = shortened
    throws = len(history)
    hits = sum(history)
    misses = throws - hits
    records.observe(history, save=True)
    return True


ota_bench = False

def ota_idle():
    # Staging may continue through unconfirmed capacitance spikes, but never
    # through a confirmed grab, flight, contact, partial game, or sensor timeout.
    return (state in (READY, WAIT_RELEASE, COMPLETE) and (not history or len(history) == GAME_SHOTS)
            and not last_contact and not hooked and not completed_held
            and (last_cap is not None or (ota_bench and not history)))


def ota_safe():
    return (state in (READY, WAIT_RELEASE, COMPLETE) and (not history or len(history) == GAME_SHOTS)
            and not last_contact and not hooked and not completed_held
            and touch_candidate_since is None
            and ((last_cap is not None and last_cap <= RELEASE_THRESHOLD)
                 or (ota_bench and last_cap is None and not history)))


def ota_checkpoint():
    from ota_recovery import atomic_json
    records.pending = True
    records.flush(time.ticks_ms())
    if records.pending or records.error:
        raise OSError('Records checkpoint failed')
    atomic_json('ota_game.json', {
        'history': history, 'throws': throws, 'hits': hits, 'misses': misses,
        'last_completed': last_completed, 'previous_completed': previous_completed,
        'record_base': records.base, 'record_values': records.values,
    })


updater = None
try:
    from ota_recovery import load_state, confirm, atomic_json, STATE
    ota_boot = load_state()
    # A saved result remains available across activation and rollback. Ordinary
    # power cycles keep the original RAM-only game behavior after confirmation.
    if ota_boot.get('restore_pending'):
        import json
        with open('ota_game.json') as source:
            restored = json.load(source)
        history = restored['history']
        throws, hits, misses = restored['throws'], restored['hits'], restored['misses']
        last_completed, previous_completed = restored['last_completed'], restored['previous_completed']
        records.base = tuple(restored['record_base'])
        records.values = tuple(restored['record_values'])
        state = COMPLETE if len(history) == GAME_SHOTS else WAIT_RELEASE
        ota_boot['restore_pending'] = False
        atomic_json(STATE, ota_boot)
    with open('ota_config.json') as source:
        ota_config = __import__('json').load(source)
    ota_bench = ota_config.get('bench_mode') is True
    from ota_client import Updater
    import machine
    updater = Updater(ota_config, ota_checkpoint, machine.reset)
except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
    print('OTA unavailable:', exc)

ota_trial_start = time.ticks_ms()
ota_iterations = 0


ota_log_paused = False


def pause_ota_log():
    global log, log_buf, ota_log_paused
    if log is not None:
        if log_buf:
            log.write('\n'.join(log_buf) + '\n')
            log_buf = []
        log.flush()
        log.close()
        log = None
        ota_log_paused = True


def ota_command(action):
    if updater is None or not ota_safe():
        return False
    try:
        # LittleFS statvfs can count an open append file twice. Close only while
        # staging between games, preserving the log and resuming it afterwards.
        pause_ota_log()
        return updater.command(action, True)
    except OSError as exc:
        updater.error = 'Log checkpoint failed: ' + str(exc)
        return False


def ota_status():
    if updater:
        data = updater.status()
        data['bench_mode'] = ota_bench
        return data
    return {'update_status': 'disabled', 'current_version': 'USB / unversioned',
                                           'available_version': None}


web = None
try:
    from web_server import WebServer
    web = WebServer(web_status, action=web_action, diagnostics=sensor_status,
                    ota=updater, ota_command=ota_command, ota_status=ota_status)
except Exception as exc:
    print("Web UI unavailable:", exc)


while True:
    now = time.ticks_ms()
    resolved_before = len(history)

    contact = read_hook()
    last_contact = contact
    if contact:
        last_contact_time = now

    # Reset gesture
    if update_reset_gesture(now, contact):
        continue

    # Hook debounce
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
                last_activity = now
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
                last_activity = now

    # Capacitive sensing
    cap = None
    if not contact and not hooked:
        cap = read_touch()
    last_cap = cap
    if cap is not None or contact or hooked:
        ota_bench = False
    # Observe only released, ungrounded samples; do not alter sensor thresholds.
    if (state in (READY, WAIT_RELEASE, WAIT_RESET) and not contact and not hooked
            and cap is not None and cap <= RELEASE_THRESHOLD):
        cap_baseline = cap if cap_baseline is None else cap_baseline + (cap - cap_baseline) / 16

    # Game logic
    if state == READY:
        if grab_confirmed(cap, now):
            state = HELD
            touch_candidate_since = None
            last_activity = now
            last_event = "GRABBED"

    elif state == HELD:
        if cap is not None and cap <= RELEASE_THRESHOLD:
            if touch_candidate_since is None:
                touch_candidate_since = now

            elif time.ticks_diff(
                now, touch_candidate_since
            ) >= RELEASE_DEBOUNCE_MS:
                state = IN_FLIGHT
                touch_candidate_since = None

                if len(history) == GAME_SHOTS:
                    # Keep the final card undoable until the next actual throw.
                    # Carry records forward without dropping this release.
                    records.reset()
                    throws = hits = misses = 0
                    history = []
                throws += 1
                throw_started = now
                last_activity = now
                last_event = "THROWN #{}".format(throws)
        else:
            touch_candidate_since = None

    elif state == IN_FLIGHT:
        elapsed = time.ticks_diff(
            now, throw_started
        )

        # Hook takes priority
        if hooked:
            hits += 1
            history.append(True)
            state = LANDED
            last_activity = now
            last_event = "HIT! Total: {}".format(hits)

        # Regrab ends previous throw as a miss
        elif elapsed >= MIN_FLIGHT_MS:
            # A ring bouncing on the hook reads high between contacts and
            # looks like a regrab; wait for the hook debounce to decide
            if (
                last_contact_time is not None
                and time.ticks_diff(now, last_contact_time)
                < HOOK_REGRAB_GUARD_MS
            ):
                touch_candidate_since = None

            elif grab_confirmed(cap, now):
                misses += 1
                history.append(False)
                state = HELD
                touch_candidate_since = None
                last_activity = now
                last_event = "MISS - REGRABBED"

        # Fallback timeout
        if (
            state == IN_FLIGHT
            and elapsed >= THROW_TIMEOUT_MS
        ):
            misses += 1
            history.append(False)
            state = WAIT_RESET
            touch_candidate_since = None
            last_activity = now
            last_event = "MISS - TIMEOUT"

    elif state == LANDED:
        if not hooked:
            state = WAIT_RESET
            last_event = "RING REMOVED"

    elif state == WAIT_RESET:
        if time.ticks_diff(
            now, throw_started
        ) >= POST_THROW_LOCKOUT_MS:
            if grab_confirmed(cap, now):
                state = HELD
                touch_candidate_since = None
                last_activity = now
                last_event = "GRABBED"

    elif state == COMPLETE:
        # A re-catch on shot 21 already confirmed the next physical grab.
        if completed_held or grab_confirmed(cap, now):
            completed_held = False
            state = HELD
            touch_candidate_since = None
            last_activity = now
            last_event = "NEXT GAME - RELEASE TO THROW"

    elif state == WAIT_RELEASE:
        if (
            not contact
            and not hooked
            and cap is not None
            and cap <= RELEASE_THRESHOLD
        ):
            if touch_candidate_since is None:
                touch_candidate_since = now

            elif time.ticks_diff(
                now, touch_candidate_since
            ) >= RELEASE_DEBOUNCE_MS:
                state = READY
                touch_candidate_since = None
                last_event = "READY FOR NEW GAME"
        else:
            touch_candidate_since = None

    if len(history) != resolved_before:
        if history and len(history) > resolved_before:
            score_event += 1
            score_sound = 'complete' if len(history) == GAME_SHOTS else ('hit' if history[-1] else 'miss')
        if len(history) == GAME_SHOTS:
            previous_completed = last_completed
            last_completed = {
                "throws": throws, "hits": hits, "misses": misses,
                "history": history[:],
            }
            completed_held = state == HELD
            state = COMPLETE
            last_event = "GAME COMPLETE: {}/{}".format(hits, GAME_SHOTS)
        records.observe(history, save=len(history) == GAME_SHOTS)

    # LED: on while the ring is electrically touching the hook
    # (raw contact, not debounced), so a bad ring/wire joint is visible
    led.value(1 if contact else 0)

    # Attract mode after 5 minutes inactivity
    attracting = (
        state in (
            READY,
            WAIT_RELEASE,
            WAIT_RESET
        )
        and time.ticks_diff(
            now, last_activity
        ) >= ATTRACT_IDLE_MS
    )

    if attracting:
        update_attract(now)
    else:
        update_pixels(now)

    draw_dashboard(now, attracting)

    # Nothing wired (timeout with no contact/hook): don't log at all
    connected = (
        last_cap is not None or contact or hooked
    )

    # Full rate during activity; idle (READY, untouched) thinned to 1/s
    busy = (
        state != READY or contact or hooked
        or (last_cap is not None and last_cap > RELEASE_THRESHOLD)
        or last_event != log_last_event
    )

    if log is not None and connected and (
        busy or time.ticks_diff(now, log_last_row) >= LOG_IDLE_MS
    ):
        log_last_row = now
        if not log_marked:
            log_buf.append("# boot")
            log_marked = True
        log_buf.append("{},{},{},{},{},{}".format(
            now,
            STATE_NAMES[state],
            "T" if last_cap is None else last_cap,
            1 if contact else 0,
            1 if hooked else 0,
            last_event if last_event != log_last_event else ""
        ))
        log_last_event = last_event

        if time.ticks_diff(now, log_last_flush) >= LOG_FLUSH_MS:
            data = "\n".join(log_buf) + "\n"
            log.write(data)
            log.flush()
            log_buf = []
            log_last_flush = now

            if log_free() < LOG_MIN_FREE_BYTES:
                log.close()
                log = None

    if web is not None:
        web.poll()

    if state in (COMPLETE, WAIT_RELEASE):
        records.flush(time.ticks_ms())

    if updater is not None:
        if ota_config.get('bench_mode') and not ota_bench and ota_safe():
            # Persist automatic bench exit once, between games; retry failures safely.
            try:
                updated_config = dict(ota_config)
                updated_config['bench_mode'] = False
                atomic_json('ota_config.json', updated_config)
                ota_config = updated_config
            except OSError:
                updater.error = 'Could not persist bench-mode exit'
        idle = ota_idle()
        # Keep a verified release ready while a brief candidate clears. Actual
        # play still pauses it; activation keeps the stricter released-ring gate.
        if not idle or updater.phase != 'ready' or ota_safe():
            updater.poll(idle)
        if ota_log_paused and updater.phase in ('idle', 'available', 'error', 'paused'):
            try:
                log = open(LOG_FILE, 'a')
            except OSError:
                log = None
            ota_log_paused = False
    # Confirmation depends on real sensor-loop progress, never on Wi-Fi availability.
    if 'ota_watchdog' in globals():
        ota_iterations += 1
        if ota_iterations >= 30 and time.ticks_diff(time.ticks_ms(), ota_trial_start) >= 30000 and ota_safe():
            if ota_boot['phase'] == 'trial':
                ota_boot = confirm()
                if updater is not None:
                    updater.boot = ota_boot
        ota_watchdog.feed()

    time.sleep_ms(SAMPLE_INTERVAL_MS)
