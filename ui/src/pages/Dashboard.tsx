import { useEffect, useState } from "react";
import { api } from "../api";
import type { RunSummary } from "../types";
import StatusBadge from "../components/StatusBadge";

const STATUSES = ["", "queued", "running", "awaiting_approval", "succeeded", "failed", "denied", "cancelled"];

export default function Dashboard() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const data = await api.listRuns(filter || undefined);
      setRuns(data.runs);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const count = (s: string) => runs.filter((r) => r.status === s).length;

  return (
    <div>
      <h1 className="page-title">Runs</h1>
      <p className="page-sub">Every pipeline generation, from request to evidence.</p>
      {error && <div className="alert error">{error}</div>}
      <div className="grid cols-4">
        <div className="card stat"><div className="num">{runs.length}</div><div className="lbl">total</div></div>
        <div className="card stat"><div className="num">{count("succeeded")}</div><div className="lbl">succeeded</div></div>
        <div className="card stat"><div className="num">{count("awaiting_approval")}</div><div className="lbl">awaiting approval</div></div>
        <div className="card stat"><div className="num">{count("failed") + count("denied")}</div><div className="lbl">failed / denied</div></div>
      </div>
      <div className="toolbar">
        <select className="input" style={{ width: 220 }} value={filter} onChange={(e) => setFilter(e.target.value)}>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s === "" ? "all statuses" : s}</option>
          ))}
        </select>
        <div className="spacer" />
        <a className="btn primary" href="#/new">＋ New run</a>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <table className="tbl">
          <thead>
            <tr><th>Run</th><th>Repository</th><th>Platform</th><th>Status</th><th>Risk</th><th>Updated</th></tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td className="mono"><a href={`#/runs/${r.id}`}>{r.id.slice(0, 12)}</a></td>
                <td className="short" title={r.repo_url}>{r.repo_url}</td>
                <td>{r.platform}</td>
                <td><StatusBadge value={r.status} /></td>
                <td><StatusBadge value={r.risk_level || "low"} /></td>
                <td className="muted">{new Date(r.updated_at).toLocaleString()}</td>
              </tr>
            ))}
            {!runs.length && <tr><td colSpan={6} className="muted">No runs yet — create one.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
