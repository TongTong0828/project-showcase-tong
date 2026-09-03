#!/usr/bin/env node
import { spawn } from "node:child_process";

import { dshEnvironment, pathsFor } from "../src/paths.mjs";
import { bootstrap } from "./bootstrap.mjs";

const paths = pathsFor();
await bootstrap(paths);

const child = spawn(
  paths.dshBin,
  [
    "web",
    "--patch",
    paths.patchPath,
    "--host",
    paths.defaultHost,
    "--port",
    paths.defaultPort,
  ],
  {
    cwd: paths.repoRoot,
    env: dshEnvironment(paths),
    stdio: "inherit",
  },
);

child.on("exit", (code, signal) => {
  if (signal !== null) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code ?? 0);
  }
});
