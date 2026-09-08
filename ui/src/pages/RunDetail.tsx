import { useEffect, useState } from "react";
import { api } from "../api";
import type { RunDetail as RD, RunEvent, ValidationResult } from "../types";
import { TERMINAL } from "../types";
import StatusBadge from "../components/StatusBadge";
import JsonView from "../components/JsonView";
import YamlView from "../components/YamlView";
import Timeline from "../components/Timeline";
import Markdown from "../components/Markdown";

const TABS = ["Overview", "Plan", "Pipeline IR", "Workflow", "Validation", "Policy", "Security", "Supply chain", "Publish", "Evidence", "Events"];

function Findings({ list, kind }: { list: any[]; kind: string }) {
  if (!list?.length) return <p className="muted">No {kind}.</p>;
  return (
    <table className="tbl">
      <thead><tr><th>Message</th><th>Location</th><th>Remediation</th></tr></thead>
      <tbody>
        {list.map((f: any, i: number) => (
          <tr key={i}>
            <td>{f.message || f.rule || JSON.stringify(f)}</td>
            <td className="mono muted">{[f.file, f.line].filter(Boolean).join(":")}</td>
            <td className="muted">{f.remediation || ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function RunDetail({ id }: { id: string }) {
  const [run, setRun] = useState<RD | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [yaml, setYaml] = useState<{ filename: string; content: string } | null>(null);
  const [evidence, setEvidence] = useState<Record<string, unknown> | null>(null);
  const [tab, setTab] = useState("Overview");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const r = await api.getRun(id);
      setRun(r);
      const ev = await api.getEvents(id);
      setEvents(ev.events);
      if (r.rendered_yaml) {
        try { setYaml(await api.getYaml(id)); } catch { /* not rendered yet */ }
      }
      try { setEvidence(await api.getEvidence(id)); } catch { /* no evidence yet */ }
      setError("");
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(async () => {
      const r = await api.getRun(id).catch(() => null);
      if (!r) return;
      setRun(r);
      const ev = await api.getEvents(id).catch(() => null);
      if (ev) setEvents(ev.events);
      if (TERMINAL.has(r.status)) {
        clearInterval(t);
        load();
      }
    }, 2000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const decide = async (decision: string) => {
    setBusy(true);
    try {
      await api.decide(id, decision, reason);
      await load();
    } catch (e) {
      setError(String(e));
    }
    setBusy(false);
  };

  const refreshChecks = async () => {
    setBusy(true);
    try {
      await api.refreshChecks(id);
      await load();
    } catch (e) {
      setError(String(e));
    }
    setBusy(false);
  };

  if (error && !run) return <div className="alert error">{error}</div>;
  if (!run) return <p className="muted">Loading…</p>;

  const plan: any = run.plan || {};
  const intent: any = run.intent || {};
  const policy = run.policy || { decision: "?", deny: [], approval_reasons: [], evaluator: "?" };
  const publish: any = run.publish || {};
  const security: any = run.security || {};
  const supply: any = run.supply_chain || {};
  const active = !TERMINAL.has(run.status);

  return (
    <div>
      <div className="run-head">
        <h2>{run.id}</h2>
        <StatusBadge value={run.status} />
        <StatusBadge value={run.risk_level || "low"} />
        {active && <span className="muted">· {run.current_step || "working"}…</span>}
      </div>
      <p className="page-sub mono">{run.repo_url} · {run.platform}</p>
      {error && <div className="alert error">{error}</div>}
      {run.error && <div className="alert error">{run.error}</div>}

      {run.status === "awaiting_approval" && (
        <div className="card">
          <h3>Human approval required</h3>
          <div className="field">
            <input className="input" placeholder="reason (recorded immutably)" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="btn-row">
            <button className="btn primary" disabled={busy} onClick={() => decide("approve")}>Approve</button>
            <button className="btn danger" disabled={busy} onClick={() => decide("reject")}>Reject</button>
          </div>
        </div>
      )}

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t} className={"tab" + (tab === t ? " active" : "")} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {tab === "Overview" && (
        <div className="card">
          {run.explanation ? <Markdown text={run.explanation} /> : <p className="muted">Explanation appears once planning finishes.</p>}
        </div>
      )}

      {tab === "Plan" && (
        <>
          <div className="card">
            <h3>Intent <span className="muted mono">({String(intent.planner || "")})</span></h3>
            <dl className="kv">
              <dt>capabilities</dt><dd className="mono">{(intent.capabilities || []).join(", ")}</dd>
              <dt>prohibited tools</dt><dd className="mono">{(intent.prohibited_tools || []).join(", ") || "—"}</dd>
              <dt>deployment target</dt><dd className="mono">{intent.deployment_target || "—"}</dd>
              <dt>constraints</dt><dd>{(intent.constraints || []).join(" · ") || "—"}</dd>
            </dl>
          </div>
          <div className="card">
            <h3>Selected tools</h3>
            <table className="tbl">
              <thead><tr><th>Tool</th><th>Capability</th><th>Version</th><th>Why</th></tr></thead>
              <tbody>
                {(plan.tools || []).map((t: any) => (
                  <tr key={t.name}><td className="mono">{t.name}</td><td>{t.capability}</td>
                    <td className="mono">{t.version}</td><td className="muted">{t.reason}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card">
            <h3>Actions &amp; permissions</h3>
            <dl className="kv">
              <dt>actions</dt>
              <dd className="mono">{(plan.actions || []).map((a: any) => a.uses).join(", ") || "—"}</dd>
              <dt>permissions</dt>
              <dd className="mono">{Object.entries(plan.permissions || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"}</dd>
              <dt>flags</dt>
              <dd className="mono">deploy={String(plan.has_deploy_job)} security={String(plan.touches_security)} oidc={String(plan.cloud_oidc)}</dd>
            </dl>
            {(plan.notes || []).length > 0 && (
              <><h3 style={{ marginTop: 12 }}>Planner notes</h3>
              <ul>{(plan.notes || []).map((n: string, i: number) => <li key={i} className="muted">{n}</li>)}</ul></>
            )}
          </div>
        </>
      )}

      {tab === "Pipeline IR" && (
        <div className="card"><JsonView data={run.ir} /></div>
      )}

      {tab === "Workflow" && (
        <div className="card">
          <YamlView filename={yaml?.filename || ""} content={yaml?.content || run.rendered_yaml || ""} />
        </div>
      )}

      {tab === "Validation" && (
        <>
          {(run.validation || []).map((v: ValidationResult) => (
            <div className="card" key={v.validator}>
              <h3>{v.validator} {v.version && <span className="muted mono">({v.version})</span>} — {v.passed ? "PASS" : "FAIL"}
                {v.provenance?.runner === "skipped" && <span className="muted"> (skipped: {v.provenance.reason})</span>}
              </h3>
              <Findings list={v.errors} kind="errors" />
              {v.warnings?.length > 0 && <><h3 style={{ marginTop: 10 }}>Warnings</h3><Findings list={v.warnings} kind="warnings" /></>}
            </div>
          ))}
          {!(run.validation || []).length && <p className="muted">No validation results yet.</p>}
          {run.repair_attempts > 0 && <p className="muted">Repair attempts: {run.repair_attempts}</p>}
        </>
      )}

      {tab === "Policy" && (
        <div className="card">
          <h3>Decision: <StatusBadge value={policy.decision} /> <span className="muted">via {policy.evaluator}</span></h3>
          <h3 style={{ marginTop: 12 }}>Deny findings</h3>
          <Findings list={policy.deny || []} kind="deny findings" />
          <h3 style={{ marginTop: 12 }}>Approval reasons</h3>
          <Findings list={policy.approval_reasons || []} kind="approval reasons" />
        </div>
      )}

      {tab === "Security" && (
        <>
          {Object.keys(security).length === 0 && <p className="muted">No security scans ran for this run.</p>}
          {Object.entries(security).map(([name, raw]) => {
            const s: any = raw;
            return (
              <div className="card" key={name}>
                <h3>{name} <span className="muted mono">({s.scanner}{s.provenance?.runner ? ` · ${s.provenance.runner}` : ""})</span> — {s.passed ? "PASS" : "FAIL"}</h3>
                <Findings list={s.findings || []} kind="findings" />
              </div>
            );
          })}
        </>
      )}

      {tab === "Supply chain" && (
        <div className="card">
          {Object.keys(supply).length === 0 && <p className="muted">No supply-chain steps ran for this run.</p>}
          <JsonView data={supply} />
        </div>
      )}

      {tab === "Publish" && (
        <div className="card">
          {!publish.commit_sha && <p className="muted">Nothing published (generate-only run).</p>}
          {publish.commit_sha && (
            <>
              <dl className="kv">
                <dt>branch</dt><dd className="mono">{publish.head_branch} → {publish.base_branch}</dd>
                <dt>commit</dt><dd className="mono">{publish.commit_sha}</dd>
                <dt>file</dt><dd className="mono">{publish.file}</dd>
                <dt>PR</dt><dd>{publish.pr?.url ? <a href={publish.pr.url} target="_blank" rel="noreferrer">#{publish.pr.number}</a> : "—"}</dd>
                <dt>merge</dt><dd><StatusBadge value={publish.merge?.recommendation || "?"} /> <span className="muted">{(publish.merge?.reasons || []).join(" · ")}</span></dd>
              </dl>
              <div className="btn-row">
                <button className="btn" disabled={busy} onClick={refreshChecks}>Refresh checks</button>
              </div>
              {(publish.checks || []).length > 0 && (
                <table className="tbl" style={{ marginTop: 12 }}>
                  <thead><tr><th>Check</th><th>Status</th><th>Conclusion</th></tr></thead>
                  <tbody>
                    {(publish.checks || []).map((c: any, i: number) => (
                      <tr key={i}><td>{c.name}</td><td className="mono">{c.status}</td><td className="mono">{c.conclusion}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>
      )}

      {tab === "Evidence" && (
        <div className="card">
          {evidence ? <JsonView data={evidence} /> : <p className="muted">Evidence is recorded when the run finishes or pauses.</p>}
        </div>
      )}

      {tab === "Events" && (
        <div className="card"><Timeline events={events} /></div>
      )}
    </div>
  );
}
