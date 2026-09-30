import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import Nodes from "./Nodes";

vi.mock("../lib/ws", () => ({ subscribe: () => () => {} }));

afterEach(() => vi.unstubAllGlobals());

test("lists nodes from /api/nodes with health", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify([
        { id: "loft", name: null, online: false, last_seen: null, ip: null, wifi_rssi: null,
          uptime_s: null, version: null, calib_json: null, placed: false, nearby_devices: 0 },
        { id: "office", name: null, online: true, last_seen: Date.now() / 1000, ip: "192.168.5.232",
          wifi_rssi: -60, uptime_s: 5, version: "v4.0.6", calib_json: null, placed: false,
          nearby_devices: 3 },
      ]),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(<Nodes />);
  expect(await screen.findByText("192.168.5.232")).toBeTruthy();
  expect(screen.getByText("loft")).toBeTruthy();
  expect(screen.getByText("never")).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith("/api/nodes", expect.anything());
});

test("apiGet throws ApiError with status", async () => {
  const { apiGet, ApiError } = await import("../lib/api");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "pet not found" }), { status: 404 })));
  const err = await apiGet("/pets/9").then(() => null, (e: InstanceType<typeof ApiError>) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err?.status).toBe(404);
  expect(err?.message).toContain("pet not found");
});
