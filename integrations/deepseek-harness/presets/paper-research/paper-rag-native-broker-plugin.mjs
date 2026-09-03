import { join } from "node:path";
import { pathToFileURL } from "node:url";

export const name = "paper-rag-native-broker";
export const inject = ["tools", "credentials"];

export async function apply(ctx) {
  const repoRoot = process.env.PAPER_RAG_REPO_ROOT ?? process.cwd();
  const implementation = pathToFileURL(
    join(repoRoot, "integrations/deepseek-harness/src/paper-rag-native-broker-plugin.mjs"),
  ).href;
  const plugin = await import(implementation);
  return plugin.apply(ctx);
}
