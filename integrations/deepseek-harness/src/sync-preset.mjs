import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { pathsFor } from "./paths.mjs";

export async function syncPaperResearchPreset(paths = pathsFor()) {
  await mkdir(paths.presetDestDir, { recursive: true });
  const entries = await readdir(paths.presetSourceDir, { withFileTypes: true });
  await Promise.all(
    entries.map((entry) =>
      copyEntry(join(paths.presetSourceDir, entry.name), join(paths.presetDestDir, entry.name), entry),
    ),
  );
  return {
    id: paths.presetId,
    sourceDir: paths.presetSourceDir,
    destDir: paths.presetDestDir,
  };
}

async function copyEntry(source, dest, entry) {
  if (entry.isDirectory()) {
    await mkdir(dest, { recursive: true });
    const children = await readdir(source, { withFileTypes: true });
    await Promise.all(
      children.map((child) => copyEntry(join(source, child.name), join(dest, child.name), child)),
    );
    return;
  }
  if (!entry.isFile()) {
    return;
  }
  await writeFile(dest, await readFile(source));
}
