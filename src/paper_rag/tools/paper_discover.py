"""paper_discover tool entry."""

from __future__ import annotations

from ._schema import PaperDiscoverInput


def paper_discover(input: PaperDiscoverInput) -> dict:
    from ..discovery.runner import run_discovery

    return run_discovery(
        input.topic,
        user_id="tool",
        source_names=input.sources,
        max_candidates=input.max_candidates,
    )
