# Paper RAG Workbench Bilingual V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Paper RAG Workbench Chinese-first with a persistent English toggle while preserving the existing research workflows and safety boundaries.

**Architecture:** Add a small Workbench-local React i18n provider, then route all Workbench-owned UI chrome through typed translation keys. Keep Paper RAG data, model output, citations, chunk text, backend payloads, DSH handoff content, and `deepseek-v4-flash` behavior unchanged.

**Tech Stack:** React 18, TypeScript, Vite, Vitest, Testing Library, Playwright, existing Workbench API fixtures.

## Global Constraints

- UI language values are exactly `zh` and `en`.
- Default language is Chinese.
- Persist the selected language in `localStorage` key `paper-rag-workbench-language`.
- Do not translate paper titles, abstracts, chunk text, citations, model answers, raw backend error details, model names, paper ids, or chunk ids.
- Keep `deepseek-v4-flash` unchanged.
- Do not create or restore `integrations/deer-flow/`.
- Do not commit `.env`, API keys, `data/index`, runtime credentials, DSH sessions, real PDFs, generated `dist`, `node_modules`, or temporary smoke data.
- Do not execute real-library write smoke tests unless the user explicitly approves that run.
- Preserve explicit approval for every real write path.
- Add no new runtime dependencies.

---

## File Structure

- Create `integrations/paper-rag-workbench/src/i18n.tsx`
  - Owns `Language`, `messages`, `I18nProvider`, `useI18n`, persistence, and interpolation.
- Create `integrations/paper-rag-workbench/src/test/render.tsx`
  - Wraps tested components in `I18nProvider`.
- Create `integrations/paper-rag-workbench/src/__tests__/i18n.test.tsx`
  - Covers default Chinese, English switch, localStorage persistence, invalid stored values, and interpolation.
- Modify `integrations/paper-rag-workbench/src/App.tsx`
  - Wraps Shell and pages in `I18nProvider`.
- Modify `integrations/paper-rag-workbench/src/components/Shell.tsx`
  - Translates navigation and adds the language toggle.
- Modify Workbench pages:
  - `integrations/paper-rag-workbench/src/pages/OverviewPage.tsx`
  - `integrations/paper-rag-workbench/src/pages/HealthPage.tsx`
  - `integrations/paper-rag-workbench/src/pages/LibraryPage.tsx`
  - `integrations/paper-rag-workbench/src/pages/SearchPage.tsx`
  - `integrations/paper-rag-workbench/src/pages/AskPage.tsx`
  - `integrations/paper-rag-workbench/src/pages/DiscoverPage.tsx`
- Modify Workbench components:
  - `integrations/paper-rag-workbench/src/components/AgentTimeline.tsx`
  - `integrations/paper-rag-workbench/src/components/AnswerPanel.tsx`
  - `integrations/paper-rag-workbench/src/components/ApprovalDialog.tsx`
  - `integrations/paper-rag-workbench/src/components/CandidateTable.tsx`
  - `integrations/paper-rag-workbench/src/components/ChunkDetailPanel.tsx`
  - `integrations/paper-rag-workbench/src/components/CitationChips.tsx`
  - `integrations/paper-rag-workbench/src/components/DshHandoffDialog.tsx`
  - `integrations/paper-rag-workbench/src/components/EvidenceChunkCard.tsx`
  - `integrations/paper-rag-workbench/src/components/HealthSummary.tsx`
  - `integrations/paper-rag-workbench/src/components/PaperDetailPanel.tsx`
  - `integrations/paper-rag-workbench/src/components/PaperTable.tsx`
  - `integrations/paper-rag-workbench/src/components/QualityIssueTable.tsx`
  - `integrations/paper-rag-workbench/src/components/ScoreBreakdown.tsx`
- Modify `integrations/paper-rag-workbench/src/styles.css`
  - Adds segmented language toggle styling.
- Modify frontend tests:
  - `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`
  - `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx`
  - `integrations/paper-rag-workbench/tests/workbench.spec.ts`
- Modify `integrations/paper-rag-workbench/README.md`
  - Documents the Chinese default and English toggle.

---

### Task 1: I18n Provider, Messages, and Unit Tests

**Files:**
- Create: `integrations/paper-rag-workbench/src/i18n.tsx`
- Create: `integrations/paper-rag-workbench/src/__tests__/i18n.test.tsx`

**Interfaces:**
- Produces: `export type Language = "zh" | "en"`
- Produces: `export const LANGUAGE_STORAGE_KEY = "paper-rag-workbench-language"`
- Produces: `export type MessageKey = keyof typeof messages.en`
- Produces: `export function I18nProvider({ children }: { children: ReactNode })`
- Produces: `export function useI18n(): { language: Language; setLanguage(language: Language): void; t(key: MessageKey, vars?: Record<string, string | number>): string }`
- Produces: `export function resolveInitialLanguage(storageValue: string | null): Language`
- Produces: `export function formatMessage(template: string, vars?: Record<string, string | number>): string`
- Consumes: React context and browser `localStorage`.

- [ ] **Step 1: Write the failing i18n tests**

Create `integrations/paper-rag-workbench/src/__tests__/i18n.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, beforeEach } from "vitest";

import {
  I18nProvider,
  LANGUAGE_STORAGE_KEY,
  formatMessage,
  resolveInitialLanguage,
  useI18n,
} from "../i18n";

function Probe() {
  const { language, setLanguage, t } = useI18n();
  return (
    <section>
      <h1>{t("nav.overview")}</h1>
      <p>{t("health.chunkCount", { count: 345 })}</p>
      <output aria-label="language">{language}</output>
      <button type="button" onClick={() => setLanguage("en")}>
        switch english
      </button>
    </section>
  );
}

describe("Workbench i18n", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  test("defaults to Chinese when no language is stored", () => {
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );

    expect(screen.getByRole("heading", { name: "概览" })).toBeInTheDocument();
    expect(screen.getByLabelText("language")).toHaveTextContent("zh");
  });

  test("switches to English and persists the selection", async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );

    await user.click(screen.getByRole("button", { name: "switch english" }));

    expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
  });

  test("ignores invalid stored language values", () => {
    expect(resolveInitialLanguage("fr")).toBe("zh");
    expect(resolveInitialLanguage(null)).toBe("zh");
    expect(resolveInitialLanguage("en")).toBe("en");
  });

  test("interpolates named values without touching unknown tokens", () => {
    expect(formatMessage("Chunks: {count}; {missing}", { count: 345 })).toBe(
      "Chunks: 345; {missing}",
    );
  });
});
```

This catches these production bugs: defaulting to English, not persisting a user language choice, accepting unsupported language values, and breaking message interpolation.

- [ ] **Step 2: Run the i18n tests to verify they fail**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- src/__tests__/i18n.test.tsx
```

Expected: fail because `../i18n` does not exist.

- [ ] **Step 3: Implement `src/i18n.tsx`**

Create `integrations/paper-rag-workbench/src/i18n.tsx`:

```tsx
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

export type Language = "zh" | "en";
export const LANGUAGE_STORAGE_KEY = "paper-rag-workbench-language";

export const messages = {
  en: {
    "nav.overview": "Overview",
    "nav.health": "Health",
    "nav.library": "Library",
    "nav.search": "Search",
    "nav.ask": "Ask",
    "nav.discover": "Discover",
    "nav.dsh": "DSH Chat",
    "nav.aria": "Workbench navigation",
    "language.zh": "中",
    "language.en": "EN",
    "language.aria": "Interface language",
    "overview.title": "Overview",
    "overview.subtitle": "Corpus status, model readiness, and quick actions.",
    "overview.openDsh": "Open DSH Chat",
    "overview.papers": "Papers",
    "overview.chunks": "Chunks",
    "overview.model": "Model",
    "overview.credentials": "Credentials",
    "overview.configured": "Configured",
    "overview.missing": "Missing",
    "overview.loading": "Loading overview...",
    "overview.unavailable": "Overview unavailable",
    "health.title": "Health",
    "health.subtitle": "Inspect corpus readiness, retrieval fallback, model configuration, and data quality.",
    "health.indexTitle": "Index Health",
    "health.qualityIssues": "Quality Issues",
    "health.sendToDsh": "Send diagnostics to DSH",
    "health.loadingTitle": "Loading health",
    "health.loadingDetail": "Checking local indexes.",
    "health.unavailable": "Health unavailable",
    "health.chunkCount": "{count} chunks",
    "library.title": "Library",
    "library.subtitle": "Inspect indexed papers and open source sections without writing to the corpus.",
    "library.filter": "Filter papers",
    "library.loading": "Loading library...",
    "library.unavailable": "Library unavailable",
    "library.sectionUnavailable": "Section is unavailable.",
    "library.introduction": "Introduction",
    "search.title": "Search",
    "search.subtitle": "Retrieve source chunks before asking the model to synthesize.",
    "search.evidence": "Search evidence",
    "search.topK": "Top K",
    "search.submit": "Search",
    "search.loading": "Searching...",
    "search.unavailable": "Search unavailable",
    "search.resultsAria": "Search results",
    "search.sendToDsh": "Send search to DSH",
    "ask.title": "Ask",
    "ask.subtitle": "Ask grounded questions and inspect the evidence used for each answer.",
    "ask.question": "Question",
    "ask.paperIds": "Paper IDs",
    "ask.topK": "Top K",
    "ask.submit": "Ask",
    "ask.loading": "Asking...",
    "ask.unavailable": "Answer unavailable",
    "ask.copyPrompt": "Copy prompt for DSH",
    "ask.sendToDsh": "Send to DSH",
    "ask.copied": "Copied",
    "discover.title": "Discover",
    "discover.subtitle": "Find candidate papers, then explicitly approve any ingest side effects.",
    "discover.topic": "Topic",
    "discover.sources": "Sources",
    "discover.maxCandidates": "Max candidates",
    "discover.submit": "Discover",
    "discover.loading": "Discovering...",
    "discover.unavailable": "Discovery unavailable",
    "discover.ingestSelected": "Ingest selected",
    "discover.selectedCount": "{count} selected",
    "discover.receipt": "Ingest receipt",
    "discover.ingesting": "Ingesting approved candidates...",
    "answer.title": "Answer",
    "answer.noCitations": "No citations",
    "answer.citationsAria": "Citations",
    "timeline.title": "Agent Timeline",
    "timeline.running": "running",
    "approval.title": "Approve candidate ingest",
    "approval.candidateIds": "Candidate ids: {ids}",
    "approval.cancel": "Cancel",
    "approval.approve": "Approve ingest",
    "approval.effect.write": "write indexed paper and chunks",
    "approval.effect.update": "update the configured Paper RAG corpus",
    "approval.effect.record": "record ingestion metadata",
    "candidate.select": "Select",
    "candidate.candidate": "Candidate",
    "candidate.source": "Source",
    "candidate.rank": "Rank",
    "candidate.evidence": "Evidence",
    "candidate.notEvidence": "Candidate-only; not answer evidence",
    "paperDetail.sections": "Sections",
    "paperDetail.chunks": "Chunks",
    "paperDetail.unknownSection": "Unknown section",
    "chunkDetail.openPaper": "Open paper detail",
    "chunkDetail.paper": "Paper",
    "chunkDetail.section": "Section",
    "chunkDetail.page": "Page",
    "chunkDetail.unknown": "unknown",
    "chunkDetail.nearby": "Nearby chunks",
    "chunk.page": "Page {page}",
    "chunk.source": "source",
    "chunk.score": "score {score}",
    "quality.empty": "No quality samples detected.",
    "quality.kind": "Kind",
    "quality.paper": "Paper",
    "quality.chunks": "Chunks",
    "quality.preview": "Preview",
    "handoff.title": "Send to DSH",
    "handoff.close": "Close DSH handoff",
    "handoff.copy": "Copy prompt",
    "handoff.open": "Open DSH",
  },
  zh: {
    "nav.overview": "概览",
    "nav.health": "健康检查",
    "nav.library": "论文库",
    "nav.search": "检索",
    "nav.ask": "问答",
    "nav.discover": "发现",
    "nav.dsh": "DSH 对话",
    "nav.aria": "工作台导航",
    "language.zh": "中",
    "language.en": "EN",
    "language.aria": "界面语言",
    "overview.title": "概览",
    "overview.subtitle": "查看语料库状态、模型就绪度和快捷操作。",
    "overview.openDsh": "打开 DSH 对话",
    "overview.papers": "论文",
    "overview.chunks": "分块",
    "overview.model": "模型",
    "overview.credentials": "凭据",
    "overview.configured": "已配置",
    "overview.missing": "缺失",
    "overview.loading": "正在加载概览...",
    "overview.unavailable": "概览不可用",
    "health.title": "健康检查",
    "health.subtitle": "检查语料库就绪度、检索降级、模型配置和数据质量。",
    "health.indexTitle": "索引健康",
    "health.qualityIssues": "质量问题",
    "health.sendToDsh": "发送诊断到 DSH",
    "health.loadingTitle": "正在加载健康检查",
    "health.loadingDetail": "正在检查本地索引。",
    "health.unavailable": "健康检查不可用",
    "health.chunkCount": "{count} 个分块",
    "library.title": "论文库",
    "library.subtitle": "查看已索引论文并读取原文章节，不写入语料库。",
    "library.filter": "筛选论文",
    "library.loading": "正在加载论文库...",
    "library.unavailable": "论文库不可用",
    "library.sectionUnavailable": "章节不可用。",
    "library.introduction": "引言",
    "search.title": "检索",
    "search.subtitle": "先检索原文证据，再让模型综合回答。",
    "search.evidence": "检索证据",
    "search.topK": "Top K",
    "search.submit": "检索",
    "search.loading": "检索中...",
    "search.unavailable": "检索不可用",
    "search.resultsAria": "检索结果",
    "search.sendToDsh": "发送检索到 DSH",
    "ask.title": "问答",
    "ask.subtitle": "提出基于论文的问题，并检查每个回答使用的证据。",
    "ask.question": "问题",
    "ask.paperIds": "论文 ID",
    "ask.topK": "Top K",
    "ask.submit": "提问",
    "ask.loading": "回答中...",
    "ask.unavailable": "回答不可用",
    "ask.copyPrompt": "复制 DSH 提示词",
    "ask.sendToDsh": "发送到 DSH",
    "ask.copied": "已复制",
    "discover.title": "发现",
    "discover.subtitle": "查找候选论文，并在任何入库副作用前显式批准。",
    "discover.topic": "主题",
    "discover.sources": "来源",
    "discover.maxCandidates": "候选数量上限",
    "discover.submit": "发现",
    "discover.loading": "发现中...",
    "discover.unavailable": "发现不可用",
    "discover.ingestSelected": "入库所选",
    "discover.selectedCount": "已选择 {count} 项",
    "discover.receipt": "入库回执",
    "discover.ingesting": "正在入库已批准候选...",
    "answer.title": "回答",
    "answer.noCitations": "无引用",
    "answer.citationsAria": "引用",
    "timeline.title": "执行轨迹",
    "timeline.running": "运行中",
    "approval.title": "批准候选入库",
    "approval.candidateIds": "候选 ID：{ids}",
    "approval.cancel": "取消",
    "approval.approve": "批准入库",
    "approval.effect.write": "写入索引论文和分块",
    "approval.effect.update": "更新已配置的 Paper RAG 语料库",
    "approval.effect.record": "记录入库元数据",
    "candidate.select": "选择",
    "candidate.candidate": "候选论文",
    "candidate.source": "来源",
    "candidate.rank": "排名",
    "candidate.evidence": "证据",
    "candidate.notEvidence": "候选项；不是回答证据",
    "paperDetail.sections": "章节",
    "paperDetail.chunks": "分块",
    "paperDetail.unknownSection": "未知章节",
    "chunkDetail.openPaper": "打开论文详情",
    "chunkDetail.paper": "论文",
    "chunkDetail.section": "章节",
    "chunkDetail.page": "页码",
    "chunkDetail.unknown": "未知",
    "chunkDetail.nearby": "附近分块",
    "chunk.page": "第 {page} 页",
    "chunk.source": "来源",
    "chunk.score": "得分 {score}",
    "quality.empty": "未检测到质量样本。",
    "quality.kind": "类型",
    "quality.paper": "论文",
    "quality.chunks": "分块",
    "quality.preview": "预览",
    "handoff.title": "发送到 DSH",
    "handoff.close": "关闭 DSH 交接",
    "handoff.copy": "复制提示词",
    "handoff.open": "打开 DSH",
  },
} as const;

export type MessageKey = keyof typeof messages.en;

type I18nValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
};

const I18nContext = createContext<I18nValue | null>(null);

export function resolveInitialLanguage(storageValue: string | null): Language {
  return storageValue === "en" || storageValue === "zh" ? storageValue : "zh";
}

export function formatMessage(
  template: string,
  vars?: Record<string, string | number>,
): string {
  if (!vars) return template;
  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) => {
    const value = vars[name];
    return value === undefined ? match : String(value);
  });
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(() =>
    resolveInitialLanguage(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)),
  );

  const value = useMemo<I18nValue>(() => {
    const setLanguage = (nextLanguage: Language) => {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, nextLanguage);
      setLanguageState(nextLanguage);
    };

    return {
      language,
      setLanguage,
      t: (key, vars) => formatMessage(messages[language][key], vars),
    };
  }, [language]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) {
    throw new Error("useI18n must be used inside I18nProvider");
  }
  return value;
}
```

- [ ] **Step 4: Run the i18n tests to verify they pass**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- src/__tests__/i18n.test.tsx
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add integrations/paper-rag-workbench/src/i18n.tsx integrations/paper-rag-workbench/src/__tests__/i18n.test.tsx
git commit -m "feat: add workbench i18n provider"
```

---

### Task 2: App Provider, Shell Toggle, and Render Helper

**Files:**
- Modify: `integrations/paper-rag-workbench/src/App.tsx`
- Modify: `integrations/paper-rag-workbench/src/components/Shell.tsx`
- Modify: `integrations/paper-rag-workbench/src/styles.css`
- Create: `integrations/paper-rag-workbench/src/test/render.tsx`
- Modify: `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`

**Interfaces:**
- Consumes: `I18nProvider` and `useI18n` from Task 1.
- Produces: `renderWithI18n(ui: ReactElement)`.
- Produces: translated sidebar labels and language toggle in `Shell`.

- [ ] **Step 1: Write the failing shell tests**

Add these tests to `integrations/paper-rag-workbench/src/__tests__/components.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { Shell } from "../components/Shell";
import { renderWithI18n } from "../test/render";

test("shell renders Chinese navigation by default", () => {
  renderWithI18n(
    <Shell active="overview" onNavigate={vi.fn()}>
      <p>body</p>
    </Shell>,
  );

  expect(screen.getByRole("navigation", { name: "工作台导航" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "概览" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("button", { name: "健康检查" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "DSH 对话" })).toBeInTheDocument();
});

test("shell language toggle switches navigation to English", async () => {
  const user = userEvent.setup();
  renderWithI18n(
    <Shell active="overview" onNavigate={vi.fn()}>
      <p>body</p>
    </Shell>,
  );

  await user.click(screen.getByRole("button", { name: "EN" }));

  expect(screen.getByRole("navigation", { name: "Workbench navigation" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Overview" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(screen.getByRole("button", { name: "中" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("button", { name: "EN" })).toHaveAttribute("aria-pressed", "true");
});
```

These tests catch untranslated navigation and a toggle that changes state but not visible labels.

- [ ] **Step 2: Run the shell tests to verify they fail**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- src/__tests__/components.test.tsx
```

Expected: fail because `renderWithI18n` does not exist and `Shell` still renders English literals.

- [ ] **Step 3: Create `renderWithI18n`**

Create `integrations/paper-rag-workbench/src/test/render.tsx`:

```tsx
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement } from "react";

import { I18nProvider } from "../i18n";

export function renderWithI18n(ui: ReactElement, options?: RenderOptions) {
  return render(<I18nProvider>{ui}</I18nProvider>, options);
}
```

- [ ] **Step 4: Wrap App with `I18nProvider`**

Modify `integrations/paper-rag-workbench/src/App.tsx`:

```tsx
import { I18nProvider } from "./i18n";

export function App() {
  const [route, setRoute] = useState<RouteId>("overview");
  const client = useMemo(() => createWorkbenchClient(), []);

  return (
    <I18nProvider>
      <Shell active={route} onNavigate={setRoute}>
        {route === "health" ? <HealthPage client={client} /> : null}
        {route === "library" ? <LibraryPage client={client} /> : null}
        {route === "search" ? <SearchPage client={client} /> : null}
        {route === "ask" ? <AskPage client={client} /> : null}
        {route === "discover" ? <DiscoverPage client={client} /> : null}
        {route === "overview" ? <OverviewPage client={client} /> : null}
      </Shell>
    </I18nProvider>
  );
}
```

- [ ] **Step 5: Translate Shell and add the toggle**

Modify `integrations/paper-rag-workbench/src/components/Shell.tsx`:

```tsx
import { Activity, BookOpen, Compass, Database, MessageSquare, Search, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { useI18n, type MessageKey } from "../i18n";

const nav = [
  { id: "overview", labelKey: "nav.overview", icon: Database },
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
      </aside>
      <section className="workspace">{children}</section>
    </main>
  );
}
```

- [ ] **Step 6: Style the toggle**

Add to `integrations/paper-rag-workbench/src/styles.css` near sidebar styles:

```css
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.language-toggle {
  display: inline-grid;
  grid-template-columns: 1fr 1fr;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  overflow: hidden;
}

.language-toggle button {
  min-width: 38px;
  min-height: 30px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #d7dee8;
  font-size: 0.82rem;
  font-weight: 700;
}

.language-toggle button[aria-pressed="true"] {
  background: #1f5e9d;
  color: #fff;
}
```

- [ ] **Step 7: Run the shell tests to verify they pass**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- src/__tests__/components.test.tsx
```

Expected: all component tests pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add integrations/paper-rag-workbench/src/App.tsx integrations/paper-rag-workbench/src/components/Shell.tsx integrations/paper-rag-workbench/src/styles.css integrations/paper-rag-workbench/src/test/render.tsx integrations/paper-rag-workbench/src/__tests__/components.test.tsx
git commit -m "feat: add workbench language toggle"
```

---

### Task 3: Translate Pages and Component Chrome

**Files:**
- Modify: all pages and component files listed in File Structure.
- Modify: `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx`

**Interfaces:**
- Consumes: `useI18n().t`.
- Produces: Chinese-first Workbench-owned UI copy across the existing workflow.

- [ ] **Step 1: Write failing page-flow assertions in Chinese**

Update `integrations/paper-rag-workbench/src/__tests__/pages.test.tsx` so every render uses `renderWithI18n`:

```tsx
import { renderWithI18n } from "../test/render";
```

Replace `render(...)` calls with `renderWithI18n(...)` for page components that use `useI18n`.

Change representative assertions:

```tsx
expect(screen.getByRole("heading", { name: "概览" })).toBeInTheDocument();
expect(screen.getByRole("link", { name: /打开 DSH 对话/ })).toHaveAttribute(
  "href",
  "http://127.0.0.1:3080",
);
```

```tsx
await waitForElementToBeRemoved(() => screen.queryByText(/正在加载论文库/));
await user.type(screen.getByLabelText(/筛选论文/), "2005");
await user.click(screen.getByRole("button", { name: /open section self-rag/i }));
expect(await screen.findByRole("heading", { name: /引言|introduction/i })).toBeInTheDocument();
```

```tsx
await user.type(screen.getByLabelText(/检索证据/), "reflection tokens");
await user.click(screen.getByRole("button", { name: /^检索$/ }));
expect(await screen.findByText("chunk:chunk-self-rag-1")).toBeInTheDocument();
```

```tsx
await user.type(screen.getByLabelText(/问题/), "What is Self-RAG?");
await user.click(screen.getByRole("button", { name: /^提问$/ }));
expect(await screen.findByRole("heading", { name: /执行轨迹/ })).toBeInTheDocument();
expect(screen.getByRole("button", { name: /复制 DSH 提示词/ })).toBeInTheDocument();
```

```tsx
await user.type(screen.getByLabelText(/主题/), "agentic rag");
await user.click(screen.getByRole("button", { name: /^发现$/ }));
await user.click(screen.getByRole("button", { name: /入库所选/ }));
expect(screen.getByText(/写入索引论文和分块/)).toBeInTheDocument();
await user.click(screen.getByRole("button", { name: /批准入库/ }));
```

These tests catch untranslated page titles, labels, submit buttons, and approval copy while still allowing dynamic paper content to remain English.

- [ ] **Step 2: Run page tests to verify they fail**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- src/__tests__/pages.test.tsx
```

Expected: fail on English-only UI labels.

- [ ] **Step 3: Translate page chrome**

For each page, import `useI18n`:

```tsx
import { useI18n } from "../i18n";
```

Add inside the component:

```tsx
const { t } = useI18n();
```

Replace Workbench-owned literal strings:

- `OverviewPage.tsx`
  - `Overview` -> `t("overview.title")`
  - subtitle -> `t("overview.subtitle")`
  - `Open DSH Chat` -> `t("overview.openDsh")`
  - metric labels -> `overview.papers`, `overview.chunks`, `overview.model`, `overview.credentials`
  - `Configured` / `Missing` -> `overview.configured` / `overview.missing`
  - loading/error titles -> `overview.loading`, `overview.unavailable`
- `HealthPage.tsx`
  - title/subtitle -> `health.title`, `health.subtitle`
  - `Send diagnostics to DSH` -> `health.sendToDsh`
  - loading/error -> `health.loadingTitle`, `health.loadingDetail`, `health.unavailable`
  - `Quality Issues` -> `health.qualityIssues`
- `LibraryPage.tsx`
  - title/subtitle/filter/loading/error -> `library.*`
  - section heading `Introduction` -> `library.introduction`
  - page fallback `source` -> `chunk.source`
- `SearchPage.tsx`
  - title/subtitle/form/error/results/send -> `search.*`
- `AskPage.tsx`
  - title/subtitle/form/error/buttons/copy state -> `ask.*`
- `DiscoverPage.tsx`
  - title/subtitle/form/error/buttons/selected count/receipt/loading -> `discover.*`

Keep these values unchanged because they are data or protocol content:

```tsx
"arxiv:2310.11511, arxiv:2005.11401"
"deepseek-v4-flash"
"http://127.0.0.1:3080"
"discovery_candidate_ingest"
"real-library"
```

- [ ] **Step 4: Translate component chrome**

Use `useI18n().t` in these components:

- `AgentTimeline.tsx`
  - `Agent Timeline` -> `timeline.title`
  - `running` -> `timeline.running`
- `AnswerPanel.tsx`
  - `Answer` -> `answer.title`
- `ApprovalDialog.tsx`
  - title, candidate ids, button labels, and effect list -> `approval.*`
- `CandidateTable.tsx`
  - table headers and candidate-only note -> `candidate.*`
- `ChunkDetailPanel.tsx`
  - open paper button and metadata labels -> `chunkDetail.*`
- `CitationChips.tsx`
  - no citations and aria label -> `answer.noCitations`, `answer.citationsAria`
- `DshHandoffDialog.tsx`
  - dialog title, close aria label, copy/open buttons -> `handoff.*`
- `EvidenceChunkCard.tsx`
  - page/source/score labels -> `chunk.*`
- `HealthSummary.tsx`
  - `Index Health` -> `health.indexTitle`
  - static diagnostic labels that are not product names can be translated only if message keys already exist; keep `SQLite`, `Qdrant`, `LLM`, and `FTS` unchanged.
- `PaperDetailPanel.tsx`
  - `Sections`, `Chunks`, and unknown section -> `paperDetail.*`
- `PaperTable.tsx`
  - headers -> existing or new `paperTable.*` keys added to both dictionaries.
- `QualityIssueTable.tsx`
  - empty state and headers -> `quality.*`
- `ScoreBreakdown.tsx`
  - keep metric keys `score`, `dense`, `sparse`, `rrf`, `rerank` unchanged because they are retrieval debug labels.

If a component needs a new key not listed in Task 1, add it to both `messages.en` and `messages.zh` in the same edit. Do not use an English fallback in production components.

- [ ] **Step 5: Run page/component tests to verify they pass**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test -- src/__tests__/pages.test.tsx src/__tests__/components.test.tsx
```

Expected: all updated UI tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add integrations/paper-rag-workbench/src/pages integrations/paper-rag-workbench/src/components integrations/paper-rag-workbench/src/i18n.tsx integrations/paper-rag-workbench/src/__tests__/pages.test.tsx integrations/paper-rag-workbench/src/__tests__/components.test.tsx
git commit -m "feat: localize workbench ui"
```

---

### Task 4: Fixture E2E, Build, Docs, and Final Verification

**Files:**
- Modify: `integrations/paper-rag-workbench/tests/workbench.spec.ts`
- Modify: `integrations/paper-rag-workbench/README.md`

**Interfaces:**
- Consumes: translated UI from Tasks 1-3.
- Produces: fixture smoke coverage for Chinese default plus English toggle.

- [ ] **Step 1: Update Playwright fixture smoke to assert Chinese default**

Modify `integrations/paper-rag-workbench/tests/workbench.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("workbench bilingual fixture flow", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: /工作台导航/ });

  await expect(page.getByRole("heading", { name: "概览" })).toBeVisible();
  await expect(nav.getByRole("button", { name: "概览" })).toHaveAttribute("aria-current", "page");

  await page.getByRole("button", { name: "EN" }).click();
  await expect(page.getByRole("navigation", { name: /Workbench navigation/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  await page.getByRole("button", { name: "中" }).click();
  await expect(page.getByRole("heading", { name: "概览" })).toBeVisible();

  await nav.getByRole("button", { name: /健康检查/ }).click();
  await expect(page.getByRole("heading", { name: "健康检查", exact: true })).toBeVisible();
  await expect(page.getByText(/Dense retrieval is unavailable/i)).toBeVisible();

  await nav.getByRole("button", { name: /论文库/ }).click();
  await expect(page.getByText(/Self-RAG/)).toBeVisible();
  await page.getByRole("button", { name: /inspect paper self-rag/i }).click();
  await expect(page.getByText(/Abstract/)).toBeVisible();

  await nav.getByRole("button", { name: /^检索$/ }).click();
  await page.getByLabel(/检索证据/).fill("reflection tokens");
  await page.locator("form").getByRole("button", { name: /^检索$/ }).click();
  await page.getByRole("button", { name: /inspect chunk chunk-self-rag-1/i }).click();
  await expect(page.getByText(/critiques its own generations/i)).toBeVisible();

  await nav.getByRole("button", { name: /^问答$/ }).click();
  await page.getByLabel(/问题/).fill("What is Self-RAG?");
  await page.locator("form").getByRole("button", { name: /^提问$/ }).click();
  await expect(page.getByRole("heading", { name: /执行轨迹/ })).toBeVisible();
  await expect(page.getByText(/Understanding question/i)).toBeVisible();
  await page.getByRole("button", { name: /chunk-self-rag-1/i }).click();
  await expect(page.getByText(/critiques its own generations/i)).toBeVisible();
  await page.getByRole("button", { name: /发送到 DSH/ }).click();
  await expect(page.getByRole("dialog", { name: /发送到 DSH/ })).toBeVisible();
  await page.getByRole("button", { name: /关闭 DSH 交接/ }).click();

  await nav.getByRole("button", { name: /发现/ }).click();
  await page.getByLabel(/主题/).fill("agentic rag");
  await page.locator("form").getByRole("button", { name: /^发现$/ }).click();
  await page.getByLabel(/select candidate 11/i).check();
  await page.getByRole("button", { name: /入库所选/ }).click();
  await expect(page.getByText(/写入索引论文和分块/)).toBeVisible();
});
```

This catches regressions where the SPA still boots in English, the toggle does not update the shell, or translated labels break the core Workbench flow.

- [ ] **Step 2: Run Playwright to verify the updated smoke passes**

Run:

```bash
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
```

Expected: Playwright fixture test passes.

- [ ] **Step 3: Update README**

Add a short section to `integrations/paper-rag-workbench/README.md`:

```md
## Language

Workbench starts in Chinese by default. Use the `中 / EN` toggle in the sidebar
to switch the interface language. The selection is stored in browser
`localStorage` under `paper-rag-workbench-language`.

Only Workbench-owned UI copy is localized. Paper titles, abstracts, evidence
chunks, citations, raw backend errors, and model answers remain in their source
language.
```

- [ ] **Step 4: Run full frontend verification**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
```

Expected: Vitest, TypeScript/Vite build, and Playwright all pass.

- [ ] **Step 5: Run secret scan and git status**

Run:

```bash
.venv/bin/python scripts/secret_scan.py
git status --short
```

Expected:

```text
secret scan: clean
```

and `git status --short` only shows intended doc/code/test changes before commit.

- [ ] **Step 6: Commit Task 4**

```bash
git add integrations/paper-rag-workbench/tests/workbench.spec.ts integrations/paper-rag-workbench/README.md
git commit -m "test: cover bilingual workbench flow"
```

- [ ] **Step 7: Final clean verification**

Run:

```bash
pnpm --dir integrations/paper-rag-workbench test
pnpm --dir integrations/paper-rag-workbench build
VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright
.venv/bin/python scripts/secret_scan.py
git status --short --branch
```

Expected:

- frontend unit tests pass,
- build passes,
- Playwright fixture smoke passes,
- secret scan is clean,
- branch is clean after commits.

---

## Self-Review

- Spec coverage: This plan implements the spec's Chinese default, English toggle, persistence key, translated Workbench chrome, dynamic research-content preservation, fixture-flow verification, README update, secret scan, clean git status, and no new dependency constraint.
- Scope control: Compare, Collections, Notes, Literature Review, Annotated Bibliography, Related Work, Evidence Pack export, PDF export, and BibTeX export are intentionally excluded and listed as future specs.
- Type consistency: `Language`, `MessageKey`, `I18nProvider`, `useI18n`, `resolveInitialLanguage`, and `formatMessage` are defined in Task 1 and consumed in later tasks with matching names.
- Red-flag scan: No deferred-work markers or unspecified test steps remain. Any new translation key required during Task 3 must be added to both dictionaries in the same edit.
