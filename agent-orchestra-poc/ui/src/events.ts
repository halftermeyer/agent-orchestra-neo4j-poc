import { loadSession } from "./api";
import type { StreamEvent } from "./types";

type Listener = (ev: StreamEvent) => void;

/** WebSocket client for the normalized stream, with reconnection. The same stream feeds the scene, the graph and the timeline. */
export class EventStream {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private statusListeners = new Set<(connected: boolean) => void>();
  private closed = false;
  private retry = 500;
  connected = false;
  readonly buffer: StreamEvent[] = [];

  constructor(private max = 500) {}

  start() {
    this.closed = false;
    this.open();
  }
  stop() {
    this.closed = true;
    this.ws?.close();
  }
  private open() {
    const s = loadSession();
    if (!s || this.closed) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/stream/ws/events?token=${encodeURIComponent(s.token)}`);
    this.ws = ws;
    ws.onopen = () => { this.retry = 500; this.setConnected(true); };
    ws.onmessage = (m) => {
      const ev = JSON.parse(m.data) as StreamEvent;
      this.buffer.push(ev);
      if (this.buffer.length > this.max) this.buffer.shift();
      this.listeners.forEach((l) => l(ev));
    };
    ws.onclose = () => {
      this.setConnected(false);
      if (!this.closed) setTimeout(() => this.open(), (this.retry = Math.min(this.retry * 2, 8000)));
    };
  }
  private setConnected(v: boolean) { this.connected = v; this.statusListeners.forEach((l) => l(v)); }
  subscribe(l: Listener) { this.listeners.add(l); return () => { this.listeners.delete(l); }; }
  onStatus(l: (c: boolean) => void) { this.statusListeners.add(l); return () => { this.statusListeners.delete(l); }; }
}
