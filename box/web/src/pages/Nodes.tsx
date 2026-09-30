import { useEffect, useState } from "react";
import { apiGet } from "../lib/api";
import type { Node } from "../lib/types";
import { subscribe } from "../lib/ws";

function ago(ts: number | null): string {
  if (ts == null) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 90 ? `${s}s ago` : `${Math.round(s / 60)}m ago`;
}

export default function Nodes() {
  const [nodes, setNodes] = useState<Node[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => apiGet<Node[]>("/api/nodes").then(setNodes, (e: Error) => setError(e.message));
    load();
    return subscribe("node.health", load);
  }, []);

  if (error) return <p role="alert">Could not load nodes: {error}</p>;
  if (!nodes) return <p>Loading…</p>;
  return (
    <>
      <h1>Nodes</h1>
      {nodes.length === 0 ? (
        <p>No nodes have reported yet. Point your ESPresense nodes at this box's MQTT broker.</p>
      ) : (
        <table className="panel">
          <thead>
            <tr><th>Node</th><th>IP</th><th>Wi-Fi</th><th>Last seen</th><th>Nearby devices</th><th>Version</th></tr>
          </thead>
          <tbody>
            {nodes.map((n) => (
              <tr key={n.id}>
                <td><span className={`dot ${n.online ? "ok" : "down"}`} />{n.name ?? n.id}</td>
                <td>{n.ip ?? "–"}</td>
                <td>{n.wifi_rssi != null ? `${n.wifi_rssi} dBm` : "–"}</td>
                <td>{ago(n.last_seen)}</td>
                <td>{n.nearby_devices}</td>
                <td>{n.version ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
