export default function StatusBadge({ value }: { value: string }) {
  const cls = "b-" + value.toLowerCase().replace(/-/g, "_");
  return <span className={`badge ${cls}`}>{value}</span>;
}
