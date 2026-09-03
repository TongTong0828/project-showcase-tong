import { join } from "node:path";

import { discoverPresets } from "@deepseek-ai/dsh-agent-presets";

import { pathsFor } from "./paths.mjs";

export async function discoverPaperResearchPreset(paths = pathsFor()) {
  const presets = await discoverPresets([
    { path: join(paths.dshHome, ".agent-presets"), trust: "user" },
  ]);
  const preset = presets.find((item) => item.id === paths.presetId);
  if (preset === undefined) {
    throw new Error(`paper-research preset not discovered under ${paths.dshHome}`);
  }
  return preset;
}
