"""OpenAI-compatible vision summarizer."""

from __future__ import annotations

import base64
import json
import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .schema import STATUS_FAILED, STATUS_OK, VisualSummaryRequest, VisualSummaryResult

_PROMPT = """You are summarizing a figure or visual table from an academic paper.
Use the image plus the provided caption and nearby paper context.
Do not invent exact numbers that are not legible.
If text or values are unclear, say "not legible".
Return compact JSON with:
- visual_type
- main_message
- axes_or_dimensions
- key_entities
- trends_or_comparisons
- supports_claim
- limitations_or_uncertainty
"""


class OpenAIVisionSummarizer:
    """Small OpenAI-compatible adapter for one image summary request."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_sec: int = 60,
        client_factory: Callable[[], Any] | None = None,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout_sec = timeout_sec
        self._client_factory = client_factory

    def summarize(self, request: VisualSummaryRequest) -> VisualSummaryResult:
        try:
            resp = self._client().chat.completions.create(
                model=self.model,
                messages=[self._message(request)],
                temperature=0,
                max_tokens=700,
                timeout=self.timeout_sec,
            )
            content = resp.choices[0].message.content or ""
            raw = _loads_json(content)
            summary = _summary_from_payload(raw) if raw else content.strip()
            return VisualSummaryResult(
                status=STATUS_OK,
                summary=summary,
                provider="api",
                model=self.model,
                raw=raw,
            )
        except Exception as exc:
            return VisualSummaryResult(
                status=STATUS_FAILED,
                provider="api",
                model=self.model,
                error=str(exc),
            )

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory()
        from openai import OpenAI

        return OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout_sec)

    def _message(self, request: VisualSummaryRequest) -> dict[str, Any]:
        text = (
            f"{_PROMPT}\n\n"
            f"Paper id: {request.paper_id}\n"
            f"Chunk id: {request.chunk_id}\n"
            f"Modality: {request.modality}\n"
            f"Caption: {request.caption or '(none)'}\n"
            f"Nearby context: {request.surrounding_context or '(none)'}"
        )
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": _data_url(request.asset_path)}},
            ],
        }


def _data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _loads_json(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _summary_from_payload(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    labels = (
        ("visual_type", "Visual type"),
        ("main_message", "Main message"),
        ("axes_or_dimensions", "Axes or dimensions"),
        ("key_entities", "Key entities"),
        ("trends_or_comparisons", "Trends or comparisons"),
        ("supports_claim", "Supports claim"),
        ("limitations_or_uncertainty", "Limitations or uncertainty"),
    )
    for key, label in labels:
        value = payload.get(key)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        parts.append(f"{label}: {value}")
    if parts:
        return "\n".join(parts)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
