import { useEffect, useState } from "react";
import { api } from "../api";
import JsonView from "../components/JsonView";
import StatusBadge from "../components/StatusBadge";

const SAMPLE = {
  intent: { platform: "github", capabilities: ["lint"], prohibited_tools: [], target_branch: "feature/x", deployment_target: "", publish: false },
  plan: {
    tools: [{ name: "ruff", version: "0.4.0", capability: "lint" }],
    actions: [{ uses: "actions/checkout@v4", pinned: true }],
    permissions: { contents: "read" },
    licenses: ["MIT"],
    has_deploy_job: false,
    touches_security: false,
    removes_security: false,
    cloud_oidc: false,
  },
  repo: { repo_url: "https://github.com/o/r", default_branch: "main", is_fork: false },
  risk_level: "low",
  target_branch: "feature/x",
  publish: false,
};

export default function Policies() {
  const [catalog, setCatalog] = useState<Record<string, unknown> | null>(null);
  const [payload, setPayload] = useState(JSON.stringify(SAMPLE, null, 2));
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.policyCatalog().then(setCatalog).catch((e) => setError(String(e)));
  }, []);

  const evaluate = async () => {
    setError("");
    try {
      setResult(await api.evaluatePolicy(JSON.parse(payload)));
    } catch (e) {
      setError(String(e));
    }
  };

  const list = (v: unknown) => Array.isArray(v) ? v.join(", ") : "";

  return (
    <div>
      <h1 className="page-title">Policies</h1>
      <p className="page-sub">OPA is the decision point; the catalog below is the shared source of truth.</p>
      {error && <div className="alert error">{error}</div>}
      <div className="card">
        <h3>Approved catalog</h3>
        {!catalog && <p className="muted">Loading…</p>}
        {catalog && (
          <dl className="kv">
            <dt>tools ({(catalog.tools as string[]).length})</dt><dd className="mono">{list(catalog.tools)}</dd>
            <dt>capabilities</dt><dd className="mono">{list(catalog.capabilities)}</dd>
            <dt>actions</dt><dd className="mono">{list(catalog.action_prefixes)}</dd>
            <dt>denied licenses</dt><dd className="mono">{list(catalog.denied_licenses)}</dd>
            <dt>protected branches</dt><dd className="mono">{list(catalog.protected_branches)}</dd>
            <dt>known permissions</dt><dd className="mono">{list(catalog.known_permissions)}</dd>
          </dl>
        )}
      </div>
      <div className="card">
        <h3>Ad-hoc evaluation</h3>
        <div className="field">
          <textarea className="input" rows={14} value={payload} onChange={(e) => setPayload(e.target.value)} />
        </div>
        <button className="btn primary" onClick={evaluate}>Evaluate</button>
        {result && (
          <div style={{ marginTop: 16 }}>
            <h3>Decision: <StatusBadge value={result.decision} /> <span className="muted">via {result.evaluator}</span></h3>
            <JsonView data={result} maxHeight={320} />
          </div>
        )}
      </div>
    </div>
  );
}
