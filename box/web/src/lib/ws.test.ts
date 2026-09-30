import { afterEach, expect, test, vi } from "vitest";

class FakeWs {
  static last: FakeWs | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeWs.last = this;
  }
  close() {
    this.closed = true;
    this.onclose?.();
  }
  emit(topic: string, data: object) {
    this.onmessage?.({ data: JSON.stringify({ topic, data }) });
  }
}

afterEach(() => vi.unstubAllGlobals());

test("one shared socket, prefix routing, closes after last unsubscribe", async () => {
  vi.stubGlobal("WebSocket", FakeWs);
  const { subscribe } = await import("./ws");
  const nodes: string[] = [];
  const all: string[] = [];
  const offNodes = subscribe("node.", (topic, data) => nodes.push(`${topic}:${data.id}`));
  const offAll = subscribe("", (topic) => all.push(topic));
  const sock = FakeWs.last!;
  expect(sock.url).toMatch(/\/api\/ws$/);
  sock.emit("node.health", { id: "office" });
  sock.emit("reading", { rssi: -70 });
  expect(nodes).toEqual(["node.health:office"]);
  expect(all).toEqual(["node.health", "reading"]);
  offNodes();
  expect(sock.closed).toBe(false);
  offAll();
  expect(sock.closed).toBe(true);
});
