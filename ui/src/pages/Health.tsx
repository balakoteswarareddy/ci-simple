import { useEffect, useState } from "react";
import { api } from "../api";
import JsonView from "../components/JsonView";

export default function Health() {
  const [ready, setReady] = useState<{ ready: boolean; checks: Record<string, unknown> } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.ready().then(setReady).catch((e) => setError(String(e)));
    const t = setInterval(() => api.ready().then(setReady).catch(() => undefined), 10000);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <h1 className="page-title">Health</h1>
      <p className="page-sub">Dependency status for the API, policy engine, knowledge and model.</p>
      {error && <div className="alert error">{error}</div>}
      {!ready && <p className="muted">Loading…</p>}
      {ready && (
        <>
          <div className={`alert ${ready.ready ? "ok" : "error"}`}>
            {ready.ready ? "Ready to serve." : "Not ready — see failing checks below."}
          </div>
          <div className="card"><JsonView data={ready.checks} /></div>
          <p className="muted">Prometheus metrics: <span className="mono">/metrics</span> · Liveness: <span className="mono">/healthz</span></p>
        </>
      )}
    </div>
  );
}
