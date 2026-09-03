import type { ReactNode } from "react";

export function DiagnosticCard({
  title,
  status,
  statusLabel,
  children,
}: {
  title: string;
  status: string;
  statusLabel?: string;
  children: ReactNode;
}) {
  return (
    <section className="diagnostic-card" aria-label={title}>
      <header>
        <h3>{title}</h3>
        <span className={`status-pill ${status.toLowerCase()}`}>{statusLabel ?? status}</span>
      </header>
      <div>{children}</div>
    </section>
  );
}
