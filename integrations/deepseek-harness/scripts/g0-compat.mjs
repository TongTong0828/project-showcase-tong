#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

import { runBrokerCompatibilityProbe } from "../src/broker-probe.mjs";
import { pathsFor } from "../src/paths.mjs";
import { buildG0CompatReport, writeJsonAtomic } from "../src/report.mjs";
import { runDoctor } from "./doctor.mjs";

function argValue(name) {
  const index = process.argv.indexOf(name);
  return index === -1 ? undefined : process.argv[index + 1];
}

function git(paths, args) {
  const proc = spawnSync("git", args, {
    cwd: paths.repoRoot,
    encoding: "utf8",
  });
  if (proc.status !== 0) {
    throw new Error(proc.stderr || proc.stdout || `git ${args.join(" ")} failed`);
  }
  return proc.stdout.trim();
}

try {
  const paths = pathsFor();
  const doctor = await runDoctor(paths);
  const brokerProbe = await runBrokerCompatibilityProbe(paths);
  const report = buildG0CompatReport({
    commit: git(paths, ["rev-parse", "HEAD"]),
    dirty: git(paths, ["status", "--porcelain"]).length > 0,
    paths,
    configAudit: doctor.audit,
    presetDiscovery: doctor.preset,
    brokerProbe,
  });
  const reportPath = argValue("--report");
  if (reportPath !== undefined) {
    await writeJsonAtomic(resolve(process.cwd(), reportPath), report);
  }
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
