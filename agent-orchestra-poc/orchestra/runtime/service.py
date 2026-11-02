"""Service des runtimes : un fil par agent LLM ; réveil par WebSocket, rattrapage par /inbox/pending."""
import json
import logging
import queue
import threading
import time

from websockets.sync.client import connect

from orchestra.runtime.agent import AgentRunner
from orchestra.runtime.auditor import AuditorRunner
from orchestra.runtime.client import AgentClient, ClientError
from orchestra.runtime.settings import RuntimeSettings

log = logging.getLogger("orchestra.runtime")


class AgentWorker:
    def __init__(self, agent_id: str, settings: RuntimeSettings, stop: threading.Event):
        self.agent, self.s, self.stop = agent_id, settings, stop
        self.client = AgentClient(settings.gateway_url, settings.token(agent_id))
        cls = AuditorRunner if agent_id == "auditeur" else AgentRunner
        self.runner = cls(agent_id, self.client, settings)
        self.q: queue.Queue = queue.Queue()
        self.seen: set[str] = set()

    def enqueue(self, mid: str):
        if mid not in self.seen:
            self.seen.add(mid)
            self.q.put(mid)

    def _listen(self):
        url = f"{self.s.wake_url}/ws/wake?token={self.s.token(self.agent)}"
        while not self.stop.is_set():
            try:
                with connect(url, open_timeout=5) as ws:
                    for p in self.client.pending():          # rattrapage : réveils manqués pendant une déconnexion
                        self.enqueue(p["messageId"])
                    for raw in ws:
                        m = json.loads(raw)
                        if m.get("type") == "wake":
                            self.enqueue(m["messageId"])
            except Exception as e:
                if not self.stop.is_set():
                    log.warning("%s: wake-up channel unavailable (%s), retrying", self.agent, type(e).__name__)
                    self.stop.wait(2)

    def run(self):
        threading.Thread(target=self._listen, daemon=True).start()
        while not self.stop.is_set():
            try:
                mid = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            t0 = time.time()
            status = self.runner.handle(mid)
            log.info("%s: message %s -> %s (%.1f s)", self.agent, mid[:12], status, time.time() - t0)


def run_all(settings: RuntimeSettings):
    stop = threading.Event()
    threads = [threading.Thread(target=AgentWorker(a, settings, stop).run, name=a, daemon=True) for a in settings.agents]
    for t in threads:
        t.start()
    log.info("runtimes started: %s (the KG bridge is a rule-based agent carried by the CDC consumer)", ", ".join(settings.agents))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop.set()
