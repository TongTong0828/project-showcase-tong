import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test } from "vitest";

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
