"""Small atomic record checkpoint; no writes while a throw is being sensed."""
import json
import os
import time


class Records:
    def __init__(self, path='records.json'):
        self.path = path
        self.base = (0, 0)
        self.error = None
        try:
            with open(path) as source:
                data = json.load(source)
            values = (data['best'], data['streak'])
            if data.get('version') != 1 or any(type(v) is not int or not 0 <= v <= 21 for v in values):
                raise ValueError('Invalid records')
            self.base = values
        except OSError as exc:
            if exc.args[0] != 2:
                self.error = 'Records could not be loaded'
        except (ValueError, KeyError, TypeError):
            self.error = 'Invalid records file'
        self.values = self.base
        self.saved = self.base
        self.pending = False
        self.last_attempt = None

    def observe(self, history, save=False):
        streak = longest = 0
        for hit in history:
            streak = streak + 1 if hit else 0
            longest = max(longest, streak)
        self.values = (max(self.base[0], sum(history) if len(history) == 21 else 0),
                       max(self.base[1], longest))
        self.pending = self.pending or save

    def reset(self):
        self.base = self.values
        self.pending = True

    def flush(self, now):
        if not self.pending:
            return
        if self.values == self.saved:
            self.pending = False
            return
        if self.last_attempt is not None and time.ticks_diff(now, self.last_attempt) < 30000:
            return
        self.last_attempt = now
        try:
            with open(self.path + '.tmp', 'w') as target:
                json.dump({'version': 1, 'best': self.values[0], 'streak': self.values[1]}, target)
                target.flush()
            if hasattr(os, 'sync'):
                os.sync()
            # LittleFS rename replaces the checkpoint atomically. A failed write
            # leaves the previous file intact; an interrupted .tmp is ignored.
            os.rename(self.path + '.tmp', self.path)
            if hasattr(os, 'sync'):
                os.sync()
        except OSError:
            self.error = 'Records save failed; retrying'
            return
        self.saved = self.values
        self.pending = False
        self.last_attempt = None
        self.error = None
