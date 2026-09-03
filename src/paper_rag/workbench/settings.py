from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkbenchSettings:
    actor_id: str = "workbench"
    toolset: str = "research"
    dsh_url: str = "http://127.0.0.1:3080"
    credentials_path: Path | None = None
    artifact_root: Path | None = None
    import_root: Path | None = None
    workspace_state_path: Path | None = None
    openai_base_url: str = "https://api.deepseek.com"
    chat_model: str = "deepseek-v4-flash"
    small_model: str = "deepseek-v4-flash"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> WorkbenchSettings:
        source = os.environ if env is None else env
        credentials = source.get("PAPER_RAG_DSH_CREDENTIALS_PATH")
        artifact_root = source.get("PAPER_RAG_ARTIFACT_ROOT")
        import_root = source.get("PAPER_RAG_IMPORT_ROOT")
        workspace_state_path = source.get("PAPER_RAG_WORKBENCH_STATE_PATH")
        return cls(
            actor_id=source.get("PAPER_RAG_WORKBENCH_ACTOR_ID", "workbench"),
            toolset=source.get("PAPER_RAG_WORKBENCH_TOOLSET", "research"),
            dsh_url=source.get("PAPER_RAG_DSH_URL", "http://127.0.0.1:3080"),
            credentials_path=Path(credentials).resolve() if credentials else None,
            artifact_root=Path(artifact_root).resolve() if artifact_root else None,
            import_root=Path(import_root).resolve() if import_root else None,
            workspace_state_path=(
                Path(workspace_state_path).resolve() if workspace_state_path else None
            ),
            openai_base_url=source.get("OPENAI_BASE_URL", "https://api.deepseek.com"),
            chat_model=source.get("CHAT_MODEL", "deepseek-v4-flash"),
            small_model=source.get(
                "SMALL_MODEL",
                source.get("CHAT_MODEL", "deepseek-v4-flash"),
            ),
        )
