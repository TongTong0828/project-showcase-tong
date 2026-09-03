import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_INTEGRATION_ROOT = fileURLToPath(new URL("..", import.meta.url));

function readPackageJson(integrationRoot) {
  return JSON.parse(readFileSync(join(integrationRoot, "package.json"), "utf8"));
}

export function pathsFor(options = {}) {
  const integrationRoot = resolve(options.integrationRoot ?? DEFAULT_INTEGRATION_ROOT);
  const repoRoot = resolve(options.repoRoot ?? join(integrationRoot, "../.."));
  const packageJson = readPackageJson(integrationRoot);
  const dshVersion = packageJson.dependencies["@deepseek-ai/dsh"];
  const cordisVersion = packageJson.dependencies["@deepseek-ai/cordis"];
  const runtimeRoot = join(repoRoot, "data/runtime/deepseek-harness");
  const dshHome = resolve(
    options.dshHome ?? join(runtimeRoot, "versions", dshVersion),
  );

  return {
    repoRoot,
    integrationRoot,
    runtimeRoot,
    dshVersion,
    cordisVersion,
    dshHome,
    sessionRoot: join(dshHome, "sessions"),
    storageRoot: join(dshHome, "storages"),
    credentialsDir: join(runtimeRoot, "credentials"),
    credentialsPath: resolve(
      options.credentialsPath ?? join(runtimeRoot, "credentials/.credentials.yaml"),
    ),
    artifactsRoot: join(repoRoot, "data/artifacts"),
    importsRoot: join(repoRoot, "data/imports"),
    patchPath: join(integrationRoot, "cordis.patch.yml"),
    presetId: "paper-research",
    presetSourceDir: join(integrationRoot, "presets/paper-research"),
    presetDestDir: join(dshHome, ".agent-presets/paper-research"),
    projectSkillRoot: join(repoRoot, ".dsh/skills"),
    dshBin: join(integrationRoot, "node_modules/.bin/dsh"),
    defaultHost: "127.0.0.1",
    defaultPort: String(options.port ?? process.env.PAPER_RAG_DSH_PORT ?? "3080"),
  };
}

export function dshEnvironment(paths = pathsFor(), extra = {}) {
  return {
    ...process.env,
    PAPER_RAG_CONFIG:
      process.env.PAPER_RAG_CONFIG ?? join(paths.repoRoot, "config/local.yaml"),
    OPENAI_BASE_URL:
      process.env.OPENAI_BASE_URL ?? process.env.DEEPSEEK_BASE_URL ?? "https://api.deepseek.com",
    CHAT_MODEL: process.env.CHAT_MODEL ?? "deepseek-v4-flash",
    SMALL_MODEL: process.env.SMALL_MODEL ?? process.env.CHAT_MODEL ?? "deepseek-v4-flash",
    DSH_HOME: paths.dshHome,
    DSH_TELEMETRY_DISABLED: "1",
    DSH_TELEMETRY_MODE: "DISABLED",
    DSH_PERMISSION_MODE: "read-only",
    DSH_TOOLS_MODE: "native",
    PAPER_RAG_REPO_ROOT: paths.repoRoot,
    PAPER_RAG_DSH_CREDENTIALS_PATH: paths.credentialsPath,
    PAPER_RAG_DSH_SKILL_ROOT: paths.projectSkillRoot,
    PAPER_RAG_DSH_PORT: paths.defaultPort,
    ...extra,
  };
}
