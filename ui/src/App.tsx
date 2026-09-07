import { useEffect, useState } from "react";
import Dashboard from "./pages/Dashboard";
import NewRun from "./pages/NewRun";
import RunDetail from "./pages/RunDetail";
import Approvals from "./pages/Approvals";
import Knowledge from "./pages/Knowledge";
import Policies from "./pages/Policies";
import Health from "./pages/Health";

const NAV = [
  { hash: "#/", label: "Runs", match: (h: string) => h === "#/" || h === "" || h.startsWith("#/runs/") },
  { hash: "#/new", label: "＋ New run", match: (h: string) => h === "#/new" },
  { hash: "#/approvals", label: "Approvals", match: (h: string) => h === "#/approvals" },
  { hash: "#/knowledge", label: "Knowledge", match: (h: string) => h.startsWith("#/knowledge") },
  { hash: "#/policies", label: "Policies", match: (h: string) => h.startsWith("#/policies") },
  { hash: "#/health", label: "Health", match: (h: string) => h.startsWith("#/health") },
];

export default function App() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  const [apiKey, setApiKey] = useState(localStorage.getItem("ci-agent-api-key") || "");
  const [actor, setActor] = useState(localStorage.getItem("ci-agent-actor") || "");

  useEffect(() => {
    const onHash = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (apiKey) localStorage.setItem("ci-agent-api-key", apiKey);
    else localStorage.removeItem("ci-agent-api-key");
  }, [apiKey]);

  useEffect(() => {
    if (actor) localStorage.setItem("ci-agent-actor", actor);
    else localStorage.removeItem("ci-agent-actor");
  }, [actor]);

  let page: JSX.Element = <Dashboard />;
  if (hash === "#/new") page = <NewRun />;
  else if (hash === "#/approvals") page = <Approvals />;
  else if (hash.startsWith("#/knowledge")) page = <Knowledge />;
  else if (hash.startsWith("#/policies")) page = <Policies />;
  else if (hash.startsWith("#/health")) page = <Health />;
  else if (hash.startsWith("#/runs/")) page = <RunDetail id={hash.slice("#/runs/".length)} />;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          CI Agent <span>●</span>
        </div>
        {NAV.map((n) => (
          <a key={n.hash} href={n.hash} className={"nav-link" + (n.match(hash) ? " active" : "")}>
            {n.label}
          </a>
        ))}
        <div className="side-foot">
          API key
          <input
            type="password"
            placeholder="X-API-Key (if required)"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          Actor
          <input
            placeholder="approver identity"
            value={actor}
            onChange={(e) => setActor(e.target.value)}
          />
        </div>
      </aside>
      <main className="main">{page}</main>
    </div>
  );
}
