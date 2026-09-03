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

  await nav.getByRole("button", { name: /工作区/ }).click();
  await expect(page.getByRole("heading", { name: "工作区" })).toBeVisible();
  const workspaceCreateForm = page.locator(".workspace > form").first();
  await workspaceCreateForm.getByLabel(/项目名称/).fill("Scoped Notes 调研");
  await workspaceCreateForm.getByRole("button", { name: /创建项目/ }).click();
  await expect(page.getByRole("heading", { name: /Scoped Notes 调研/ })).toBeVisible();
  await page.locator(".note-editor").getByLabel(/^笔记$/).fill("local project note");
  await page.locator(".note-editor").getByRole("button", { name: /保存笔记/ }).click();
  await expect(page.getByText(/local project note/)).toBeVisible();

  await nav.getByRole("button", { name: /健康检查/ }).click();
  await expect(page.getByRole("heading", { name: "健康检查", exact: true })).toBeVisible();
  await expect(page.getByText(/Dense retrieval is unavailable/i)).toBeVisible();

  await nav.getByRole("button", { name: /论文库/ }).click();
  await expect(page.getByRole("cell", { name: /Self-RAG/ }).first()).toBeVisible();
  await page.getByRole("button", { name: /加入项目 self-rag/i }).first().click();
  await expect(page.getByText(/已加入当前项目/)).toBeVisible();
  await page
    .getByRole("button", { name: /加入项目 retrieval-augmented generation/i })
    .first()
    .click();
  await expect(page.getByText(/已加入当前项目/)).toBeVisible();
  await page.getByRole("button", { name: /查看论文 self-rag/i }).click();
  await expect(page.getByText(/Abstract/)).toBeVisible();

  await nav.getByRole("button", { name: /^检索$/ }).click();
  await page.getByLabel(/检索证据/).fill("reflection tokens");
  await page.locator("form").getByRole("button", { name: /^检索$/ }).click();
  await page.getByRole("button", { name: /钉选证据 chunk-self-rag-1/i }).click();
  await expect(page.getByText(/已钉选/)).toBeVisible();
  await page.getByRole("button", { name: /查看分块 chunk-self-rag-1/i }).click();
  await expect(page.getByText(/critiques its own generations/i)).toBeVisible();

  await nav.getByRole("button", { name: /^问答$/ }).click();
  await page.getByLabel(/包含钉选证据/).check();
  await page.getByLabel(/包含笔记/).check();
  await page.getByLabel(/限制到项目论文/).check();
  await page.getByLabel(/问题/).fill("What is Self-RAG?");
  await page.locator("form").getByRole("button", { name: /^提问$/ }).click();
  await expect(page.getByRole("heading", { name: /执行轨迹/ })).toBeVisible();
  await expect(page.getByText(/Understanding question/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: /用户笔记引用/ })).toBeVisible();
  await page.getByRole("button", { name: /保存问答/ }).click();
  await expect(page.getByText(/问答已保存/)).toBeVisible();
  await page.getByRole("button", { name: "chunk-self-rag-1", exact: true }).click();
  await expect(page.getByText(/critiques its own generations/i)).toBeVisible();
  await page.getByRole("button", { name: /发送到 DSH/ }).click();
  await expect(page.getByRole("dialog", { name: /发送到 DSH/ })).toBeVisible();
  await page.getByRole("button", { name: /关闭 DSH 交接/ }).click();

  await nav.getByRole("button", { name: /对比/ }).click();
  await expect(page.getByRole("heading", { name: "对比" })).toBeVisible();
  await page.getByLabel(/方法/).check();
  await page.getByLabel(/限制/).check();
  await page.getByRole("button", { name: /生成对比/ }).click();
  await expect(page.getByText("chunk-self-rag-1").first()).toBeVisible();
  await expect(page.getByText(/No pinned evidence/).first()).toBeVisible();
  await page.getByRole("button", { name: /发送对比到 DSH/ }).click();
  await expect(page.getByRole("dialog", { name: /发送到 DSH/ })).toBeVisible();
  await expect(page.getByText(/Compare run/)).toBeVisible();
  await page.getByRole("button", { name: /关闭 DSH 交接/ }).click();

  await nav.getByRole("button", { name: /工作区/ }).click();
  await expect(page.getByRole("heading", { name: /对比记录/ })).toBeVisible();
  await expect(page.getByText(/compare-1/)).toBeVisible();
  await page.getByLabel(/DSH 任务/).fill("Compare methods.");
  await page.getByRole("button", { name: /发送项目到 DSH/ }).click();
  await expect(page.getByRole("dialog", { name: /发送到 DSH/ })).toBeVisible();
  await expect(page.getByText(/Compare methods/)).toBeVisible();
  await page.getByRole("button", { name: /关闭 DSH 交接/ }).click();

  await nav.getByRole("button", { name: /发现/ }).click();
  await page.getByLabel(/主题/).fill("agentic rag");
  await page.locator("form").getByRole("button", { name: /^发现$/ }).click();
  await page.getByLabel(/选择候选 11/).check();
  await page.getByRole("button", { name: /入库所选/ }).click();
  await expect(page.getByText(/写入索引论文和分块/)).toBeVisible();
});
