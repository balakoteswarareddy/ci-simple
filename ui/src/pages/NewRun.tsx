import { useState } from "react";
import { api, CreateRunOptions } from "../api";

const CAPS = ["lint", "format", "test", "sast", "sca", "secrets", "container-scan", "iac-scan", "build", "docker-build", "sbom", "sign", "deploy"];
const PLATFORMS = ["github", "azure", "gitlab", "jenkins"];

const EXAMPLES = [
  {
    label: "Python API, full suite",
    request: "Create GitHub Actions CI for this Python API. Run tests, linting and security checks. Do not use Semgrep.",
  },
  {
    label: "Node, lint + test",
    request: "Create CI for this Node project: run eslint and jest tests.",
  },
  {
    label: "Container + supply chain",
    request: "Build the container image, scan it, generate an SBOM and sign it.",
  },
];

export default function NewRun() {
  const [repoUrl, setRepoUrl] = useState("");
  const [request, setRequest] = useState(EXAMPLES[0].request);
  const [platform, setPlatform] = useState("github");
  const [revision, setRevision] = useState("");
  const [publish, setPublish] = useState(false);
  const [targetBranch, setTargetBranch] = useState("");
  const [baseBranch, setBaseBranch] = useState("");
  const [prTitle, setPrTitle] = useState("");
  const [requireApproval, setRequireApproval] = useState(false);
  const [caps, setCaps] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const toggleCap = (c: string) =>
    setCaps((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const options: CreateRunOptions = {
        platform,
        revision: revision || undefined,
        publish,
        target_branch: targetBranch || undefined,
        base_branch: baseBranch || undefined,
        pr_title: prTitle || undefined,
        require_approval: requireApproval,
        capabilities: caps.length ? caps : undefined,
      };
      const { run_id } = await api.createRun(repoUrl.trim(), request.trim(), options);
      window.location.hash = `#/runs/${run_id}`;
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  };

  return (
    <div>
      <h1 className="page-title">New run</h1>
      <p className="page-sub">Describe the CI you want — the agent inspects the repo and grounds every choice.</p>
      {error && <div className="alert error">{error}</div>}
      <div className="card">
        <div className="field">
          <label>Repository URL</label>
          <input className="input mono" placeholder="https://github.com/org/repo" value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} />
          <div className="hint">HTTPS git URL on an allow-listed host. Local paths work only when the server enables them (dev/tests).</div>
        </div>
        <div className="field">
          <label>Request</label>
          <div className="btn-row" style={{ margin: "0 0 8px" }}>
            {EXAMPLES.map((ex) => (
              <button key={ex.label} className="btn" onClick={() => setRequest(ex.request)}>{ex.label}</button>
            ))}
          </div>
          <textarea className="input" rows={4} value={request} onChange={(e) => setRequest(e.target.value)} />
        </div>
        <div className="grid cols-2">
          <div className="field">
            <label>Platform</label>
            <select className="input" value={platform} onChange={(e) => setPlatform(e.target.value)}>
              {PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Revision (optional)</label>
            <input className="input mono" placeholder="branch, tag or SHA (default branch if empty)" value={revision} onChange={(e) => setRevision(e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label>Capabilities <span className="muted" style={{ fontWeight: 400 }}>(optional — detected from the request when empty)</span></label>
          <div className="cap-grid">
            {CAPS.map((c) => (
              <label key={c} className={caps.includes(c) ? "on" : ""}>
                <input type="checkbox" checked={caps.includes(c)} onChange={() => toggleCap(c)} />{c}
              </label>
            ))}
          </div>
        </div>
        <div className="check-row">
          <input type="checkbox" id="pub" checked={publish} onChange={(e) => setPublish(e.target.checked)} />
          <label htmlFor="pub">Publish: create branch, commit workflow, open PR <span className="muted">(high-risk runs pause for approval first)</span></label>
        </div>
        {publish && (
          <div className="grid cols-2">
            <div className="field">
              <label>Feature branch (optional)</label>
              <input className="input mono" placeholder="auto: ci-agent/&lt;run&gt;" value={targetBranch} onChange={(e) => setTargetBranch(e.target.value)} />
            </div>
            <div className="field">
              <label>Base branch (optional)</label>
              <input className="input mono" placeholder="repo default" value={baseBranch} onChange={(e) => setBaseBranch(e.target.value)} />
            </div>
            <div className="field">
              <label>PR title (optional)</label>
              <input className="input" value={prTitle} onChange={(e) => setPrTitle(e.target.value)} />
            </div>
          </div>
        )}
        <div className="check-row">
          <input type="checkbox" id="appr" checked={requireApproval} onChange={(e) => setRequireApproval(e.target.checked)} />
          <label htmlFor="appr">Require human approval before finishing</label>
        </div>
        <div className="btn-row">
          <button className="btn primary" disabled={busy || !repoUrl.trim() || !request.trim()} onClick={submit}>
            {busy ? "Starting…" : "Start run"}
          </button>
        </div>
      </div>
    </div>
  );
}
