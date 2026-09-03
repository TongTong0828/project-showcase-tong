#!/usr/bin/env node
import { spawnSync } from "node:child_process";

import { auditDshConfigDump } from "../src/config-audit.mjs";
import { dshEnvironment, pathsFor } from "../src/paths.mjs";
import { discoverPaperResearchPreset } from "../src/preset-discovery.mjs";
import { withRuntimeLock } from "../src/runtime-lock.mjs";
import { bootstrap } from "./bootstrap.mjs";

export function dumpConfig(paths = pathsFor()) {
  const proc = spawnSync(
    paths.dshBin,
    ["web", "--patch", paths.patchPath, "--dump-config"],
    {
      cwd: paths.repoRoot,
      env: dshEnvironment(paths),
      encoding: "utf8",
    },
  );
  if (proc.status !== 0) {
    throw new Error(proc.stderr || proc.stdout || "dsh dump-config failed");
  }
  return proc.stdout;
}

export async function runDoctor(paths = pathsFor()) {
  return withRuntimeLock(paths, async () => {
    await bootstrap(paths);
    const dump = dumpConfig(paths);
    const audit = auditDshConfigDump(dump);
    const preset = await discoverPaperResearchPreset(paths);
    return { dump, audit, paths, preset };
  });
}

const args = new Set(process.argv.slice(2));
if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    const result = await runDoctor();
    if (args.has("--dump-config")) {
      process.stdout.write(result.dump);
    } else {
      console.log(JSON.stringify(result.audit, null, 2));
    }
    if (!result.audit.passed) {
      process.exitCode = 1;
    }
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
