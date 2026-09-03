#!/usr/bin/env node
import { runDoctor } from "./doctor.mjs";

try {
  const result = await runDoctor();
  const output = {
    schema_version: 1,
    status: result.audit.passed ? "PASS" : "FAIL",
    checks: result.audit.checks,
    preset: {
      id: result.preset.id,
      path: result.preset.path,
      broken: result.preset.broken,
    },
  };
  console.log(JSON.stringify(output, null, 2));
  if (!result.audit.passed) {
    process.exitCode = 1;
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
