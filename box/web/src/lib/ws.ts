import type { BusEvent } from "./types";

// data is `any`: its shape depends on the topic (see Interface additions #5)
export type Handler = (topic: string, data: any) => void;
type Sub = { prefix: string; handler: Handler };

const subs = new Set<Sub>();
let ws: WebSocket | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let delay = 1000;

function open() {
  timer = undefined;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const sock = new WebSocket(`${proto}://${location.host}/api/ws`);
  ws = sock;
  sock.onopen = () => (delay = 1000);
  sock.onmessage = (m) => {
    const e = JSON.parse(m.data) as BusEvent;
    for (const s of subs) if (e.topic.startsWith(s.prefix)) s.handler(e.topic, e.data);
  };
  sock.onclose = () => {
    if (ws === sock) ws = null;
    if (subs.size === 0 || timer !== undefined) return;
    timer = setTimeout(open, delay);
    delay = Math.min(delay * 2, 30000);
  };
}

/** Receive box bus events whose topic starts with topicPrefix ("" = all). Returns unsubscribe. */
export function subscribe(topicPrefix: string, handler: Handler): () => void {
  const sub = { prefix: topicPrefix, handler };
  subs.add(sub);
  if (!ws && timer === undefined) open();
  return () => {
    subs.delete(sub);
    if (subs.size > 0) return;
    clearTimeout(timer);
    timer = undefined;
    ws?.close();
    ws = null;
  };
}
