import { open, rm, mkdir } from "node:fs/promises";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

import { pathsFor } from "./paths.mjs";

export async function withRuntimeLock(paths = pathsFor(), callback, options = {}) {
  const timeoutMs = options.timeoutMs ?? 30_000;
  const pollMs = options.pollMs ?? 25;
  const lockPath = options.lockPath ?? join(paths.runtimeRoot, ".runtime.lock");
  const started = Date.now();
  await mkdir(paths.runtimeRoot, { recursive: true });

  let handle;
  while (handle === undefined) {
    try {
      handle = await open(lockPath, "wx");
      await handle.writeFile(`${process.pid}\n`);
    } catch (error) {
      if (error?.code !== "EEXIST") {
        throw error;
      }
      if (Date.now() - started > timeoutMs) {
        throw new Error(`timed out waiting for DeepSeek Harness runtime lock: ${lockPath}`);
      }
      await delay(pollMs);
    }
  }

  try {
    return await callback();
  } finally {
    await handle.close();
    await rm(lockPath, { force: true });
  }
}
