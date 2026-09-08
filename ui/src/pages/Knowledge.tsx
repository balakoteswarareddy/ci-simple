import { useEffect, useState } from "react";
import { api } from "../api";
import JsonView from "../components/JsonView";

export default function Knowledge() {
  const [tools, setTools] = useState<string[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [selected, setSelected] = useState("");
  const [record, setRecord] = useState<Record<string, unknown> | null>(null);
  const [url, setUrl] = useState("");
  const [hint, setHint] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setTools((await api.knowledgeTools()).tools);
      setStats(await api.knowledgeStats());
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => { load(); }, []);

  const select = async (name: string) => {
    setSelected(name);
    try {
      setRecord(await api.knowledgeTool(name));
    } catch (e) {
      setError(String(e));
    }
  };

  const ingest = async () => {
    setBusy(true);
    setMsg("");
    try {
      const res: any = await api.ingest(url, hint);
      setMsg(res.ok ? `Ingested as '${res.tool}'. ${res.notes?.join(" ") || ""}` : `Failed: ${res.errors?.join(" ")}`);
      await load();
    } catch (e) {
      setError(String(e));
    }
    setBusy(false);
  };

  const refresh = async () => {
    setBusy(true);
    setMsg("");
    try {
      const res: any = await api.refreshKnowledge();
      const ok = (res.refreshed || []).filter((r: any) => r.ok).length;
      setMsg(`Refresh finished: ${ok}/${(res.refreshed || []).length} sources updated.`);
      await load();
    } catch (e) {
      setError(String(e));
    }
    setBusy(false);
  };

  return (
    <div>
      <h1 className="page-title">Knowledge</h1>
      <p className="page-sub">Grounded tool catalog — every plan cites these records, never vendor lore.</p>
      {error && <div className="alert error">{error}</div>}
      {msg && <div className="alert ok">{msg}</div>}
      <div className="grid cols-4">
        <div className="card stat"><div className="num">{tools.length}</div><div className="lbl">tools</div></div>
        <div className="card stat"><div className="num">{String(stats?.fresh_records ?? "—")}</div><div className="lbl">fresh records</div></div>
        <div className="card stat"><div className="num">{String(stats?.seed_records ?? "—")}</div><div className="lbl">seed records</div></div>
        <div className="card stat"><div className="btn-row" style={{ marginTop: 4 }}><button className="btn" disabled={busy} onClick={refresh}>Refresh all</button></div></div>
      </div>
      <div className="grid cols-2">
        <div className="card">
          <h3>Tools</h3>
          <div style={{ maxHeight: 420, overflow: "auto" }}>
            <table className="tbl">
              <tbody>
                {tools.map((t) => (
                  <tr key={t}>
                    <td><a href="#/knowledge" onClick={(e) => { e.preventDefault(); select(t); }} className="mono">{t}</a></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div>
          <div className="card">
            <h3>{selected ? `Record: ${selected}` : "Select a tool"}</h3>
            {record ? <JsonView data={record} maxHeight={360} /> : <p className="muted">Click a tool to inspect its evidence.</p>}
          </div>
          <div className="card">
            <h3>Ingest a trusted source</h3>
            <div className="field">
              <input className="input mono" placeholder="https://docs…/tool" value={url} onChange={(e) => setUrl(e.target.value)} />
            </div>
            <div className="field">
              <input className="input mono" placeholder="hint: tool name (optional)" value={hint} onChange={(e) => setHint(e.target.value)} />
              <div className="hint">Only allow-listed HTTPS hosts are fetched; extracted claims are verified against the source text.</div>
            </div>
            <button className="btn primary" disabled={busy || !url} onClick={ingest}>Ingest</button>
          </div>
        </div>
      </div>
    </div>
  );
}
