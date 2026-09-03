#!/usr/bin/env node
import { pathsFor } from "../src/paths.mjs";
import { syncPaperResearchPreset } from "../src/sync-preset.mjs";

const result = await syncPaperResearchPreset(pathsFor());
console.log(JSON.stringify(result, null, 2));
