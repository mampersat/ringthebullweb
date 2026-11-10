"""USB-installed recovery boundary. Never included in application releases."""
import json
import os

FILES = ('main.py', 'web_server.py', 'records.py')
STATE = 'ota_state.json'


def atomic_json(path, value):
    with open(path + '.tmp', 'w') as target:
        json.dump(value, target)
        target.flush()
    if hasattr(os, 'sync'):
        os.sync()
    os.rename(path + '.tmp', path)
    if hasattr(os, 'sync'):
        os.sync()


def load_state():
    # Fail closed: never guess which slot is complete if the pointer is damaged.
    with open(STATE) as source:
        state = json.load(source)
    if state.get('active') not in ('ota_a', 'ota_b'):
        raise ValueError('Invalid OTA state')
    if state.get('previous') not in (None, 'ota_a', 'ota_b'):
        raise ValueError('Invalid previous slot')
    if state.get('phase') not in ('stable', 'pending', 'trial'):
        raise ValueError('Invalid OTA phase')
    return state


def prepare_boot():
    state = load_state()
    if state['phase'] == 'trial':
        # Any restart before confirmation, including power loss, rejects the trial.
        state.update(active=state['previous'], previous=None, phase='stable',
                     version=state['previous_version'], restore_pending=True, error='Trial boot not confirmed; rolled back')
        atomic_json(STATE, state)
    elif state['phase'] == 'pending':
        state['phase'] = 'trial'
        atomic_json(STATE, state)
    return state


def confirm():
    state = load_state()
    if state['phase'] == 'trial':
        state.update(phase='stable', error=None)
        atomic_json(STATE, state)
    return state


def activate(slot, version):
    state = load_state()
    if state['phase'] != 'stable' or slot == state['active'] or slot not in ('ota_a', 'ota_b'):
        raise ValueError('Unsafe activation')
    state.update(previous=state['active'], previous_version=state['version'],
                 active=slot, version=version, phase='pending', restore_pending=True, error=None)
    atomic_json(STATE, state)


def run():
    # USB-only maintenance escape hatch, outside the application release set.
    try:
        os.stat('ota_maintenance')
        print('OTA USB maintenance: remove ota_maintenance and reset to play')
        return
    except OSError as exc:
        if exc.args[0] != 2:
            raise
    import sys
    import machine
    state = prepare_boot()
    # WDT stays active after confirmation; only a completed game-loop pass feeds it.
    watchdog = machine.WDT(timeout=8000)
    sys.path.insert(0, state['active'])
    try:
        with open(state['active'] + '/main.py') as source:
            application = compile(source.read(), state['active'] + '/main.py', 'exec')
        exec(application,
             {'__name__': '__main__', 'ota_watchdog': watchdog})
    except KeyboardInterrupt:
        watchdog.feed()  # Give the USB operator eight seconds to request maintenance.
        raise
    except BaseException as exc:
        print('Application stopped:', exc)
    machine.reset()
