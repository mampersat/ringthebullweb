# CLAUDE.md

Developer guide for **Ring the Bull**, an electronic scorer for the pub game where a metal ring on a string is swung onto a metal hook. A Raspberry Pi Pico W (MicroPython) senses grab / release / hook contact / re-catch, keeps score, and shows status on a NeoPixel strip.

## Repository layout

| Path | What it is |
|---|---|
| `records.py` | Atomic best-score/streak checkpoints; no per-sample writes. |
| `web_server.py` | Optional Pico web scoreboard; nonblocking polling. |
| `main.py` | The entire Pico firmware: single file, runs a single event loop at import time (no `if __name__` guard, no functions to import). |
| `test_neopixel.py` | Standalone strip test (cycles R/G/B/off on GP28). Not part of the game. |
| `index.html`, `sw.js`, `manifest.json`, `icons/`, `vendor/`, `deploy.sh`, `scripts/`, `images/` | Separate phone **web score-keeper** (PWA, deployed to S3/CloudFront). Unrelated to the Pico firmware; don't mix the two when editing. |

## Firmware architecture (`main.py`)

Top to bottom: hardware setup → constants (`CONFIGURATION` section) → state constants → module-level globals → sensor functions → reset handling → pixel drawing → dashboard → `while True` main loop.

- Sensors: `read_touch()` (RC charge time in µs, `None` on 20 ms timeout), `read_hook()` (True if GP15 pulled to ground).
- Reset: `update_reset_gesture(now, contact)` (returns True when it triggered `reset_game()`), `reset_game()`.
- Display: `update_pixels(now)` (game), `update_attract(now)` + `scale_color()` (attract), `draw_dashboard(now, attracting)` (serial).
- All game state is module-level globals; functions mutate them via `global`. Keep that style.
- All timing uses `time.ticks_ms()` / `time.ticks_diff()` (wrap-safe). Never compare ticks directly.

Main loop order each iteration: `read_hook()` → reset gesture (`continue` if reset fired) → hook/unhook debounce → `read_touch()` (only when not in contact and not `hooked`) → state machine → onboard LED → attract-vs-game pixels → dashboard → `sleep_ms(SAMPLE_INTERVAL_MS)`.

Note `read_touch()` itself blocks ~10 ms (discharge delay), so the real loop period is ~30+ ms, not 20.

## Pins

| GPIO | Physical | Purpose |
|---|---|---|
| GP14 | 19 | Cap-sense drive (via 1 MΩ to GP15) |
| GP15 | 20 | Cap-sense input / hook continuity; wired to the **ring** |
| GP28 | 34 | NeoPixel DIN |
| GND | e.g. 38 | Common ground; the **hook** connects to GND |
| VBUS | 40 | 5 V from USB; powers the NeoPixel strip |
| `"LED"` | onboard | 5 quick blinks at boot (firmware ready); then lit whenever `read_hook()` sees ring-to-hook contact (raw, not debounced), a quick check that the ring wire and hook ground are good |

GPIO number ≠ physical pin number. Double-check orientation when wiring.

## Sensing principles

**Capacitive grab** (`read_touch`): drive GP14 and GP15 low for 10 ms to discharge, make GP15 a floating input, drive GP14 high, time until GP15 reads high through the 1 MΩ. A held ring adds body capacitance → longer time. Logged on the installed wiring (`diag_capacitance.py`): untouched 52–117 µs, held ~1,100–6,000 µs (transitions briefly dip to ~200). `GRAB_THRESHOLD = 500`, `RELEASE_THRESHOLD = 300` (hysteresis). The original prototype values (80/70) sat inside the untouched range of the long wire run. The value is a relative timing, not farads.

**Hook contact** (`read_hook`): GP14 → input, GP15 → input with pull-up, 200 µs settle, LOW = ring touching grounded hook; then pins are restored for cap-sensing. The hook needs no switch or modification.

## State machine

States: `READY`, `HELD`, `IN_FLIGHT`, `LANDED`, `WAIT_RESET`, `WAIT_RELEASE`, `COMPLETE`.
The 21st resolved throw enters COMPLETE; sensing/LEDs/reset continue but no new throws count.

- `READY` → `HELD`: cap ≥ `GRAB_THRESHOLD` for `GRAB_DEBOUNCE_MS`.
- `HELD` → `IN_FLIGHT`: cap ≤ `RELEASE_THRESHOLD` for `RELEASE_DEBOUNCE_MS`; `throws += 1`.
- `IN_FLIGHT`:
  - `hooked` → hit, `LANDED` (**hook is checked first and wins over regrab**).
  - after `MIN_FLIGHT_MS` and `HOOK_REGRAB_GUARD_MS` since the last hook contact, cap ≥ grab for `GRAB_DEBOUNCE_MS` → miss, back to `HELD` ("MISS - REGRABBED").
  - `THROW_TIMEOUT_MS` → miss, `WAIT_RESET`.
- `LANDED` → `WAIT_RESET` when ring is unhooked.
- `WAIT_RESET` → `HELD`: after `POST_THROW_LOCKOUT_MS` (measured from `throw_started`), grab detected.
- `WAIT_RELEASE`: entered only by `reset_game()`; → `READY` once ring is released (not in contact, not hooked, cap ≤ release threshold for `RELEASE_DEBOUNCE_MS`).

## Timing constants (all in the CONFIGURATION block)

| Constant | Value | Purpose |
|---|---|---|
| `GRAB_DEBOUNCE_MS` | 150 | Confirm grab / regrab (via `grab_confirmed()`: ≥ `GRAB_MIN_HITS` = 3 highs within the window, dropouts up to `GRAB_GLITCH_MS` = 250 bridged, because a held ring reads in bursts) |
| `RELEASE_DEBOUNCE_MS` | 450 | Confirm release (throw); a held ring reads low for up to ~200 ms between bursts, so this must exceed that |
| `HOOK_DEBOUNCE_MS` | 300 | Contact must persist to count as hooked |
| `UNHOOK_DEBOUNCE_MS` | 100 | Confirm hook removal |
| `HOOK_REGRAB_GUARD_MS` | 600 | In flight, ignore a regrab within this long of any hook contact (a ring bouncing on the hook reads high between contacts and looks like a grab) |
| `MIN_FLIGHT_MS` | 250 | Ignore regrab right after release |
| `THROW_TIMEOUT_MS` | 3000 | Fallback miss if nothing happens |
| `POST_THROW_LOCKOUT_MS` | 250 | Ignore grabs just after a timeout miss |
| `RESET_TAPS` / `RESET_WINDOW_MS` | 3 / 2000 | Triple-tap reset gesture |
| `RESET_CONTACT_MS` / `RESET_RELEASE_MS` | 150 / 150 | Min contact / separation per tap |
| `ATTRACT_IDLE_MS` | 300000 | Idle time before attract mode |
| `ATTRACT_INTERVAL_MS` | 180 | Attract step rate |
| `SAMPLE_INTERVAL_MS` | 20 | Loop sleep |
| `DISPLAY_INTERVAL_MS` | 200 | Dashboard refresh (~5 Hz) |
| `PIXEL_INTERVAL_MS` | 50 | Game pixel refresh |
| `BLINK_INTERVAL_MS` | 250 | Blink half-period |

## NeoPixels

`PIXEL_COUNT = 100` in firmware (physical install is ~22 pixels), `BRIGHTNESS = 0.07` applied by `color()`. The strip is a score line: pixel *i* = throw *i+1*, locked green (hit) / red (miss), wrapping modulo `SCORE_PIXELS` (22). There is no separate state pixel. The next free location (`len(history)`) shows live status: **purple** with brightness = live `read_touch()` on a log scale (`CAP_PIXEL_MIN_US` 50 → `CAP_PIXEL_MAX_US` 5000, floor `CAP_PIXEL_FLOOR`; uses its own `PURPLE_BRIGHTNESS` = 0.15, independent of `BRIGHTNESS`); **blue** while `IN_FLIGHT`; **blinking white** while `hooked` / `LANDED` until the ring is grabbed again. Dark when capacitance can't be read and the ring isn't hooked.

**Attract mode**: uses the first `ATTRACT_PIXELS` (22). One pixel sweeps 0→21 with ±1 and ±2 dim neighbours (`ATTRACT_MAIN` 0.07, `ATTRACT_NEIGHBOR` 0.018, `ATTRACT_OUTER` 0.006), colour cycling red → white → blue. Active only in `READY` / `WAIT_RELEASE` / `WAIT_RESET` and after `ATTRACT_IDLE_MS` without activity. `last_activity` is pre-set to `now - ATTRACT_IDLE_MS` at boot and in `reset_game()` so attract starts immediately. The ±2 pixels at 0.6% quantize to ~1/255 and may be invisible.

## Reset gesture

Three contacts of ≥150 ms, each separated by ≥150 ms, within 2 s of the first. Allowed in any state except `IN_FLIGHT` (where the tracker is cleared). `reset_game()` clears counts/history/debounce trackers, sets `WAIT_RELEASE`, flashes white 3×, and re-enters attract. Note it blocks ~720 ms.

## Running and debugging

- Deploy: copy `records.py`, `web_server.py`, and `main.py` to the Pico (e.g. `mpremote cp records.py :records.py`, `mpremote cp web_server.py :web_server.py`, and `mpremote cp main.py :main.py` then `mpremote reset`, or Thonny). It then runs on boot.
- Try without installing: `mpremote run main.py`.
- Strip check: `mpremote run test_neopixel.py`.
- Debug log: `LOG_ENABLED` writes `game_log.csv` on the Pico (`ms,state,cap_us,contact,hooked,event`, buffered, appended across boots and never erased, flushed every 1 s, idle rows thinned to 1/s, nothing logged while the ring isn't wired (timeout with no contact), stops when < 150 KB flash is free). Pull with `mpremote cp :game_log.csv .`. Set False for normal use.
- Dashboard: connect a real serial terminal (`mpremote connect /dev/ttyACM0`, `screen /dev/ttyACM0 115200`, minicom). It uses ANSI clear/home (`\033[H\033[2J`), so IDE consoles without ANSI support will look garbled. It shows state, µs reading (or GROUNDED/TIMEOUT), hook/hooked, counts, throw time left, reset taps, last event.
- Targeted tests live in `tests/`: host mocks exercise the unchanged state machine, HTTP, and record storage; `pico_games.py` checks synthetic sequences with isolated records on-device. Physical sensing still requires hardware checks.
- To tune thresholds, watch the live µs reading with the ring untouched vs. held on the real installation.

## Safety and power

- Don't power a long strip from the Pico's 3V3(OUT). The strip's 5 V comes from the Pico's **VBUS** (pin 40), i.e. USB power, with common ground to the Pico GND.
- Data goes into DIN, not DOUT. A 330–470 Ω series resistor on data is recommended; a 74AHCT125-style level shifter may be needed for 5 V strips.
- Because the strip draws from USB via VBUS, total strip current is limited by the USB supply and the Pico's VBUS path; keep `BRIGHTNESS` low and don't raise `PIXEL_COUNT` casually. The USB supply rating isn't documented; don't assert specifics in docs.
- Keep `BRIGHTNESS` low; the 100-pixel config at full white is a big load.
- The ring/hook wires are only ever connected to GP15/GND through the sensing circuit; don't connect either to a higher voltage.

## Modifying code: preserve working behaviour

This is installed and working. When changing it:

- Don't alter thresholds, debounce times, the hook-over-regrab priority, or pin assignments without a hardware reason and a way to test on the device.
- Keep `read_touch()`/`read_hook()` pin restore order intact; they share GP14/GP15 and each leaves pins ready for the other.
- Keep `read_touch()` skipped while in contact or hooked (the ring is grounded; reading would be meaningless).
- Avoid long blocking calls in the loop (reset flash is the only deliberate one); blocking delays hurt debounce accuracy.
- Keep attract changes separate from game-display changes; the `attracting` condition gates which one draws.
- Update README and this file when constants or behaviour change.

## On-device web server

Implemented in `web_server.py`, with a read-only `web_status()` snapshot and one
`web.poll()` call at the end of each normal game iteration. Uses `select.poll(0)`,
nonblocking sockets, bounded client I/O, and optional gitignored `wifi_config.py`
(`WIFI_SSID`, `WIFI_PASSWORD`); otherwise reuses an existing station connection.
DHCP/IP configuration is left alone. POST undo/reset use `web_action()`, with
undo disabled during flight and both actions awaiting release. Records checkpoint
only changed values at completion/reset/undo in safe states. Undo retains the
prior-games baseline so current-game records can be retracted. Weekly streaks
are deferred without a synchronized clock. See README for deployment, endpoints, limits,
and hardware-only checks. Keep networking separate from sensing and game logic.
The S3 phone app remains separately deployed. Do not add network waits to the loop.

## Known limitations

Fixed thresholds (no auto-calibration); wire movement/nearby grounded objects shift readings; the 3 s timeout can score a miss while the ring still swings; current scores are RAM-only (records persist); single player; hook contact must last ≥300 ms to count; `PIXEL_COUNT` (100) exceeds the physical strip (~22).
