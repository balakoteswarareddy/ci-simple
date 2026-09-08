import type { RunEvent } from "../types";

export default function Timeline({ events }: { events: RunEvent[] }) {
  if (!events.length) return <p className="muted">No events yet.</p>;
  return (
    <div className="timeline">
      {events.map((e) => (
        <div key={e.seq} className={`tl-item ${e.level}`}>
          <div className="tl-step">
            #{e.seq} {e.step} · {new Date(e.created_at).toLocaleTimeString()}
          </div>
          <div className="tl-msg">{e.message}</div>
        </div>
      ))}
    </div>
  );
}
