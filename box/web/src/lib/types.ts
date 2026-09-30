// Hand-written mirrors of the box API (conventions §10). Keep in sync with the pydantic models.
export type Health = { ok: boolean; version: string; relay: "connected" | "disabled" | "offline" };

export type SiteSettings = { tz: string; units: "ft" | "m"; home_name: string };

export type Node = {
  id: string;
  name: string | null;
  online: boolean;
  last_seen: number | null;
  ip: string | null;
  wifi_rssi: number | null;
  uptime_s: number | null;
  version: string | null;
  calib_json: string | null;
  placed: boolean;
  nearby_devices: number;
};

export type Tag = { id: number; pet_id: number; ibeacon_id: string; motion_ibeacon_id: string | null };
export type Pet = { id: number; name: string; species: string; tags: Tag[] };
export type TagCandidate = { ibeacon_id: string; node_id: string; rssi: number; last_seen: number };

export type BusEvent = { topic: string; data: Record<string, unknown> };
