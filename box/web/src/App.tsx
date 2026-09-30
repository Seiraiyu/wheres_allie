import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import Calibrate from "./pages/Calibrate";
import Data from "./pages/Data";
import Editor from "./pages/Editor";
import History from "./pages/History";
import Live from "./pages/Live";
import Nodes from "./pages/Nodes";
import Setup from "./pages/Setup";

export const PAGES = [
  { path: "live", label: "Live", icon: "◉", element: <Live /> },
  { path: "history", label: "History", icon: "↺", element: <History /> },
  { path: "editor", label: "Plan", icon: "▦", element: <Editor /> },
  { path: "nodes", label: "Nodes", icon: "⌖", element: <Nodes /> },
  { path: "calibrate", label: "Calibrate", icon: "◎", element: <Calibrate /> },
  { path: "data", label: "Data", icon: "⇩", element: <Data /> },
  { path: "setup", label: "Setup", icon: "⚙", element: <Setup /> },
];

export default function App() {
  return (
    <div className="shell">
      <nav className="rail" aria-label="Pages">
        {PAGES.map((p) => (
          <NavLink key={p.path} to={`/${p.path}`} title={p.label}>
            <span className="icon" aria-hidden="true">{p.icon}</span>
            {p.label}
          </NavLink>
        ))}
      </nav>
      <main className="page">
        <Routes>
          {PAGES.map((p) => (
            <Route key={p.path} path={`/${p.path}`} element={p.element} />
          ))}
          <Route path="*" element={<Navigate to="/live" replace />} />
        </Routes>
      </main>
    </div>
  );
}
