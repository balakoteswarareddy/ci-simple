import { useState } from "react";

export default function YamlView({ filename, content }: { filename: string; content: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  const download = () => {
    const blob = new Blob([content], { type: "text/yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename.split("/").pop() || "workflow.yml";
    a.click();
    URL.revokeObjectURL(url);
  };
  if (!content) return <p className="muted">No rendered output yet.</p>;
  return (
    <div>
      <div className="code-head">
        <span className="mono">{filename}</span>
        <span className="btn-row" style={{ marginTop: 0 }}>
          <button className="btn" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
          <button className="btn" onClick={download}>Download</button>
        </span>
      </div>
      <pre className="code">{content}</pre>
    </div>
  );
}
