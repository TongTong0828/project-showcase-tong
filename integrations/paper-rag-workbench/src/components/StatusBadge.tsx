import type { ReactNode } from "react";

export function StatusBadge({
  tone,
  children,
}: {
  tone: "good" | "warn" | "neutral";
  children: ReactNode;
}) {
  return <span className={`status-badge ${tone}`}>{children}</span>;
}
