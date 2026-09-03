from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CredentialStatus:
    configured: bool
    source: str | None
    writable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "source": self.source,
            "writable": self.writable,
        }


def credential_status(
    env: Mapping[str, str] | None = None,
    credentials_path: Path | None = None,
) -> CredentialStatus:
    source = os.environ if env is None else env
    if source.get("DEEPSEEK_API_KEY") or source.get("OPENAI_API_KEY"):
        return CredentialStatus(configured=True, source="env", writable=False)
    if credentials_path is not None and credentials_path.exists():
        text = credentials_path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        if isinstance(data, dict) and (
            data.get("DEEPSEEK_API_KEY") or data.get("OPENAI_API_KEY")
        ):
            return CredentialStatus(configured=True, source="file", writable=True)
    return CredentialStatus(configured=False, source=None, writable=True)
