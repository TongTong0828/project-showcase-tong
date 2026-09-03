import {
  Activity,
  BookOpen,
  Briefcase,
  Columns3,
  Compass,
  Database,
  MessageSquare,
  Search,
  Sparkles,
} from "lucide-react";
import type { ReactNode } from "react";

import { ProjectSwitcher } from "./ProjectSwitcher";
import { useI18n, type MessageKey } from "../i18n";

const nav = [
  { id: "overview", labelKey: "nav.overview", icon: Database },
  { id: "workspace", labelKey: "nav.workspace", icon: Briefcase },
  { id: "compare", labelKey: "nav.compare", icon: Columns3 },
  { id: "health", labelKey: "nav.health", icon: Activity },
  { id: "library", labelKey: "nav.library", icon: BookOpen },
  { id: "search", labelKey: "nav.search", icon: Search },
  { id: "ask", labelKey: "nav.ask", icon: MessageSquare },
  { id: "discover", labelKey: "nav.discover", icon: Compass },
  { id: "dsh", labelKey: "nav.dsh", icon: Sparkles },
] as const satisfies readonly {
  id: string;
  labelKey: MessageKey;
  icon: typeof Database;
}[];

export type RouteId = (typeof nav)[number]["id"];

export function Shell({
  active,
  onNavigate,
  children,
}: {
  active: RouteId;
  onNavigate: (route: RouteId) => void;
  children: ReactNode;
}) {
  const { language, setLanguage, t } = useI18n();

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>Paper RAG</h1>
          <div className="language-toggle" aria-label={t("language.aria")}>
            <button type="button" aria-pressed={language === "zh"} onClick={() => setLanguage("zh")}>
              {t("language.zh")}
            </button>
            <button type="button" aria-pressed={language === "en"} onClick={() => setLanguage("en")}>
              {t("language.en")}
            </button>
          </div>
        </div>
        <nav aria-label={t("nav.aria")}>
          {nav.map(({ id, labelKey, icon: Icon }) => (
            <button
              key={id}
              type="button"
              aria-current={active === id ? "page" : undefined}
              className={active === id ? "active" : ""}
              onClick={() => {
                if (id === "dsh") {
                  window.open("http://127.0.0.1:3080", "_blank", "noopener,noreferrer");
                  return;
                }
                onNavigate(id);
              }}
            >
              <Icon aria-hidden="true" size={17} />
              <span>{t(labelKey)}</span>
            </button>
          ))}
        </nav>
        <ProjectSwitcher />
      </aside>
      <section className="workspace">{children}</section>
    </main>
  );
}
