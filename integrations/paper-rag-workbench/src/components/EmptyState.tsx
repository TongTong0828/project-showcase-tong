export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state" role="status">
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}
