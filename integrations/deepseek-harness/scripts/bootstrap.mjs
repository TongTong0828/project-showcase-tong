#!/usr/bin/env node
import { mkdir } from "node:fs/promises";

import { pathsFor } from "../src/paths.mjs";
import { syncPaperResearchPreset } from "../src/sync-preset.mjs";

export async function bootstrap(paths = pathsFor()) {
  await mkdir(paths.dshHome, { recursive: true });
  await mkdir(paths.sessionRoot, { recursive: true });
  await mkdir(paths.storageRoot, { recursive: true });
  await mkdir(paths.credentialsDir, { recursive: true });
  await mkdir(paths.artifactsRoot, { recursive: true });
  await mkdir(paths.importsRoot, { recursive: true });
  const preset = await syncPaperResearchPreset(paths);
  return { paths, preset };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const result = await bootstrap();
  console.log(
    JSON.stringify(
      {
        dsh_home: result.paths.dshHome,
        credentials_path: result.paths.credentialsPath,
        preset: result.preset.destDir,
      },
      null,
      2,
    ),
  );
}
