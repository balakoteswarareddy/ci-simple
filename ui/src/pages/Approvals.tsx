import { useEffect, useState } from "react";
import { api } from "../api";
import type { RunSummary } from "../types";
import StatusBadge from "../components/StatusBadge";

export default function Approvals() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = async () => {
    try {
      setRuns((await api.pendingApprovals()).pending);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const decide = async (id: string, decision: string) => {
    setBusy(id + decision);
    try {
      await api.decide(id, decision, reasons[id] || "");
      await load();
    } catch (e) {
      setError(String(e));
    }
    setBusy("");
  };

  return (
    <div>
      <h1 className="page-title">Approvals</h1>
      <p className="page-sub">Runs paused before any mutation. Decisions are recorded immutably.</p>
      {error && <div className="alert error">{error}</div>}
      {!runs.length && <div className="card muted">Queue empty — nothing waiting for review.</div>}
      {runs.map((r) => (
        <div className="card" key={r.id}>
          <div className="run-head">
            <h2><a href={`#/runs/${r.id}`}>{r.id}</a></h2>
            <StatusBadge value={r.risk_level || "low"} />
          </div>
          <p className="mono muted">{r.repo_url} · {r.platform}</p>
          <p>{r.request}</p>
          <div className="field">
            <input
              className="input"
              placeholder="reason (optional, recorded)"
              value={reasons[r.id] || ""}
              onChange={(e) => setReasons({ ...reasons, [r.id]: e.target.value })}
            />
          </div>
          <div className="btn-row">
            <button className="btn primary" disabled={!!busy} onClick={() => decide(r.id, "approve")}>
              {busy === r.id + "approve" ? "…" : "Approve"}
            </button>
            <button className="btn danger" disabled={!!busy} onClick={() => decide(r.id, "reject")}>
              {busy === r.id + "reject" ? "…" : "Reject"}
            </button>
            <a className="btn" href={`#/runs/${r.id}`}>Inspect run</a>
          </div>
        </div>
      ))}
    </div>
  );
}
