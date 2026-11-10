#!/usr/bin/env python3
"""Enter/leave USB maintenance on the Ring the Bull Pico; suspends the game."""
import argparse
from pathlib import Path
import time
from ampy.pyboard import Pyboard


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('enter','exit'))
    args=parser.parse_args()
    port=Path('/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_e66428c51fa06e28-if00')
    if not port.exists():
        parser.error('Ring the Bull USB identity not found')
    board=Pyboard(str(port));board.serial.timeout=.2;board.serial.write_timeout=3
    try:
        board.serial.write(b'\r\x03\x03');time.sleep(.15)
        board.serial.reset_input_buffer();board.serial.write(b'\r\x01')
        if not board.read_until(1,b'raw REPL; CTRL-B to exit\r\n',timeout=2).endswith(b'raw REPL; CTRL-B to exit\r\n'):
            raise RuntimeError('No raw REPL; reconnect USB and retry once')
        if args.mode=='enter':
            command="open('ota_maintenance','w').close();import machine;machine.reset()"
        else:
            command="import os,machine;os.remove('ota_maintenance');machine.reset()"
        board.exec_raw_no_follow(command)
    finally:
        board.close()
    print('USB maintenance',args.mode,'requested; verify device startup')


if __name__=='__main__':main()
