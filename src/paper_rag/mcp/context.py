"""Trusted MCP request context and server configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_TOOLSETS = {"readonly", "research", "full"}


@dataclass(frozen=True)
class McpServerConfig:
    toolset: str = "readonly"
    actor_id: str = "system"
    artifact_root: Path | None = None
    import_root: Path | None = None

    def __post_init__(self) -> None:
        if self.toolset not in VALID_TOOLSETS:
            raise ValueError(f"invalid MCP toolset: {self.toolset}")
        if not self.actor_id:
            raise ValueError("actor_id must be non-empty")

    @classmethod
    def from_env(cls) -> "McpServerConfig":
        artifact_root = os.environ.get("PAPER_RAG_ARTIFACT_ROOT")
        import_root = os.environ.get("PAPER_RAG_IMPORT_ROOT")
        return cls(
            toolset=os.environ.get("PAPER_RAG_MCP_TOOLSET", "readonly"),
            actor_id=os.environ.get("PAPER_RAG_ACTOR_ID", "system"),
            artifact_root=Path(artifact_root).resolve() if artifact_root else None,
            import_root=Path(import_root).resolve() if import_root else None,
        )


@dataclass(frozen=True)
class McpRequestContext:
    config: McpServerConfig
    conversation_id: str | None = None
    tool_call_id: str | None = None
    request_boundary_id: str | None = None
    caller: str | None = None

    @property
    def actor_id(self) -> str:
        return self.config.actor_id

    @classmethod
    def from_meta(cls, config: McpServerConfig, meta: dict[str, Any] | None) -> "McpRequestContext":
        paper_rag = (meta or {}).get("paper_rag")
        if not isinstance(paper_rag, dict):
            paper_rag = {}
        return cls(
            config=config,
            conversation_id=_optional_str(paper_rag.get("conversation_id")),
            tool_call_id=_optional_str(paper_rag.get("tool_call_id")),
            request_boundary_id=_optional_str(paper_rag.get("request_boundary_id")),
            caller=_optional_str(paper_rag.get("caller")),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
