"""Section splitter for markdown and PDF-extracted academic text.

Returns a list of sections in document order. Each section keeps its
original markdown body (including images / tables / formulas).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADER_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.MULTILINE)
_PAGE_RE = re.compile(r"^<!--\s*page\s+\d+\s*-->$")
_STANDALONE_NUM_RE = re.compile(r"^(?:\d+(?:\.\d+)*|[IVX]+)\.?$", re.IGNORECASE)
_INLINE_NUM_TITLE_RE = re.compile(r"^(?:\d+(?:\.\d+)*|[IVX]+)\.?\s+(.+?)\s*$", re.IGNORECASE)
_ABSTRACT_INLINE_RE = re.compile(r"^(abstract)\s*[-—–:]\s*", re.IGNORECASE)

_CANONICAL_HEADINGS = (
    "abstract",
    "introduction",
    "background",
    "related work",
    "overview",
    "preliminaries",
    "problem formulation",
    "method",
    "methods",
    "methodology",
    "approach",
    "model",
    "framework",
    "architecture",
    "retrieval",
    "generation",
    "augmentation",
    "augmentation process",
    "training",
    "implementation",
    "experimental setup",
    "experiment",
    "experiments",
    "evaluation",
    "evaluation metric",
    "results",
    "results and analysis",
    "analysis",
    "discussion",
    "discussion and future prospects",
    "discussion and limitations",
    "limitations",
    "conclusion",
    "conclusions",
    "future work",
    "ethical concerns",
    "acknowledgments",
    "acknowledgements",
    "references",
    "appendix",
)
_CANONICAL_SET = set(_CANONICAL_HEADINGS)
_CANONICAL_PREFIXES = ("appendix ",)
_DESCRIPTIVE_KEYWORDS = (
    "retrieval",
    "generation",
    "hallucination",
    "mitigation",
    "prompt",
    "tuning",
    "decoding",
    "faithfulness",
    "fine-tuning",
    "finetuning",
    "query",
    "confidence",
    "flare",
    "evaluation",
    "setup",
    "results",
    "analysis",
    "dataset",
    "training",
    "method",
)
_BAD_HEADING_PREFIXES = (
    "fig.",
    "figure ",
    "table ",
    "algorithm ",
)
_TABLE_CONTEXT_RE = re.compile(r"^(?:table|fig\.|figure)\b", re.IGNORECASE)


@dataclass
class RawSection:
    idx: int
    name: str
    level: int
    start: int
    end: int
    body: str


@dataclass
class _Line:
    start: int
    end: int
    text: str


@dataclass
class _Header:
    start: int
    end: int
    name: str
    level: int
    source: str


def split_sections(md: str) -> list[RawSection]:
    headers = _dedupe_headers(_filter_reference_tail(_collect_headers(md)))
    if not headers:
        return [RawSection(idx=0, name="Body", level=1, start=0, end=len(md), body=md.strip())]

    sections: list[RawSection] = []
    for i, m in enumerate(headers):
        start = m.end
        end = headers[i + 1].start if i + 1 < len(headers) else len(md)
        body = md[start:end].strip()
        sections.append(
            RawSection(
                idx=i,
                name=m.name,
                level=m.level,
                start=start,
                end=end,
                body=body,
            )
        )
    return sections


def _collect_headers(md: str) -> list[_Header]:
    lines = _lines(md)
    headers: list[_Header] = []
    for m in _HEADER_RE.finditer(md):
        name = _clean_heading(m.group(2))
        if _valid_markdown_heading(name):
            headers.append(_Header(m.start(), m.end(), name, len(m.group(1)), "markdown"))

    for i, line in enumerate(lines):
        headers.extend(_plain_headers_at(lines, i))
    headers.sort(key=lambda h: (h.start, h.end))
    return headers


def _lines(md: str) -> list[_Line]:
    out: list[_Line] = []
    pos = 0
    for raw in md.splitlines(keepends=True):
        end = pos + len(raw)
        out.append(_Line(pos, end, raw.rstrip("\r\n")))
        pos = end
    if not out and md:
        out.append(_Line(0, len(md), md))
    return out


def _plain_headers_at(lines: list[_Line], i: int) -> list[_Header]:
    line = lines[i]
    stripped = line.text.strip()
    if not stripped:
        return []

    inline = _ABSTRACT_INLINE_RE.match(stripped)
    if inline:
        end = line.start + line.text.index(inline.group(0)) + len(inline.group(0))
        return [_Header(line.start, end, "Abstract", 1, "plain")]

    next_line = _next_nonempty(lines, i + 1)
    if _STANDALONE_NUM_RE.match(stripped) and next_line:
        title = _clean_heading(next_line.text)
        if (
            _valid_heading_name(title, allow_descriptive=True)
            and (_is_canonical_heading(title) or not _before_first_abstract(lines, i))
        ):
            return [_Header(line.start, next_line.end, title, _level_from_number(stripped), "plain")]

    numbered = _INLINE_NUM_TITLE_RE.match(stripped)
    if numbered:
        title = _clean_heading(numbered.group(1))
        if _valid_heading_name(title, allow_descriptive=True):
            return [_Header(line.start, line.end, title, _level_from_number(stripped), "plain")]

    name = _clean_heading(stripped)
    if (
        _valid_heading_name(name)
        and (name.lower() in {"abstract", "references"} or _paragraph_boundary_before(lines, i))
        and (name.lower() in {"abstract", "references"} or not _table_context_before(lines, i))
    ):
        return [_Header(line.start, line.end, name, 1, "plain")]
    return []


def _next_nonempty(lines: list[_Line], start: int) -> _Line | None:
    for line in lines[start:]:
        if line.text.strip():
            return line
    return None


def _paragraph_boundary_before(lines: list[_Line], i: int) -> bool:
    for prev in reversed(lines[:i]):
        text = prev.text.strip()
        if not text:
            return True
        if _PAGE_RE.match(text) or _STANDALONE_NUM_RE.match(text):
            return True
        return False
    return True


def _before_first_abstract(lines: list[_Line], i: int) -> bool:
    for line in lines[:i]:
        text = line.text.strip()
        if _clean_heading(text).lower() == "abstract" or _ABSTRACT_INLINE_RE.match(text):
            return False
    return True


def _table_context_before(lines: list[_Line], i: int) -> bool:
    checked = 0
    for prev in reversed(lines[:i]):
        text = prev.text.strip()
        if not text or _PAGE_RE.match(text):
            continue
        checked += 1
        if _TABLE_CONTEXT_RE.match(text):
            return True
        if checked >= 2:
            return False
    return False


def _level_from_number(value: str) -> int:
    value = value.strip().rstrip(".")
    if re.match(r"^[IVX]+$", value, re.IGNORECASE):
        return 1
    return min(value.count(".") + 1, 4)


def _clean_heading(value: str) -> str:
    value = re.sub(r"^#+\s*", "", value.strip())
    value = re.sub(r"^(?:\d+(?:\.\d+)*|[IVX]+)\.?\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" \t:.-—–")
    return value


def _valid_heading_name(name: str, *, allow_descriptive: bool = False) -> bool:
    if not name:
        return False
    low = name.lower().strip()
    if any(low.startswith(prefix) for prefix in _BAD_HEADING_PREFIXES):
        return False
    if _is_canonical_heading(name):
        return True
    if not allow_descriptive:
        return False
    if len(name) > 120 or len(name.split()) > 12:
        return False
    if len(name) < 3 or len(name.split()) < 2:
        return False
    if re.search(r"[\[\]{}()]", name):
        return False
    if name.endswith("-"):
        return False
    alpha = [c for c in name if c.isalpha()]
    if not alpha:
        return False
    uppercase_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
    if uppercase_ratio >= 0.85:
        return True
    return name[0].isupper() and any(keyword in low for keyword in _DESCRIPTIVE_KEYWORDS)


def _is_canonical_heading(name: str) -> bool:
    low = name.lower().strip()
    return low in _CANONICAL_SET or any(low.startswith(prefix) for prefix in _CANONICAL_PREFIXES)


def _valid_markdown_heading(name: str) -> bool:
    if not name:
        return False
    if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", name):
        return False
    return True


def _dedupe_headers(headers: list[_Header]) -> list[_Header]:
    out: list[_Header] = []
    for h in sorted(headers, key=lambda x: (x.start, x.end)):
        if out and h.start < out[-1].end:
            prev = out[-1]
            if h.source == "markdown" and prev.source != "markdown":
                out[-1] = h
            continue
        if out and h.start == out[-1].start and h.name.lower() == out[-1].name.lower():
            continue
        out.append(h)
    return out


def _filter_reference_tail(headers: list[_Header]) -> list[_Header]:
    out: list[_Header] = []
    in_references = False
    for h in headers:
        low = h.name.lower()
        if in_references and not low.startswith("appendix"):
            continue
        out.append(h)
        if low == "references":
            in_references = True
        elif low.startswith("appendix"):
            in_references = False
    return out
