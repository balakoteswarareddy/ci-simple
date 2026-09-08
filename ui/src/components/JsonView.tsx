import { useState } from "react";

export default function JsonView({ data, maxHeight }: { data: unknown; maxHeight?: number }) {
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(data ?? null, null, 2);
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  return (
    <div>
      <div className="code-head">
        <span className="muted mono">{text.split("\n").length} lines</span>
        <button className="btn" onClick={copy}>{copied ? "Copied" : "Copy JSON"}</button>
      </div>
      <pre className="code" style={maxHeight ? { maxHeight } : undefined}>{text}</pre>
    </div>
  );
}
