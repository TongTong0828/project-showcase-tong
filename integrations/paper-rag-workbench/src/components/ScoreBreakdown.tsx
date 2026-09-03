import type { EvidenceChunk } from "../types";

export function ScoreBreakdown({ chunk }: { chunk: EvidenceChunk & Record<string, unknown> }) {
  const pairs = [
    ["score", chunk.score],
    ["dense", chunk.dense_score],
    ["sparse", chunk.sparse_score],
    ["rrf", chunk.rrf_score],
    ["rerank", chunk.rerank_score],
  ].filter((item): item is [string, number] => typeof item[1] === "number");

  if (pairs.length === 0) return null;

  return (
    <dl className="score-breakdown">
      {pairs.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>
            {label} {value.toFixed(2)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
