"""Format chunks into LLM-friendly evidence blocks."""

from __future__ import annotations


def format_evidence(chunks: list[dict]) -> str:
    parts = []
    for c in chunks:
        cid = c.get("chunk_id")
        head = (
            "EVIDENCE CHUNK\n"
            f"Use this exact citation token when citing this chunk: [chunk:{cid}]\n"
            f"paper_id={c.get('paper_id')} section={c.get('section')} "
            f"modality={c.get('modality')} score={c.get('score', 0):.3f}"
        )
        body = (c.get("text") or "").strip()
        parts.append(f"{head}\n{body}")
    return "\n\n---\n\n".join(parts)
