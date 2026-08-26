"""Lazy local vision-model fallback."""

from __future__ import annotations

from .api import _PROMPT, _summary_from_payload
from .schema import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    VisualSummaryRequest,
    VisualSummaryResult,
)


class LocalVisionSummarizer:
    """Qwen2.5-VL-compatible fallback that is unavailable unless deps exist."""

    def __init__(self, model: str = "Qwen/Qwen2.5-VL-7B-Instruct"):
        self.model = model
        self._model = None
        self._processor = None

    def summarize(self, request: VisualSummaryRequest) -> VisualSummaryResult:
        try:
            self._ensure_loaded()
        except Exception as exc:
            return VisualSummaryResult(
                status=STATUS_UNAVAILABLE,
                provider="local",
                model=self.model,
                error=str(exc),
            )

        try:
            from PIL import Image

            image = Image.open(request.asset_path).convert("RGB")
            prompt = (
                f"{_PROMPT}\n\nCaption: {request.caption or '(none)'}\n"
                f"Nearby context: {request.surrounding_context or '(none)'}"
            )
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            text = self._processor.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
            inputs = self._processor(text=[text], images=[image], return_tensors="pt")
            output = self._model.generate(**inputs, max_new_tokens=700)
            decoded = self._processor.batch_decode(output, skip_special_tokens=True)[0]
            raw = _try_json(decoded)
            return VisualSummaryResult(
                status=STATUS_OK,
                summary=_summary_from_payload(raw) if raw else decoded.strip(),
                provider="local",
                model=self.model,
                raw=raw,
            )
        except Exception as exc:
            return VisualSummaryResult(
                status=STATUS_FAILED,
                provider="local",
                model=self.model,
                error=str(exc),
            )

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._processor is not None:
            return
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

        self._processor = AutoProcessor.from_pretrained(self.model)
        self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.model,
            device_map="auto",
        )


def _try_json(text: str):
    from .api import _loads_json

    return _loads_json(text)
