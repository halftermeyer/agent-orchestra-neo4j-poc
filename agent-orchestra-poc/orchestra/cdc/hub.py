"""Synchronous broadcast of normalized events and wake-ups; WebSockets subscribe to it."""
import threading
from collections import deque


class Hub:
    def __init__(self, history: int = 200):
        self._event_cbs, self._wake_cbs = [], []
        self._lock = threading.Lock()
        self.history = deque(maxlen=history)

    def on_event(self, cb):
        with self._lock:
            self._event_cbs.append(cb)
        return cb

    def on_wake(self, cb):
        with self._lock:
            self._wake_cbs.append(cb)
        return cb

    def off(self, cb):
        with self._lock:
            for lst in (self._event_cbs, self._wake_cbs):
                if cb in lst:
                    lst.remove(cb)

    def publish(self, ev: dict):
        self.history.append(ev)
        for cb in list(self._event_cbs):
            cb(ev)

    def wake(self, agent_id: str, info: dict):
        for cb in list(self._wake_cbs):
            cb(agent_id, info)
