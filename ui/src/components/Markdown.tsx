import React from "react";

// Minimal markdown renderer for agent explanations: headings, lists, tables,
// code fences, inline code + bold. No dependencies, no raw HTML passthrough.
function inline(text: string, key: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) parts.push(<code key={`${key}-${i}`}>{tok.slice(1, -1)}</code>);
    else parts.push(<strong key={`${key}-${i}`}>{tok.slice(2, -2)}</strong>);
    last = m.index + tok.length;
    i++;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

export default function Markdown({ text }: { text: string }) {
  const lines = (text || "").split("\n");
  const out: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  const tableRow = (cells: string[], header: boolean, k: number) => (
    <tr key={k}>
      {cells.map((c, j) =>
        header ? <th key={j}>{inline(c.trim(), `${k}-${j}`)}</th> : <td key={j}>{inline(c.trim(), `${k}-${j}`)}</td>
      )}
    </tr>
  );
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++;
      out.push(<pre key={key++}><code>{buf.join("\n")}</code></pre>);
      continue;
    }
    if (/^###\s+/.test(line)) { out.push(<h3 key={key++}>{inline(line.replace(/^###\s+/, ""), `h${key}`)}</h3>); i++; continue; }
    if (/^##\s+/.test(line)) { out.push(<h2 key={key++}>{inline(line.replace(/^##\s+/, ""), `h${key}`)}</h2>); i++; continue; }
    if (/^#\s+/.test(line)) { out.push(<h1 key={key++}>{inline(line.replace(/^#\s+/, ""), `h${key}`)}</h1>); i++; continue; }
    if (line.trim().startsWith("|") && i + 1 < lines.length && /^\|[\s:\-|]+\|/.test(lines[i + 1].trim())) {
      const head = line.trim().slice(1, -1).split("|");
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(lines[i].trim().slice(1, -1).split("|"));
        i++;
      }
      out.push(
        <table key={key++}>
          <thead>{tableRow(head, true, key * 1000)}</thead>
          <tbody>{rows.map((r, j) => tableRow(r, false, key * 1000 + j + 1))}</tbody>
        </table>
      );
      continue;
    }
    if (/^(\s*)-\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^(\s*)-\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^(\s*)-\s+/, ""));
        i++;
      }
      out.push(
        <ul key={key++}>
          {items.map((t, j) => <li key={j}>{inline(t, `li${key}-${j}`)}</li>)}
        </ul>
      );
      continue;
    }
    if (line.trim() === "") { i++; continue; }
    out.push(<p key={key++}>{inline(line, `p${key}`)}</p>);
    i++;
  }
  return <div className="md">{out}</div>;
}
