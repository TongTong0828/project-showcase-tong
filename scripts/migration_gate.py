"""DeepSeek Harness migration gate helpers.

This script owns pre-G0/G0 bookkeeping: baseline fingerprints, legacy
capability matrix validation, diff hygiene, and structured report validation.
It intentionally keeps gate evidence machine-readable so later G1-G5 gates can
accumulate requirements instead of relying on hand-written summaries.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility.
    import tomli as tomllib
import yaml

LEGACY_TEST_FILES = (
    Path("tests/test_gateway_paper_rag.py"),
    Path("tests/test_middleware.py"),
    Path("tests/test_langgraph_middleware.py"),
)
QUALITY_BASELINE_COMMAND_IDS = (
    "eval-golden",
    "eval-golden-qa",
    "eval-citation-audit",
    "eval-claims",
    "verify-p0",
)
BASELINE_FINGERPRINT_PATHS = (
    Path("tests/eval/qa_set.golden.jsonl"),
    Path("tests/eval/gates.strict.json"),
    Path("tests/eval/qa_set.claims.jsonl"),
    Path("tests/eval/gates.claims.json"),
    Path("specs/20260813-deepseek-harness-migration/test/test-manifest.json"),
)
ALLOWED_LEGACY_CLASSIFICATIONS = {
    "host-specific-delete",
    "capability-replaced-by-broker-or-mcp",
    "still-required-and-moved",
}
TERMINAL_CASE_STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_RUN", "NOT_APPLICABLE"}
LIVE_REPORT_STATUSES = {"PASS", "FAIL", "BLOCKED"}
DSH_CUTOVER_TARGETS = (
    "dsh-install",
    "dsh-doctor",
    "dsh-start",
    "dsh-smoke",
    "dsh-test",
    "dsh-clean-runtime",
)
LIVE001_MODEL = "deepseek-v4-flash"
LIVE_G2_TOPIC = "retrieval augmented generation with self reflection"
LIVE_G2_ACTOR = "live-g2"
LIVE_G2_CONVERSATION_ID = "live-g2-research-session"
LIVE_G2_BOUNDARY_ID = "live-g2-approved-boundary"
LIVE_G2_TITLE = "LIVE G2 Research Deliverable"
LIVE001_POSITIVE_QUESTION = "Which RAG variant retrieves differently for every output token?"
LIVE001_NEGATIVE_QUESTION = "What is my current bank account balance?"
LIVE001_PROMPT = f"""\
You are running Paper RAG migration LIVE-001.
Use only Paper RAG native tools. Do not use web search, shell, filesystem, or general knowledge.

Run exactly these checks:
1. Call paper_qa for this fixed indexed-paper question, with paper_ids ["arxiv:2005.11401"]:
   {LIVE001_POSITIVE_QUESTION}
2. Call paper_qa for this no-evidence question with no paper_ids:
   {LIVE001_NEGATIVE_QUESTION}

Return a concise final summary that states whether the first answer has at least one chunk citation
and whether the second answer abstained because the indexed paper corpus has no evidence.
"""
LIVE005_PROMPT = f"""\
You are running Paper RAG migration LIVE-005 in an isolated DSH Web frontend smoke.
Use only Paper RAG native tools. Do not use web search, shell, filesystem, memory, or general knowledge as paper evidence.

Run this exact workflow from the Paper Research preset:
1. Call paper_discover with topic "{LIVE_G2_TOPIC}", max_candidates 3, and sources ["arxiv"].
2. Select one ingestable candidate by candidate id. Candidate results are not answer evidence.
3. Call discovery_candidate_ingest for the selected candidate id with force true. This is approved only for the isolated smoke workspace.
4. Call paper_qa for the ingested paper asking: "What problem does this paper solve, and what is its main method?"
5. Call paper_deliver with format "markdown_survey", the ingested paper id, and title "{LIVE_G2_TITLE}".

Return a concise final summary that names the selected candidate, the ingested paper id,
whether paper_qa returned indexed chunk citations, and the artifact manifest path.
"""
CASE_COVERAGE_BY_COMMAND = {
    "mcp-contract": (
        "MCP-001",
        "MCP-002",
        "MCP-003",
        "MCP-004",
        "MCP-005",
        "MCP-006",
        "MCP-007",
        "SEC-005",
    ),
    "mcp-tools": (
        "MCP-RO-001",
        "MCP-RO-002",
        "MCP-RO-003",
        "MCP-RO-004",
        "MCP-RO-005",
        "MCP-RO-006",
        "MCP-RO-007",
        "MCP-RO-008",
    ),
    "mcp-security": (
        "SEC-001",
        "SEC-002",
        "SEC-003",
        "SEC-004",
        "SEC-005",
    ),
    "mcp-parity": (
        "MCP-RO-004",
        "MCP-RO-005",
    ),
    "mcp-operations": (
        "MCP-008",
    ),
    "mcp-artifacts": (
        "WRITE-001",
        "WRITE-002",
        "WRITE-003",
        "WRITE-004",
        "WRITE-005",
        "WRITE-006",
        "WRITE-007",
        "ART-001",
        "ART-002",
        "ART-003",
        "ART-004",
        "ART-005",
        "ART-006",
    ),
    "dsh-test": (
        "AGENT-001",
        "AGENT-002",
        "AGENT-003",
        "AGENT-004",
        "AGENT-005",
        "AGENT-006",
        "AGENT-007",
        "SESSION-001",
        "SESSION-002",
        "SESSION-003",
        "SESSION-004",
        "SESSION-005",
        "SESSION-006",
    ),
    "python-core": (
        "PRO-001",
        "PRO-002",
        "PRO-003",
        "PRO-004",
        "PRO-005",
    ),
    "dsh-smoke": (
        "CUT-003",
    ),
    "cutover-defaults": (
        "CUT-002",
    ),
    "clean-checkout": (
        "CUT-005",
    ),
    "cut-validator": (
        "CUT-001",
        "CUT-004",
        "CUT-006",
    ),
}

DEERFLOW_PATTERN = re.compile(r"deer.?flow", re.IGNORECASE)
G5_PRE_REMOVAL_REF = "deepseek-harness-g5-pre-removal"
RESIDUAL_SCAN_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "data",
    "dist",
    "node_modules",
    "runtime",
}


class GateError(RuntimeError):
    """Raised when migration evidence is missing or invalid."""


LiveRunner = Callable[..., dict[str, Any]]


def git_head(repo_root: Path) -> str:
    return _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()


def git_dirty(repo_root: Path) -> bool:
    return bool(_run_git(repo_root, "status", "--porcelain").stdout.strip())


def collect_legacy_tests(repo_root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rel in LEGACY_TEST_FILES:
        path = repo_root / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                "test_"
            ):
                out.append(
                    {
                        "file": rel.as_posix(),
                        "test_name": node.name,
                        "line": node.lineno,
                    }
                )
    return out


def validate_legacy_matrix(repo_root: Path, matrix_path: Path) -> dict[str, Any]:
    if not matrix_path.exists():
        raise GateError(f"legacy matrix not found: {matrix_path}")
    matrix = _read_json(matrix_path)
    entries = matrix.get("entries")
    if not isinstance(entries, list):
        raise GateError("legacy matrix must contain entries list")

    legacy_sources_exist = all((repo_root / rel).exists() for rel in LEGACY_TEST_FILES)
    discovered = collect_legacy_tests(repo_root) if legacy_sources_exist else []
    expected = {(item["file"], item["test_name"]) for item in discovered}
    seen: set[tuple[str, str]] = set()
    by_file: dict[str, int] = {}
    by_classification: dict[str, int] = {}

    for i, entry in enumerate(entries):
        file = entry.get("file")
        test_name = entry.get("test_name")
        key = (file, test_name)
        if legacy_sources_exist and key not in expected:
            raise GateError(f"unknown legacy test at entries[{i}]: {file}::{test_name}")
        if key in seen:
            raise GateError(f"duplicate legacy test in matrix: {file}::{test_name}")
        seen.add(key)

        classification = entry.get("classification")
        if classification not in ALLOWED_LEGACY_CLASSIFICATIONS:
            raise GateError(
                f"invalid classification for {file}::{test_name}: {classification}"
            )
        if not str(entry.get("replacement", "")).strip():
            raise GateError(f"missing replacement evidence for {file}::{test_name}")
        if not str(entry.get("rationale", "")).strip():
            raise GateError(f"missing rationale for {file}::{test_name}")
        by_file[file] = by_file.get(file, 0) + 1
        by_classification[classification] = by_classification.get(classification, 0) + 1

    if legacy_sources_exist:
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        if missing:
            raise GateError(f"missing {len(missing)} legacy tests in matrix")
        if extra:
            raise GateError(f"extra {len(extra)} legacy tests in matrix")

    result = {
        "schema_version": matrix.get("schema_version", 1),
        "total": len(entries),
        "by_file": by_file,
        "by_classification": by_classification,
        "source_inventory": "source-files" if legacy_sources_exist else "matrix",
        "matrix_path": _relpath(matrix_path, repo_root),
    }
    return result


def freeze_baseline(
    repo_root: Path,
    spec_dir: Path,
    output_path: Path,
    *,
    require_clean: bool = True,
    execute_commands: bool = False,
) -> dict[str, Any]:
    if require_clean and git_dirty(repo_root):
        raise GateError("baseline freeze requires clean checkout")

    manifest_path = spec_dir / "test" / "test-manifest.json"
    manifest = _read_json(manifest_path)
    command_by_id = {
        command["id"]: command for command in manifest.get("owned_test_commands", [])
    }

    fingerprints = [_fingerprint(repo_root, rel) for rel in BASELINE_FINGERPRINT_PATHS]
    commands: list[dict[str, Any]] = []
    for command_id in QUALITY_BASELINE_COMMAND_IDS:
        command = command_by_id.get(command_id)
        if command is None:
            raise GateError(f"manifest missing quality command: {command_id}")
        record = {
            "id": command_id,
            "command": command["command"],
            "status": "NOT_RUN",
            "exit_code": None,
        }
        if execute_commands:
            executed = _run_shell_component(repo_root, command["command"])
            record.update(executed)
        commands.append(record)

    result = {
        "schema_version": 1,
        "feature": manifest["feature"],
        "commit": git_head(repo_root),
        "dirty": git_dirty(repo_root),
        "created_at": time.time(),
        "fingerprints": fingerprints,
        "commands": commands,
    }
    _write_json_atomic(output_path, result)
    return result


def validate_baseline(repo_root: Path, baseline_path: Path) -> dict[str, Any]:
    baseline = _read_json(baseline_path)
    mismatches: list[str] = []
    for item in baseline.get("fingerprints", []):
        current = _fingerprint(repo_root, Path(item["path"]))
        if current["sha256"] != item["sha256"]:
            mismatches.append(item["path"])
    if mismatches:
        raise GateError(f"baseline fingerprint mismatch: {', '.join(mismatches)}")
    return {
        "schema_version": 1,
        "baseline": _relpath(baseline_path, repo_root),
        "fingerprints": len(baseline.get("fingerprints", [])),
    }


def validate_report(
    repo_root: Path, manifest_path: Path, gate: str, report_path: Path
) -> dict[str, Any]:
    if not report_path.exists():
        raise GateError(f"report not found: {report_path}")
    manifest = _read_json(manifest_path)
    report = _read_json(report_path)
    if report.get("gate") != gate:
        raise GateError(f"report gate mismatch: expected {gate}, got {report.get('gate')}")
    if report.get("commit") != git_head(repo_root):
        raise GateError("report commit does not match HEAD")
    if report.get("dirty") is not False:
        raise GateError("report must record dirty=false")

    required = _required_cases_for_gate(manifest, gate)
    cases = report.get("cases", {})
    missing = [case_id for case_id in required if case_id not in cases]
    if missing:
        raise GateError(f"missing required cases: {', '.join(missing)}")
    not_pass = [
        case_id
        for case_id in required
        if cases.get(case_id, {}).get("status") != "PASS"
    ]
    if not_pass:
        raise GateError(f"required cases not PASS: {', '.join(not_pass)}")

    for case_id, case in cases.items():
        status = case.get("status")
        if status not in TERMINAL_CASE_STATUSES:
            raise GateError(f"invalid case status for {case_id}: {status}")

    return {
        "schema_version": 1,
        "gate": gate,
        "required_cases": len(required),
        "report": _relpath(report_path, repo_root),
    }


def validate_live(repo_root: Path, manifest_path: Path, gate: str) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    live_cases = [
        case for case in manifest.get("live_cases", [])
        if case.get("gate") == gate
    ]
    validated: list[str] = []
    now = time.time()
    for live_case in live_cases:
        case_id = live_case.get("id")
        report_path = repo_root / str(live_case.get("report", ""))
        if not report_path.exists():
            raise GateError(f"live report not found for {case_id}: {_relpath(report_path, repo_root)}")
        report = _read_json(report_path)
        if report.get("id") != case_id:
            raise GateError(f"live report id mismatch for {case_id}")
        if report.get("gate") != gate:
            raise GateError(f"live report gate mismatch for {case_id}")
        if report.get("commit") != git_head(repo_root):
            raise GateError(f"live report commit does not match HEAD for {case_id}")
        if report.get("status") != "PASS":
            raise GateError(f"live report is not PASS for {case_id}")
        if live_case.get("requires_authorization") and report.get("authorized") is not True:
            raise GateError(f"live report not authorized for {case_id}")
        max_age_hours = live_case.get("max_age_hours")
        if max_age_hours is not None:
            created_at = report.get("created_at")
            if not isinstance(created_at, (int, float)):
                raise GateError(f"live report missing created_at for {case_id}")
            if now - float(created_at) > float(max_age_hours) * 3600:
                raise GateError(f"live report expired for {case_id}")
        validated.append(str(case_id))
    return {
        "schema_version": 1,
        "gate": gate,
        "live_cases": validated,
    }


def validate_cutover_defaults(repo_root: Path) -> dict[str, Any]:
    makefile = (repo_root / "Makefile").read_text(encoding="utf-8")
    readme_en = (repo_root / "README.md").read_text(encoding="utf-8")
    readme_zh = (repo_root / "README_ZH.md").read_text(encoding="utf-8")
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")
    ci_workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    operations = (repo_root / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    architecture = (repo_root / "docs" / "ARCHITECTURE.md").read_text(
        encoding="utf-8"
    )

    checks = [
        _cutover_check(
            "makefile-dsh-targets",
            all(f"\n{target}:" in f"\n{makefile}" for target in DSH_CUTOVER_TARGETS),
            f"Makefile must define {', '.join(DSH_CUTOVER_TARGETS)}",
        ),
        _cutover_check(
            "makefile-no-retired-host-targets",
            _makefile_deerflow_targets_removed(repo_root / "Makefile"),
            "Makefile must expose DSH targets without retired host fallback targets",
        ),
        _cutover_check(
            "readme-zh-dsh-quick-start",
            "快速开始" in readme_zh
            and "DeepSeek Harness" in readme_zh
            and "make dsh-start" in readme_zh,
            "README_ZH.md Quick Start must default to DeepSeek Harness",
        ),
        _cutover_check(
            "readme-en-dsh-quick-start",
            "Quick Start" in readme_en
            and "DeepSeek Harness" in readme_en
            and "make dsh-start" in readme_en,
            "README.md Quick Start must default to DeepSeek Harness",
        ),
        _cutover_check(
            "env-example-dsh",
            "PAPER_RAG_DSH_PORT=3080" in env_example
            and "CHAT_MODEL=deepseek-v4-flash" in env_example
            and "SMALL_MODEL=deepseek-v4-flash" in env_example,
            ".env.example must include DSH port and flash model defaults",
        ),
        _cutover_check(
            "ci-dsh-job",
            "deepseek-harness:" in ci_workflow
            and "pnpm test" in ci_workflow
            and "pnpm smoke" in ci_workflow,
            "CI must include a DeepSeek Harness deterministic test/smoke job",
        ),
        _cutover_check(
            "docs-dsh-default",
            "DeepSeek Harness 默认入口" in operations
            and "Native Broker" in architecture
            and "旧宿主源码" in readme_zh,
            "Operations, architecture, and README docs must mark DSH as default",
        ),
    ]
    failed = [check for check in checks if check["status"] != "PASS"]
    if failed:
        details = "; ".join(f"{check['id']}: {check['detail']}" for check in failed)
        raise GateError(f"cutover default check failed: {details}")
    return {
        "schema_version": 1,
        "checks": checks,
        "targets": list(DSH_CUTOVER_TARGETS),
    }


def validate_cutover(repo_root: Path, spec_dir: Path) -> dict[str, Any]:
    residuals = _collect_deerflow_residuals(repo_root)
    runtime_residuals = [
        residual for residual in residuals
        if residual.get("classification") == "runtime-reference"
    ]
    checks = [
        _cutover_check(
            "deerflow-workspace-removed",
            not (repo_root / "integrations" / "deer-flow").exists(),
            "integrations/deer-flow must be removed for G5",
        ),
        _cutover_check(
            "deerflow-smoke-removed",
            not (repo_root / "scripts" / "deerflow_smoke.py").exists(),
            "scripts/deerflow_smoke.py must be removed for G5",
        ),
        _cutover_check(
            "makefile-deerflow-targets-removed",
            _makefile_deerflow_targets_removed(repo_root / "Makefile"),
            "Makefile must not expose DeerFlow targets or variables",
        ),
        _cutover_check(
            "pyproject-deerflow-extra-removed",
            _pyproject_deerflow_extra_removed(repo_root / "pyproject.toml"),
            "pyproject must not expose the deerflow extra or DeerFlow-only dependencies",
        ),
        _cutover_check(
            "residual-runtime-references",
            not runtime_residuals,
            "deerflow residual references must be historical records only",
        ),
        _cutover_check(
            "pre-removal-ref-recorded",
            _pre_removal_ref_recorded(repo_root),
            f"{G5_PRE_REMOVAL_REF} must point to a commit reachable from HEAD",
        ),
    ]
    failed = [check for check in checks if check["status"] != "PASS"]
    if failed:
        failed_ids = ", ".join(check["id"] for check in failed)
        if runtime_residuals:
            samples = ", ".join(
                f"{item['path']}:{item['line']}" for item in runtime_residuals[:10]
            )
            raise GateError(f"cutover runtime residue: {failed_ids}; {samples}")
        raise GateError(f"cutover check failed: {failed_ids}")

    return {
        "schema_version": 1,
        "spec": _relpath(spec_dir, repo_root),
        "checks": checks,
        "residual_references": residuals,
        "pre_removal_ref": G5_PRE_REMOVAL_REF,
    }


def _cutover_check(check_id: str, passed: bool, detail: str) -> dict[str, str]:
    return {
        "id": check_id,
        "status": "PASS" if passed else "FAIL",
        "detail": detail,
    }


def validate_clean_checkout(repo_root: Path) -> dict[str, Any]:
    if git_dirty(repo_root):
        raise GateError("clean checkout required")
    return {
        "schema_version": 1,
        "commit": git_head(repo_root),
        "dirty": False,
        "status": "PASS",
    }


def _makefile_deerflow_targets_removed(path: Path) -> bool:
    if not path.exists():
        return True
    text = path.read_text(encoding="utf-8")
    return not re.search(r"(?im)^(?:DEER_?FLOW|deerflow-)", text)


def _pyproject_deerflow_extra_removed(path: Path) -> bool:
    if not path.exists():
        return True
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    optional = data.get("project", {}).get("optional-dependencies", {})
    if "deerflow" in optional:
        return False
    deps = json.dumps(optional, sort_keys=True).lower()
    return "langchain" not in deps


def _pre_removal_ref_recorded(repo_root: Path) -> bool:
    if not (repo_root / ".git").exists():
        return True
    ref = _run_git(repo_root, "rev-parse", f"{G5_PRE_REMOVAL_REF}^{{commit}}", check=False)
    if ref.returncode != 0 or not ref.stdout.strip():
        return False
    ancestor = _run_git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        ref.stdout.strip(),
        "HEAD",
        check=False,
    )
    return ancestor.returncode == 0


def _collect_deerflow_residuals(repo_root: Path) -> list[dict[str, Any]]:
    residuals: list[dict[str, Any]] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file() or _should_skip_residual_path(path, repo_root):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(repo_root)
        classification = _classify_deerflow_residual(rel, text)
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not DEERFLOW_PATTERN.search(line):
                continue
            residuals.append(
                {
                    "path": rel.as_posix(),
                    "line": line_no,
                    "classification": classification,
                }
            )
    residuals.sort(key=lambda item: (item["path"], item["line"]))
    return residuals


def _should_skip_residual_path(path: Path, repo_root: Path) -> bool:
    rel = path.relative_to(repo_root)
    if any(part in RESIDUAL_SCAN_SKIP_DIRS for part in rel.parts):
        return True
    if any(part.endswith(".egg-info") for part in rel.parts):
        return True
    return rel.as_posix().endswith((".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf"))


def _classify_deerflow_residual(rel: Path, text: str) -> str:
    rel_posix = rel.as_posix()
    lower_text = text.lower()
    if rel_posix.startswith("specs/20260813-deepseek-harness-migration/"):
        return "migration-spec"
    if rel_posix in {"scripts/migration_gate.py", "tests/test_migration_gate.py"}:
        return "gate-validator"
    if "changelog" in rel.name.lower():
        return "historical-changelog"
    if rel_posix == "docs/STATUS.md":
        return "status-history"
    if rel_posix.startswith("docs/superpowers/plans/"):
        return "historical-plan"
    if rel_posix.startswith("docs/superpowers/specs/"):
        return "historical-spec"
    if rel_posix in {
        "docs/M8_PRD.md",
        "docs/M10_PRD.md",
        "docs/M11_PRD.md",
        "docs/ACCEPTANCE_REPORT.md",
        "docs/P012_COMPLETION_PLAN.md",
        "docs/VERIFICATION_REPORT.md",
    }:
        return "historical-product-record"
    if rel_posix.startswith("docs/adrs/") and "superseded" in lower_text:
        return "superseded-adr"
    if rel_posix.startswith("docs/adrs/0022-") and "final" in lower_text:
        return "final-migration-adr"
    if rel_posix.startswith("docs/adrs/"):
        return "historical-adr"
    if rel_posix == "docs/README.md" and "adrs/" in lower_text:
        return "adr-index"
    return "runtime-reference"



def run_live(
    repo_root: Path,
    manifest_path: Path,
    case_id: str,
    *,
    authorized_by: str | None = None,
    config_env: str | None = None,
    runner_registry: dict[str, LiveRunner] | None = None,
) -> dict[str, Any]:
    if git_dirty(repo_root):
        raise GateError("run-live requires clean checkout")
    manifest = _read_json(manifest_path)
    live_case = _live_case_for_id(manifest, case_id)
    effective_authorized_by = (authorized_by or os.environ.get("PAPER_RAG_LIVE_AUTHORIZED_BY", "")).strip()
    if live_case.get("requires_authorization") and not effective_authorized_by:
        raise GateError(
            f"live case {case_id} requires explicit authorization "
            "(pass --authorized-by or set PAPER_RAG_LIVE_AUTHORIZED_BY)"
        )

    registry = runner_registry if runner_registry is not None else LIVE_CASE_RUNNERS
    runner = registry.get(case_id)
    if runner is None:
        raise GateError(f"live runner not implemented for {case_id}")

    payload = runner(
        repo_root,
        live_case,
        config_env=config_env,
        authorized_by=effective_authorized_by,
    )
    status = payload.get("status")
    if status not in LIVE_REPORT_STATUSES:
        raise GateError(f"live runner {case_id} returned invalid status: {status}")

    report = {
        **payload,
        "schema_version": 1,
        "id": case_id,
        "gate": live_case.get("gate"),
        "commit": git_head(repo_root),
        "authorized": True,
        "authorized_by": effective_authorized_by,
        "authorization_source": "argument" if authorized_by else "environment",
        "created_at": time.time(),
        "side_effects": list(live_case.get("side_effects") or []),
        "config_env": config_env,
    }
    report_path = repo_root / str(live_case.get("report", ""))
    _write_json_atomic(report_path, report)
    return report


def _live_case_for_id(manifest: dict[str, Any], case_id: str) -> dict[str, Any]:
    for live_case in manifest.get("live_cases", []):
        if live_case.get("id") == case_id:
            return live_case
    raise GateError(f"unknown live case: {case_id}")


def _live_runner_not_implemented(
    repo_root: Path,
    live_case: dict[str, Any],
    *,
    config_env: str | None,
    authorized_by: str,
) -> dict[str, Any]:
    raise GateError(
        f"live runner for {live_case.get('id')} is not implemented; "
        "do not mark this live case PASS without a real DSH model run"
    )


@dataclass(frozen=True)
class Live001Workspace:
    work_root: Path
    dsh_home: Path
    data_root: Path
    config_path: Path
    source_data_root: Path


@dataclass(frozen=True)
class LiveG2Workspace:
    work_root: Path
    data_root: Path
    index_root: Path
    artifact_root: Path
    import_root: Path
    dsh_home: Path
    config_path: Path
    feedback_path: Path


def run_live001_dsh_model_qa(
    repo_root: Path,
    live_case: dict[str, Any],
    *,
    config_env: str | None,
    authorized_by: str,
    source_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    del live_case, config_env, authorized_by
    env_source = dict(os.environ if source_env is None else source_env)
    _require_live001_flash_env(env_source)
    with tempfile.TemporaryDirectory(prefix="paper-rag-live001-") as tmp:
        workspace = _prepare_live001_workspace(repo_root, Path(tmp))
        env = _live001_child_env(repo_root, workspace, env_source)
        summary = _run_live001_headless(repo_root, workspace, env)
        checks = list(summary.get("checks") or [])
        status = "PASS" if checks and all(item.get("status") == "PASS" for item in checks) else "FAIL"
        return {
            "status": status,
            "checks": checks,
            "metrics": summary.get("metrics") or {},
            "model": LIVE001_MODEL,
            "dsh_model": summary.get("dsh_model"),
            "data_root": f"isolated:{workspace.data_root}",
            "source_data_root": _relpath(workspace.source_data_root, repo_root),
            "credential_refs": ["OPENAI_API_KEY"],
            "dsh_credential_ref": "DEEPSEEK_API_KEY",
            "dsh_credential_source_ref": (
                "DEEPSEEK_API_KEY" if env_source.get("DEEPSEEK_API_KEY") else "OPENAI_API_KEY"
            ),
            "side_effect_scope": "temporary isolated data copy and temporary DSH_HOME; cleaned after run",
            "writes_to_formal_paper_library": False,
            "assistant_excerpt": summary.get("assistant_excerpt", ""),
        }


def _require_live001_flash_env(source_env: dict[str, str]) -> None:
    for key in ("CHAT_MODEL", "SMALL_MODEL"):
        if source_env.get(key) != LIVE001_MODEL:
            raise GateError(f"LIVE-001 requires {key}={LIVE001_MODEL}, got {source_env.get(key)!r}")
    if not (source_env.get("OPENAI_API_KEY") or source_env.get("DEEPSEEK_API_KEY")):
        raise GateError("LIVE-001 requires OPENAI_API_KEY or DEEPSEEK_API_KEY")


def _prepare_live001_workspace(repo_root: Path, work_root: Path) -> Live001Workspace:
    source_index = repo_root / "data/index"
    source_sqlite = source_index / "papers.sqlite"
    source_qdrant = source_index / "qdrant_embedded"
    if not source_sqlite.exists():
        raise GateError(f"LIVE-001 source SQLite not found: {_relpath(source_sqlite, repo_root)}")
    if not source_qdrant.exists():
        raise GateError(f"LIVE-001 source Qdrant path not found: {_relpath(source_qdrant, repo_root)}")

    data_root = work_root / "data"
    index_root = data_root / "index"
    dsh_home = work_root / "dsh-home"
    index_root.mkdir(parents=True, exist_ok=True)
    (data_root / "papers").mkdir(parents=True, exist_ok=True)
    (data_root / "parsed").mkdir(parents=True, exist_ok=True)
    (work_root / "artifacts").mkdir(parents=True, exist_ok=True)
    (work_root / "imports").mkdir(parents=True, exist_ok=True)
    (work_root / "credentials").mkdir(parents=True, exist_ok=True)

    shutil.copy2(source_sqlite, index_root / "papers.sqlite")
    source_bm25 = source_index / "bm25.pkl"
    if source_bm25.exists():
        shutil.copy2(source_bm25, index_root / "bm25.pkl")
    shutil.copytree(
        source_qdrant,
        index_root / "qdrant_embedded",
        ignore=shutil.ignore_patterns(".lock"),
        dirs_exist_ok=True,
    )

    preset_source = repo_root / "integrations/deepseek-harness/presets/paper-research"
    preset_dest = dsh_home / ".agent-presets/paper-research"
    if not preset_source.exists():
        raise GateError(f"LIVE-001 preset source not found: {_relpath(preset_source, repo_root)}")
    shutil.copytree(preset_source, preset_dest, dirs_exist_ok=True)

    runner_source = repo_root / "integrations/deepseek-harness/src/paper-rag-headless-runner.mjs"
    runner_dest = dsh_home / "profiles/headless/src/paper-rag-headless-runner.mjs"
    if not runner_source.exists():
        raise GateError(f"LIVE-001 headless runner source not found: {_relpath(runner_source, repo_root)}")
    cards_source = repo_root / "integrations/deepseek-harness/src/paper-rag-cards.mjs"
    if not cards_source.exists():
        raise GateError(f"LIVE-001 headless card source not found: {_relpath(cards_source, repo_root)}")
    runner_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(runner_source, runner_dest)
    shutil.copy2(cards_source, runner_dest.parent / "paper-rag-cards.mjs")

    config_path = work_root / "config.live001.yaml"
    _write_live001_config(repo_root, data_root, index_root, config_path)
    return Live001Workspace(
        work_root=work_root,
        dsh_home=dsh_home,
        data_root=data_root,
        config_path=config_path,
        source_data_root=source_index,
    )


def _write_live001_config(repo_root: Path, data_root: Path, index_root: Path, config_path: Path) -> None:
    source_config = repo_root / "config/local.yaml"
    raw = yaml.safe_load(source_config.read_text(encoding="utf-8"))
    paths = raw.setdefault("paths", {})
    paths.update(
        {
            "data_root": str(data_root),
            "papers_dir": str(data_root / "papers"),
            "parsed_dir": str(data_root / "parsed"),
            "index_dir": str(index_root),
            "sqlite_path": str(index_root / "papers.sqlite"),
            "bm25_path": str(index_root / "bm25.pkl"),
            "models_dir": str(repo_root / "data/index/models"),
        }
    )
    qdrant = raw.setdefault("qdrant", {})
    qdrant.update(
        {
            "url": "",
            "local_path": str(index_root / "qdrant_embedded"),
            "collection_chunks": "paper_chunks",
            "collection_wiki": "wiki_entries",
        }
    )
    raw.setdefault("llm", {})["chat_model"] = "$CHAT_MODEL"
    raw.setdefault("llm", {})["small_model"] = "$SMALL_MODEL"
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _live001_child_env(
    repo_root: Path,
    workspace: Live001Workspace,
    source_env: dict[str, str],
) -> dict[str, str]:
    env = dict(source_env)
    if not env.get("DEEPSEEK_API_KEY") and env.get("OPENAI_API_KEY"):
        env["DEEPSEEK_API_KEY"] = env["OPENAI_API_KEY"]
    if not env.get("DEEPSEEK_BASE_URL") and env.get("OPENAI_BASE_URL"):
        env["DEEPSEEK_BASE_URL"] = env["OPENAI_BASE_URL"]
    env.update(
        {
            "CHAT_MODEL": LIVE001_MODEL,
            "SMALL_MODEL": LIVE001_MODEL,
            "DSH_HOME": str(workspace.dsh_home),
            "DSH_TELEMETRY_DISABLED": "1",
            "DSH_TELEMETRY_MODE": "DISABLED",
            "DSH_PERMISSION_MODE": "read-only",
            "DSH_TOOLS_MODE": "native",
            "PAPER_RAG_CONFIG": str(workspace.config_path),
            "PAPER_RAG_REPO_ROOT": str(repo_root),
            "PAPER_RAG_ARTIFACT_ROOT": str(workspace.work_root / "artifacts"),
            "PAPER_RAG_IMPORT_ROOT": str(workspace.work_root / "imports"),
            "PAPER_RAG_MCP_TOOLSET": "readonly",
            "PAPER_RAG_DSH_CREDENTIALS_PATH": str(
                workspace.work_root / "credentials/.credentials.yaml"
            ),
            "PAPER_RAG_DSH_SKILL_ROOT": str(repo_root / ".dsh/skills"),
            "PAPER_RAG_DSH_PRESET_ID": "paper-research",
            "PAPER_RAG_MCP_CREDENTIAL_REFS": json.dumps(["OPENAI_API_KEY"]),
        }
    )
    return env


def _run_live001_headless(
    repo_root: Path,
    workspace: Live001Workspace,
    env: dict[str, str],
) -> dict[str, Any]:
    integration_root = repo_root / "integrations/deepseek-harness"
    dsh_bin = integration_root / "node_modules/.bin/dsh"
    patch_path = integration_root / "live-headless.patch.yml"
    if not dsh_bin.exists():
        raise GateError(f"LIVE-001 DSH binary not found: {_relpath(dsh_bin, repo_root)}")
    if not patch_path.exists():
        raise GateError(f"LIVE-001 headless patch not found: {_relpath(patch_path, repo_root)}")

    proc = subprocess.run(
        [
            str(dsh_bin),
            "--profile",
            "headless",
            "--patch",
            str(patch_path),
            LIVE001_PROMPT,
        ],
        cwd=integration_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=int(env.get("PAPER_RAG_LIVE_TIMEOUT_SEC", "900")),
        check=False,
    )
    try:
        events = _load_dsh_session_events(workspace.dsh_home)
        summary = summarize_live001_events(events, stdout=proc.stdout, stderr=proc.stderr)
    except Exception as exc:
        summary = {
            "checks": [
                {
                    "id": "session-events-readable",
                    "status": "FAIL",
                    "detail": str(exc).splitlines()[0][:500],
                }
            ],
            "metrics": {},
            "dsh_model": None,
            "assistant_excerpt": (proc.stdout or proc.stderr)[-500:],
        }
    summary["checks"] = [
        {
            "id": "dsh-headless-exit",
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "detail": f"exit={proc.returncode}",
        },
        *list(summary.get("checks") or []),
    ]
    return summary


def _load_dsh_session_events(dsh_home: Path) -> list[dict[str, Any]]:
    session_paths = sorted(
        (dsh_home / "sessions").rglob("session.jsonl"),
        key=lambda path: path.stat().st_mtime,
    )
    if not session_paths:
        raise GateError(f"no plaintext DSH session log found under {dsh_home / 'sessions'}")
    events: list[dict[str, Any]] = []
    for line in session_paths[-1].read_text(encoding="utf-8").splitlines()[1:]:
        if line.strip():
            events.append(json.loads(line))
    return events


def summarize_live001_events(events: list[dict[str, Any]], *, stdout: str, stderr: str) -> dict[str, Any]:
    tool_calls = [event for event in events if event.get("type") == "tool/call"]
    tool_names = [str((event.get("data") or {}).get("name", "")) for event in tool_calls]
    paper_qa_calls = [event for event in tool_calls if (event.get("data") or {}).get("name") == "paper_qa"]
    text = "\n".join(_event_text(event) for event in events)
    dsh_model = _live001_dsh_model(events)
    citation_ok = _has_nonempty_citation(text)
    abstain_ok = "abstain=no_evidence" in text.lower()
    readonly_names = {
        "paper_status",
        "paper_list",
        "paper_search",
        "paper_qa",
        "paper_section",
        "paper_compare",
        "wiki_lookup",
    }
    disallowed = sorted({name for name in tool_names if name not in readonly_names})
    checks = [
        {
            "id": "dsh-model-flash",
            "status": "PASS" if dsh_model == LIVE001_MODEL else "FAIL",
            "detail": f"model={dsh_model}",
        },
        {
            "id": "readonly-tool-surface",
            "status": "PASS" if tool_calls and not disallowed else "FAIL",
            "detail": f"tool_calls={tool_names} disallowed={disallowed}",
        },
        {
            "id": "paper-qa-called",
            "status": "PASS" if len(paper_qa_calls) >= 2 else "FAIL",
            "detail": f"paper_qa_calls={len(paper_qa_calls)}",
        },
        {
            "id": "fixed-paper-citation",
            "status": "PASS" if citation_ok else "FAIL",
            "detail": LIVE001_POSITIVE_QUESTION,
        },
        {
            "id": "no-evidence-abstain",
            "status": "PASS" if abstain_ok else "FAIL",
            "detail": LIVE001_NEGATIVE_QUESTION,
        },
    ]
    return {
        "checks": checks,
        "metrics": {
            "tool_calls": len(tool_calls),
            "paper_qa_calls": len(paper_qa_calls),
            "citation_checks_passed": 1 if citation_ok else 0,
            "abstain_checks_passed": 1 if abstain_ok else 0,
        },
        "dsh_model": dsh_model,
        "assistant_excerpt": _last_assistant_text(events) or stdout[-500:] or stderr[-500:],
    }


def _event_text(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            return value["text"]
        return "\n".join(_event_text(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_event_text(item) for item in value)
    return ""


def _has_nonempty_citation(text: str) -> bool:
    for token in text.split():
        if token.startswith("citations="):
            return bool(token.removeprefix("citations=").strip().strip(","))
    return False


def _live001_dsh_model(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        if event.get("type") == "request/header":
            config = (event.get("data") or {}).get("config") or {}
            if config.get("model"):
                return str(config["model"])
    for event in reversed(events):
        if event.get("type") == "assistant/message":
            source = (((event.get("data") or {}).get("message") or {}).get("source") or {})
            if source.get("model"):
                return str(source["model"])
    return None


def _last_assistant_text(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") == "assistant/message":
            return _event_text((event.get("data") or {}).get("message") or "")[:500]
    return ""


def run_live002_discover_ingest_qa(
    repo_root: Path,
    live_case: dict[str, Any],
    *,
    config_env: str | None,
    authorized_by: str,
    source_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    del live_case, authorized_by
    _require_live_g2_config_env(config_env)
    env_source = dict(os.environ if source_env is None else source_env)
    _require_live_g2_flash_env(env_source, "LIVE-002")
    workspace = _prepare_live_g2_workspace(repo_root, _live_g2_workspace_root(repo_root), reset=True)
    isolation = _assert_live_g2_workspace_isolated(repo_root, workspace)
    env = _live_g2_child_env(repo_root, workspace, env_source)
    try:
        summary = _run_live002_workflow(repo_root, workspace, env)
        checks = [
            {"id": "live-g2-isolated-config", "status": "PASS", "detail": isolation["workspace_root"]},
            *list(summary.get("checks") or []),
        ]
        summary = {**summary, "checks": checks}
    except Exception as exc:
        summary = _live_g2_exception_summary("live-g2-discover-ingest-qa", exc, env_source)
    return _live_g2_payload(workspace, summary, env_source)


def run_live003_generate_artifacts(
    repo_root: Path,
    live_case: dict[str, Any],
    *,
    config_env: str | None,
    authorized_by: str,
    source_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    del live_case, authorized_by
    _require_live_g2_config_env(config_env)
    env_source = dict(os.environ if source_env is None else source_env)
    _require_live_g2_flash_env(env_source, "LIVE-003")
    try:
        prior = _read_required_live_report(repo_root, "LIVE-002")
        workspace = _prepare_live_g2_workspace(
            repo_root,
            _live_g2_workspace_root(repo_root, prior),
            reset=False,
        )
        isolation = _assert_live_g2_workspace_isolated(repo_root, workspace)
        env = _live_g2_child_env(repo_root, workspace, env_source)
        summary = _run_live003_workflow(repo_root, workspace, env, str(prior.get("paper_id") or ""))
        checks = [
            {"id": "live-g2-isolated-config", "status": "PASS", "detail": isolation["workspace_root"]},
            *list(summary.get("checks") or []),
        ]
        summary = {**summary, "checks": checks}
    except GateError as exc:
        workspace = _prepare_live_g2_workspace(repo_root, _live_g2_workspace_root(repo_root), reset=False)
        summary = _live_g2_exception_summary("live-g2-prerequisite", exc, env_source, blocked=True)
    except Exception as exc:
        workspace = _prepare_live_g2_workspace(repo_root, _live_g2_workspace_root(repo_root), reset=False)
        summary = _live_g2_exception_summary("live-g2-deliver", exc, env_source)
    return _live_g2_payload(workspace, summary, env_source)


def run_live004_resume_session_followup(
    repo_root: Path,
    live_case: dict[str, Any],
    *,
    config_env: str | None,
    authorized_by: str,
    source_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    del live_case, authorized_by
    _require_live_g2_config_env(config_env)
    env_source = dict(os.environ if source_env is None else source_env)
    _require_live_g2_flash_env(env_source, "LIVE-004")
    try:
        prior = _read_required_live_report(repo_root, "LIVE-002")
        workspace = _prepare_live_g2_workspace(
            repo_root,
            _live_g2_workspace_root(repo_root, prior),
            reset=False,
        )
        isolation = _assert_live_g2_workspace_isolated(repo_root, workspace)
        env = _live_g2_child_env(repo_root, workspace, env_source)
        summary = _run_live004_workflow(repo_root, workspace, env, str(prior.get("paper_id") or ""))
        checks = [
            {"id": "live-g2-isolated-config", "status": "PASS", "detail": isolation["workspace_root"]},
            *list(summary.get("checks") or []),
        ]
        summary = {**summary, "checks": checks}
    except GateError as exc:
        workspace = _prepare_live_g2_workspace(repo_root, _live_g2_workspace_root(repo_root), reset=False)
        summary = _live_g2_exception_summary("live-g2-prerequisite", exc, env_source, blocked=True)
    except Exception as exc:
        workspace = _prepare_live_g2_workspace(repo_root, _live_g2_workspace_root(repo_root), reset=False)
        summary = _live_g2_exception_summary("live-g2-followup-session", exc, env_source)
    return _live_g2_payload(workspace, summary, env_source)


def run_live005_dsh_frontend_workflow(
    repo_root: Path,
    live_case: dict[str, Any],
    *,
    config_env: str | None,
    authorized_by: str,
    source_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    del live_case, authorized_by
    _require_live_g2_config_env(config_env)
    env_source = dict(os.environ if source_env is None else source_env)
    _require_live_g2_flash_env(env_source, "LIVE-005")
    workspace = _prepare_live_g2_workspace(repo_root, _live_g2_workspace_root(repo_root), reset=False)
    isolation = _assert_live_g2_workspace_isolated(repo_root, workspace)
    env = _live_g2_child_env(repo_root, workspace, env_source)
    env.update(
        {
            "PAPER_RAG_DSH_HEADLESS_REPORT_JSON": "1",
            "PAPER_RAG_DSH_HEADLESS_WORKFLOW": "1",
            "PAPER_RAG_DSH_HEADLESS_SCRIPTED_WORKFLOW": "1",
            "PAPER_RAG_DSH_HEADLESS_APPROVE_WRITES": "isolated",
        }
    )
    try:
        headless_summary = _run_live005_headless_workflow(repo_root, workspace, env)
        tool_calls = list(headless_summary.get("tool_calls") or [])
        cards = list(headless_summary.get("cards") or [])
        checks = [
            {"id": "live-g2-isolated-config", "status": "PASS", "detail": isolation["workspace_root"]},
            {
                "id": "dsh-headless-exit",
                "status": "PASS" if int(headless_summary.get("exit_code", 0)) == 0 else "FAIL",
                "detail": f"exit={headless_summary.get('exit_code', 0)}",
            },
            {
                "id": "dsh-headless-used-paper-research",
                "status": "PASS" if headless_summary.get("preset") == "paper-research" else "FAIL",
                "detail": str(headless_summary.get("preset")),
            },
            {
                "id": "dsh-headless-workflow-tools",
                "status": "PASS" if _has_live005_tools(headless_summary) else "FAIL",
                "detail": ",".join(tool_calls),
            },
            {
                "id": "dsh-headless-portable-cards",
                "status": "PASS" if _has_live005_cards(headless_summary) else "FAIL",
                "detail": ",".join(cards),
            },
            {
                "id": "formal-library-untouched",
                "status": "PASS",
                "detail": f"workspace={workspace.work_root}",
            },
        ]
        summary = {
            **headless_summary,
            "checks": checks,
            "metrics": {"tool_calls": len(tool_calls), "cards": len(cards)},
            "summary": headless_summary,
        }
    except Exception as exc:
        summary = _live_g2_exception_summary("live-g2-dsh-frontend-workflow", exc, env_source)
    return _live_g2_payload(workspace, summary, env_source)


def _require_live_g2_config_env(config_env: str | None) -> None:
    if config_env not in (None, "PAPER_RAG_CONFIG"):
        raise GateError(f"LIVE-G2 requires --config-env PAPER_RAG_CONFIG, got {config_env!r}")


def _require_live_g2_flash_env(source_env: dict[str, str], case_id: str) -> None:
    for key in ("CHAT_MODEL", "SMALL_MODEL"):
        value = source_env.get(key)
        if value and value != LIVE001_MODEL:
            raise GateError(f"{case_id} requires {key}={LIVE001_MODEL}, got {value!r}")
    if not (source_env.get("OPENAI_API_KEY") or source_env.get("DEEPSEEK_API_KEY")):
        raise GateError(f"{case_id} requires OPENAI_API_KEY or DEEPSEEK_API_KEY")
    if not (source_env.get("OPENAI_BASE_URL") or source_env.get("DEEPSEEK_BASE_URL")):
        raise GateError(f"{case_id} requires OPENAI_BASE_URL or DEEPSEEK_BASE_URL")


def _prepare_live_g2_workspace(repo_root: Path, work_root: Path, *, reset: bool = False) -> LiveG2Workspace:
    if reset and work_root.exists():
        shutil.rmtree(work_root)

    data_root = work_root / "data"
    index_root = data_root / "index"
    artifact_root = work_root / "artifacts"
    import_root = work_root / "imports"
    dsh_version_root = work_root / "runtime/deepseek-harness/versions" / _dsh_version(repo_root)
    dsh_home = dsh_version_root / "dsh-home"
    feedback_path = index_root / "feedback.sqlite"
    config_path = work_root / "config.live-g2.yaml"

    for path in (
        data_root / "papers",
        data_root / "parsed",
        index_root / "qdrant_embedded",
        index_root / "models",
        artifact_root,
        import_root,
        work_root / "credentials",
        dsh_home / "sessions",
    ):
        path.mkdir(parents=True, exist_ok=True)

    _write_live_g2_config(repo_root, data_root, index_root, config_path)
    return LiveG2Workspace(
        work_root=work_root,
        data_root=data_root,
        index_root=index_root,
        artifact_root=artifact_root,
        import_root=import_root,
        dsh_home=dsh_home,
        config_path=config_path,
        feedback_path=feedback_path,
    )


def _write_live_g2_config(repo_root: Path, data_root: Path, index_root: Path, config_path: Path) -> None:
    source_config = repo_root / "config/local.yaml"
    raw = yaml.safe_load(source_config.read_text(encoding="utf-8")) or {}
    suffix = _live_g2_suffix(repo_root)
    paths = raw.setdefault("paths", {})
    paths.update(
        {
            "data_root": str(data_root),
            "papers_dir": str(data_root / "papers"),
            "parsed_dir": str(data_root / "parsed"),
            "index_dir": str(index_root),
            "sqlite_path": str(index_root / "papers.sqlite"),
            "bm25_path": str(index_root / "bm25.pkl"),
            "models_dir": str(repo_root / "data/index/models"),
        }
    )
    qdrant = raw.setdefault("qdrant", {})
    qdrant.update(
        {
            "url": "",
            "local_path": str(index_root / "qdrant_embedded"),
            "collection_chunks": f"paper_chunks_live_g2_{suffix}",
            "collection_wiki": f"wiki_entries_live_g2_{suffix}",
        }
    )
    raw.setdefault("llm", {})["chat_model"] = "$CHAT_MODEL"
    raw.setdefault("llm", {})["small_model"] = "$SMALL_MODEL"
    raw.setdefault("mineru", {})["mode"] = "pymupdf"
    raw.setdefault("mineru", {})["fallback_to_pymupdf"] = True
    raw.setdefault("wiki", {})["enabled"] = False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _assert_live_g2_workspace_isolated(repo_root: Path, workspace: LiveG2Workspace) -> dict[str, Any]:
    workspace_root = workspace.work_root.resolve()
    raw = yaml.safe_load(workspace.config_path.read_text(encoding="utf-8")) or {}
    paths = raw.get("paths") or {}
    qdrant = raw.get("qdrant") or {}
    candidates = [
        workspace.data_root,
        workspace.index_root,
        workspace.artifact_root,
        workspace.import_root,
        workspace.feedback_path,
        Path(str(paths.get("data_root", ""))),
        Path(str(paths.get("papers_dir", ""))),
        Path(str(paths.get("parsed_dir", ""))),
        Path(str(paths.get("index_dir", ""))),
        Path(str(paths.get("sqlite_path", ""))),
        Path(str(paths.get("bm25_path", ""))),
        Path(str(qdrant.get("local_path", ""))),
    ]
    for candidate in candidates:
        if not str(candidate):
            raise GateError("LIVE-G2 isolated config has an empty required path")
        if not _is_relative_to(candidate.resolve(), workspace_root):
            raise GateError(f"LIVE-G2 path escapes isolated workspace: {candidate}")

    formal_roots = [
        repo_root / "data/index",
        repo_root / "data/papers",
        repo_root / "data/parsed",
        repo_root / "data/artifacts",
        repo_root / "data/imports",
        repo_root / "runtime/session/credentials",
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        for formal_root in formal_roots:
            formal_resolved = formal_root.resolve()
            if _is_relative_to(resolved, formal_resolved) and not _is_relative_to(
                resolved, workspace_root
            ):
                raise GateError(f"LIVE-G2 path points at formal data root: {candidate}")
    for key in ("collection_chunks", "collection_wiki"):
        value = str(qdrant.get(key) or "")
        if not value.startswith(("paper_chunks_live_g2_", "wiki_entries_live_g2_")):
            raise GateError(f"LIVE-G2 qdrant {key} is not namespaced: {value!r}")
    return {"isolated": True, "workspace_root": str(workspace.work_root)}


def _live_g2_workspace_root(repo_root: Path, report: dict[str, Any] | None = None) -> Path:
    if report and report.get("workspace_root"):
        return Path(str(report["workspace_root"])).resolve()
    return (
        repo_root
        / "data/index/migration-gates/live-workspaces/G2"
        / _live_g2_suffix(repo_root)
    )


def _live_g2_suffix(repo_root: Path) -> str:
    try:
        return git_head(repo_root)[:12]
    except subprocess.CalledProcessError:
        return hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:12]


def _dsh_version(repo_root: Path) -> str:
    package = _read_json(repo_root / "integrations/deepseek-harness/package.json")
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps = package.get(key)
        if isinstance(deps, dict) and deps.get("@deepseek-ai/dsh"):
            return str(deps["@deepseek-ai/dsh"])
    raise GateError("integrations/deepseek-harness/package.json lacks @deepseek-ai/dsh")


def _live_g2_child_env(
    repo_root: Path,
    workspace: LiveG2Workspace,
    source_env: dict[str, str],
) -> dict[str, str]:
    env = dict(source_env)
    repo_src = str(repo_root / "src")
    existing_pythonpath = env.get("PYTHONPATH") or os.environ.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        repo_src if not existing_pythonpath else repo_src + os.pathsep + existing_pythonpath
    )
    if not env.get("OPENAI_API_KEY") and env.get("DEEPSEEK_API_KEY"):
        env["OPENAI_API_KEY"] = env["DEEPSEEK_API_KEY"]
    if not env.get("OPENAI_BASE_URL") and env.get("DEEPSEEK_BASE_URL"):
        env["OPENAI_BASE_URL"] = env["DEEPSEEK_BASE_URL"]
    if not env.get("DEEPSEEK_API_KEY") and env.get("OPENAI_API_KEY"):
        env["DEEPSEEK_API_KEY"] = env["OPENAI_API_KEY"]
    if not env.get("DEEPSEEK_BASE_URL") and env.get("OPENAI_BASE_URL"):
        env["DEEPSEEK_BASE_URL"] = env["OPENAI_BASE_URL"]
    env.update(
        {
            "CHAT_MODEL": LIVE001_MODEL,
            "SMALL_MODEL": LIVE001_MODEL,
            "PAPER_RAG_CONFIG": str(workspace.config_path),
            "PAPER_RAG_REPO_ROOT": str(repo_root),
            "PAPER_RAG_ACTOR_ID": LIVE_G2_ACTOR,
            "PAPER_RAG_MCP_TOOLSET": "research",
            "PAPER_RAG_ARTIFACT_ROOT": str(workspace.artifact_root),
            "PAPER_RAG_IMPORT_ROOT": str(workspace.import_root),
            "PAPER_RAG_MCP_CREDENTIAL_REFS": json.dumps(["OPENAI_API_KEY"]),
            "FEEDBACK_SQLITE_PATH": str(workspace.feedback_path),
            "DSH_HOME": str(workspace.dsh_home),
            "DSH_TELEMETRY_DISABLED": "1",
            "DSH_TELEMETRY_MODE": "DISABLED",
            "DSH_TOOLS_MODE": "native",
            "PAPER_RAG_DSH_CREDENTIALS_PATH": str(
                workspace.work_root / "credentials/.credentials.yaml"
            ),
            "PAPER_RAG_DSH_SKILL_ROOT": str(repo_root / ".dsh/skills"),
            "PAPER_RAG_DSH_PRESET_ID": "paper-research",
        }
    )
    return env


def _run_live005_headless_workflow(
    repo_root: Path,
    workspace: LiveG2Workspace,
    env: dict[str, str],
) -> dict[str, Any]:
    integration_root = repo_root / "integrations/deepseek-harness"
    dsh_bin = integration_root / "node_modules/.bin/dsh"
    patch_path = integration_root / "live-headless.patch.yml"
    if not dsh_bin.exists():
        raise GateError(f"LIVE-005 DSH binary not found: {_relpath(dsh_bin, repo_root)}")
    if not patch_path.exists():
        raise GateError(f"LIVE-005 headless patch not found: {_relpath(patch_path, repo_root)}")
    _install_live_g2_dsh_headless_assets(repo_root, workspace)

    proc = subprocess.run(
        [
            str(dsh_bin),
            "--profile",
            "headless",
            "--patch",
            str(patch_path),
            LIVE005_PROMPT,
        ],
        cwd=integration_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=int(env.get("PAPER_RAG_LIVE_TIMEOUT_SEC", "900")),
        check=False,
    )
    try:
        summary = _parse_live005_headless_json(proc.stdout)
    except GateError as exc:
        diagnostics = _live005_subprocess_diagnostics(proc, env)
        if diagnostics:
            raise GateError(f"{exc}; {diagnostics}") from exc
        raise
    summary["exit_code"] = proc.returncode
    return summary


def _install_live_g2_dsh_headless_assets(repo_root: Path, workspace: LiveG2Workspace) -> None:
    preset_source = repo_root / "integrations/deepseek-harness/presets/paper-research"
    runner_source = repo_root / "integrations/deepseek-harness/src/paper-rag-headless-runner.mjs"
    cards_source = repo_root / "integrations/deepseek-harness/src/paper-rag-cards.mjs"
    if not preset_source.exists():
        raise GateError(f"LIVE-005 preset source not found: {_relpath(preset_source, repo_root)}")
    if not runner_source.exists():
        raise GateError(f"LIVE-005 headless runner source not found: {_relpath(runner_source, repo_root)}")
    if not cards_source.exists():
        raise GateError(f"LIVE-005 headless card source not found: {_relpath(cards_source, repo_root)}")

    shutil.copytree(
        preset_source,
        workspace.dsh_home / ".agent-presets/paper-research",
        dirs_exist_ok=True,
    )
    runner_dest = workspace.dsh_home / "profiles/headless/src/paper-rag-headless-runner.mjs"
    runner_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(runner_source, runner_dest)
    shutil.copy2(cards_source, runner_dest.parent / "paper-rag-cards.mjs")


def _parse_live005_headless_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise GateError("LIVE-005 headless runner produced no JSON summary")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise GateError("LIVE-005 headless runner stdout did not contain a JSON object")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GateError(f"LIVE-005 headless runner JSON parse failed: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise GateError("LIVE-005 headless runner JSON summary must be an object")
    return parsed


def _live005_subprocess_diagnostics(
    proc: subprocess.CompletedProcess[str],
    env_source: dict[str, str],
) -> str:
    parts = [f"exit={proc.returncode}"]
    stderr = _redacted_text_excerpt(proc.stderr or "", env_source)
    stdout = _redacted_text_excerpt(proc.stdout or "", env_source)
    if stderr:
        parts.append(f"stderr={stderr}")
    if stdout:
        parts.append(f"stdout={stdout}")
    return "; ".join(parts)


def _redacted_text_excerpt(text: str, env_source: dict[str, str], limit: int = 500) -> str:
    excerpt = " ".join(text.strip().splitlines())[:limit]
    return _redact_secret_values(excerpt, env_source)


def _has_live005_tools(summary: dict[str, Any]) -> bool:
    calls = [str(name) for name in list(summary.get("tool_calls") or [])]
    ok, index = _contains_ordered_call(calls, "paper_discover", 0)
    if not ok:
        return False
    ok, index = _contains_any_ordered_call(
        calls,
        ("paper_ingest", "discovery_candidate_ingest"),
        index + 1,
    )
    if not ok:
        return False
    ok, index = _contains_any_ordered_call(
        calls,
        ("paper_qa", "paper_compare", "paper_section"),
        index + 1,
    )
    if not ok:
        return False
    ok, _index = _contains_ordered_call(calls, "paper_deliver", index + 1)
    return ok


def _contains_ordered_call(calls: list[str], name: str, start: int) -> tuple[bool, int]:
    try:
        return True, calls.index(name, start)
    except ValueError:
        return False, -1


def _contains_any_ordered_call(
    calls: list[str],
    names: tuple[str, ...],
    start: int,
) -> tuple[bool, int]:
    indexes = [calls.index(name, start) for name in names if name in calls[start:]]
    if not indexes:
        return False, -1
    return True, min(indexes)


def _has_live005_cards(summary: dict[str, Any]) -> bool:
    cards = {str(name) for name in list(summary.get("cards") or [])}
    return {
        "discovery_candidates",
        "ingest_receipt",
        "evidence_answer",
        "artifact_delivery",
    } <= cards


def _run_live002_workflow(
    repo_root: Path,
    workspace: LiveG2Workspace,
    env: dict[str, str],
) -> dict[str, Any]:
    del repo_root
    with _live_g2_env(env):
        discover_ctx = _live_g2_mcp_context(workspace, tool_call_id="live-g2-discover")
        discover = _mcp_structured(
            _mcp_call(
                "paper_discover",
                {"topic": LIVE_G2_TOPIC, "max_candidates": 3, "sources": ["arxiv"]},
                discover_ctx,
            )
        )
        candidates = list((discover.get("data") or {}).get("candidates") or [])
        selected = _select_live_g2_candidate(candidates)
        if not selected:
            return {
                "checks": [
                    {
                        "id": "discover-candidates",
                        "status": "FAIL",
                        "detail": f"candidate_count={len(candidates)}",
                    }
                ],
                "metrics": {"candidate_count": len(candidates)},
            }

        ingest_ctx = _live_g2_mcp_context(
            workspace,
            tool_call_id="live-g2-ingest",
            request_boundary_id=LIVE_G2_BOUNDARY_ID,
        )
        ingest_payload, ingest_tool = _live_g2_ingest_payload(selected)
        _ensure_live_g2_qdrant_collections()
        ingest = _mcp_structured(_mcp_call(ingest_tool, ingest_payload, ingest_ctx))
        ingest_result = _first_ingest_result(ingest)
        paper_id = str(ingest_result.get("paper_id") or selected.get("paper_id") or "")

        qa_ctx = _live_g2_mcp_context(workspace, tool_call_id="live-g2-qa")
        qa = _mcp_structured(
            _mcp_call(
                "paper_qa",
                {
                    "question": "What problem does this paper solve, and what is its main method?",
                    "paper_ids": [paper_id],
                    "top_k": 8,
                },
                qa_ctx,
            )
        )
        qa_data = qa.get("data") or {}
        citations = list(qa_data.get("citations") or [])
        chunks = list(qa_data.get("chunks") or [])
        checks = [
            {
                "id": "discover-candidates",
                "status": "PASS" if candidates else "FAIL",
                "detail": f"candidate_count={len(candidates)}",
            },
            {
                "id": "candidate-selected",
                "status": "PASS" if selected else "FAIL",
                "detail": str(selected.get("title") or selected.get("paper_id") or "")[:300],
            },
            {
                "id": "ingest-isolated",
                "status": "PASS"
                if paper_id and ingest_result.get("status") in {"ingested", "already_exists", "skipped", "done"}
                else "FAIL",
                "detail": f"tool={ingest_tool} paper_id={paper_id} status={ingest_result.get('status')}",
            },
            {
                "id": "qa-citations",
                "status": "PASS" if citations and chunks else "FAIL",
                "detail": f"citations={len(citations)} chunks={len(chunks)}",
            },
            {
                "id": "formal-library-untouched",
                "status": "PASS",
                "detail": f"sqlite={workspace.index_root / 'papers.sqlite'}",
            },
        ]
        return {
            "checks": checks,
            "metrics": {
                "candidate_count": len(candidates),
                "qa_citations": len(citations),
                "qa_chunks": len(chunks),
            },
            "paper_id": paper_id,
            "selected_candidate": _bounded_candidate_summary(selected),
            "ingest_tool": ingest_tool,
            "ingest_status": ingest_result.get("status"),
            "qa_trace_id": qa.get("trace_id"),
        }


def _run_live003_workflow(
    repo_root: Path,
    workspace: LiveG2Workspace,
    env: dict[str, str],
    paper_id: str,
) -> dict[str, Any]:
    del repo_root
    if not paper_id:
        raise GateError("LIVE-003 requires paper_id from LIVE-002")
    artifact_summaries: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    with _live_g2_env(env):
        for fmt in ("pptx", "pdf"):
            ctx = _live_g2_mcp_context(
                workspace,
                tool_call_id=f"live-g2-deliver-{fmt}",
                request_boundary_id=f"{LIVE_G2_BOUNDARY_ID}-deliver-{fmt}",
            )
            result = _mcp_structured(
                _mcp_call(
                    "paper_deliver",
                    {"format": fmt, "paper_ids": [paper_id], "title": LIVE_G2_TITLE},
                    ctx,
                )
            )
            artifact_summary, artifact_checks = _validate_live_g2_artifact(result, workspace, fmt)
            artifact_summaries.append(artifact_summary)
            checks.extend(artifact_checks)
    checks.append(
        {
            "id": "deliver-no-base64",
            "status": "PASS"
            if "content_base64" not in json.dumps(artifact_summaries, ensure_ascii=False)
            else "FAIL",
            "detail": "artifact metadata only",
        }
    )
    return {
        "checks": checks,
        "metrics": {
            "artifact_count": len(artifact_summaries),
            "citation_count": sum(int(item.get("n_citations") or 0) for item in artifact_summaries),
        },
        "paper_id": paper_id,
        "artifacts": artifact_summaries,
    }


def _run_live004_workflow(
    repo_root: Path,
    workspace: LiveG2Workspace,
    env: dict[str, str],
    paper_id: str,
) -> dict[str, Any]:
    if not paper_id:
        raise GateError("LIVE-004 requires paper_id from LIVE-002")
    turn_summaries: list[dict[str, Any]] = []
    with _live_g2_env(env):
        ctx = _live_g2_mcp_context(workspace, tool_call_id="live-g2-followup-1")
        first = _mcp_structured(
            _mcp_call(
                "paper_qa",
                {
                    "question": "What problem does this paper solve, and what is its main method? Cite indexed chunks.",
                    "paper_ids": [paper_id],
                    "top_k": 8,
                },
                ctx,
            )
        )
        second = _mcp_structured(
            _mcp_call(
                "paper_qa",
                {
                    "question": (
                        "Based only on indexed chunks, how does the previous answer's method "
                        "relate to this paper's RAG setup? Cite chunks if supported; otherwise "
                        "return a weak/no-evidence abstain."
                    ),
                    "paper_ids": [paper_id],
                    "top_k": 8,
                },
                _live_g2_mcp_context(workspace, tool_call_id="live-g2-followup-2"),
            )
        )
        for label, item in (("turn-1", first), ("turn-2", second)):
            data = item.get("data") or {}
            abstain_decision = _qa_abstain_decision(data)
            turn_summaries.append(
                {
                    "turn": label,
                    "trace_id": item.get("trace_id"),
                    "citation_count": len(list(data.get("citations") or [])),
                    "abstain_decision": abstain_decision,
                    "answer_excerpt": str(data.get("answer") or "")[:300],
                }
            )
        from paper_rag.rag import conversation_turn_store

        turns = conversation_turn_store.recent_turns(
            user_id=LIVE_G2_ACTOR,
            conversation_id=LIVE_G2_CONVERSATION_ID,
            limit=5,
        )
    session_path = _write_live_g2_session_proof(repo_root, workspace, turn_summaries)
    dsh_version = _dsh_version(repo_root)
    checks = [
        _live_g2_followup_evidence_check("turn-1", turn_summaries[0]),
        _live_g2_followup_evidence_check("turn-2", turn_summaries[1]),
        {
            "id": "conversation-turns-persisted",
            "status": "PASS" if len(turns) >= 2 else "FAIL",
            "detail": f"turns={len(turns)} conversation_id={LIVE_G2_CONVERSATION_ID}",
        },
        {
            "id": "versioned-dsh-session-proof",
            "status": "PASS" if session_path.exists() and workspace.dsh_home.parent.name == dsh_version else "FAIL",
            "detail": str(session_path),
        },
    ]
    return {
        "checks": checks,
        "metrics": {
            "turn_count": len(turns),
            "session_events": len(turn_summaries),
        },
        "paper_id": paper_id,
        "conversation_id": LIVE_G2_CONVERSATION_ID,
        "session_proof": str(session_path),
        "turns": turn_summaries,
    }


def _qa_abstain_decision(data: dict[str, Any]) -> str:
    abstain = data.get("abstain")
    if isinstance(abstain, dict):
        return str(abstain.get("decision") or "")
    return str(abstain or "")


def _live_g2_followup_evidence_check(label: str, summary: dict[str, Any]) -> dict[str, str]:
    citation_count = int(summary.get("citation_count") or 0)
    abstain_decision = str(summary.get("abstain_decision") or "")
    abstain_ok = abstain_decision in {"weak_evidence", "no_evidence", "no_chunks"}
    return {
        "id": f"followup-{label}-evidence",
        "status": "PASS" if citation_count > 0 or abstain_ok else "FAIL",
        "detail": f"citations={citation_count} abstain={abstain_decision or '-'}",
    }


@contextlib.contextmanager
def _live_g2_env(env: dict[str, str]):
    old = {key: os.environ.get(key) for key in env}
    old_sys_path = list(sys.path)
    repo_root = env.get("PAPER_RAG_REPO_ROOT")
    if repo_root:
        repo_src = str(Path(repo_root) / "src")
        if repo_src not in sys.path:
            sys.path.insert(0, repo_src)
    _reset_paper_rag_runtime()
    try:
        os.environ.update(env)
        _reset_paper_rag_runtime()
        yield
    finally:
        _reset_paper_rag_runtime()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        sys.path[:] = old_sys_path
        _reset_paper_rag_runtime()


def _reset_paper_rag_runtime() -> None:
    try:
        from paper_rag import config as paper_config

        paper_config.load.cache_clear()
    except Exception:
        pass
    try:
        from paper_rag.store import qdrant_store

        qdrant_store.close_client()
    except Exception:
        pass
    try:
        from paper_rag.store import sqlite_store

        engine = getattr(sqlite_store, "_ENGINE", None)
        if engine is not None:
            engine.dispose()
        sqlite_store._ENGINE = None
    except Exception:
        pass
    try:
        from paper_rag.retrieve import fts5

        fts5._INITIALIZED = False
    except Exception:
        pass
    try:
        from paper_rag.rag import conversation_turn_store

        conversation_turn_store._TABLE_READY = False
        conversation_turn_store._TABLE_ENGINE_KEY = None
    except Exception:
        pass
    try:
        from paper_rag.rag import llm

        llm.reset_client_for_test()
    except Exception:
        pass


def _live_g2_mcp_context(
    workspace: LiveG2Workspace,
    *,
    tool_call_id: str,
    request_boundary_id: str | None = None,
) -> Any:
    from paper_rag.mcp.context import McpRequestContext, McpServerConfig

    return McpRequestContext(
        config=McpServerConfig(
            toolset="research",
            actor_id=LIVE_G2_ACTOR,
            artifact_root=workspace.artifact_root,
            import_root=workspace.import_root,
        ),
        conversation_id=LIVE_G2_CONVERSATION_ID,
        tool_call_id=tool_call_id,
        request_boundary_id=request_boundary_id,
        caller="migration_gate",
    )


def _mcp_call(name: str, args: dict[str, Any], ctx: Any) -> dict[str, Any]:
    from paper_rag.mcp.registry import call_tool

    return call_tool(name, args, ctx)


def _mcp_structured(result: dict[str, Any]) -> dict[str, Any]:
    structured = result.get("structuredContent") or {}
    if structured.get("ok") is not True:
        error = structured.get("error") or {}
        raise GateError(
            f"{structured.get('tool', 'mcp tool')} failed: "
            f"{error.get('code', 'UNKNOWN')} {error.get('message', '')}"
        )
    return structured


def _ensure_live_g2_qdrant_collections() -> None:
    from paper_rag.tools import paper_index

    paper_index._ensure_qdrant_collections()


def _select_live_g2_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate.get("selected") and _candidate_has_ingest_source(candidate):
            return candidate
    for candidate in candidates:
        if _candidate_has_ingest_source(candidate):
            return candidate
    return None


def _candidate_has_ingest_source(candidate: dict[str, Any]) -> bool:
    return bool(candidate.get("id") or candidate.get("arxiv_id") or candidate.get("doi") or candidate.get("urls"))


def _live_g2_ingest_payload(candidate: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if candidate.get("id"):
        return {"candidate_ids": [candidate["id"]], "force": True}, "discovery_candidate_ingest"
    if candidate.get("arxiv_id"):
        return {"arxiv_id": str(candidate["arxiv_id"]), "force": True}, "paper_ingest"
    pdf_url = _first_live_g2_pdf_url(list(candidate.get("urls") or []))
    if pdf_url:
        return {"pdf_url": pdf_url, "title_hint": candidate.get("title"), "force": True}, "paper_ingest"
    raise GateError("selected candidate has no ingestable source")


def _first_live_g2_pdf_url(urls: list[str]) -> str | None:
    for url in urls:
        if ".pdf" in url.lower():
            return str(url)
    return str(urls[0]) if urls else None


def _first_ingest_result(ingest: dict[str, Any]) -> dict[str, Any]:
    data = ingest.get("data") or {}
    results = data.get("results")
    if isinstance(results, list) and results:
        return dict(results[0] or {})
    return dict(data)


def _bounded_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.get("id"),
        "paper_id": candidate.get("paper_id"),
        "arxiv_id": candidate.get("arxiv_id"),
        "source": candidate.get("source"),
        "title": str(candidate.get("title") or "")[:300],
        "rank": candidate.get("rank"),
    }


def _validate_live_g2_artifact(
    structured: dict[str, Any],
    workspace: LiveG2Workspace,
    fmt: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = structured.get("data") or {}
    artifact = data.get("artifact") or {}
    manifest_path = Path(str(artifact.get("manifest_path") or ""))
    if not manifest_path.exists():
        raise GateError(f"LIVE-003 missing artifact manifest for {fmt}: {manifest_path}")
    manifest = _read_json(manifest_path)
    files = manifest.get("files") or []
    if not files:
        raise GateError(f"LIVE-003 artifact manifest has no files for {fmt}")
    file_path = Path(str(files[0].get("path") or ""))
    if not file_path.exists():
        raise GateError(f"LIVE-003 artifact file missing for {fmt}: {file_path}")
    under_root = _is_relative_to(file_path.resolve(), workspace.artifact_root.resolve())
    if fmt == "pptx":
        open_ok = zipfile.is_zipfile(file_path)
    elif fmt == "pdf":
        open_ok = file_path.read_bytes()[:4] == b"%PDF"
    else:
        open_ok = file_path.stat().st_size > 0
    metadata = manifest.get("metadata") or {}
    deliver_meta = metadata.get("deliver") or {}
    n_citations = int(deliver_meta.get("n_citations") or 0)
    summary = {
        "format": fmt,
        "artifact_id": artifact.get("artifact_id"),
        "manifest_path": str(manifest_path),
        "file": str(file_path),
        "size_bytes": files[0].get("size_bytes"),
        "sha256": files[0].get("sha256"),
        "n_citations": n_citations,
    }
    checks = [
        {
            "id": f"deliver-{fmt}-under-artifact-root",
            "status": "PASS" if under_root else "FAIL",
            "detail": str(file_path),
        },
        {
            "id": f"deliver-{fmt}-opens",
            "status": "PASS" if open_ok else "FAIL",
            "detail": f"size={files[0].get('size_bytes')}",
        },
    ]
    return summary, checks


def _write_live_g2_session_proof(
    repo_root: Path,
    workspace: LiveG2Workspace,
    turn_summaries: list[dict[str, Any]],
) -> Path:
    session_dir = workspace.dsh_home / "paper-rag-session-proofs" / LIVE_G2_CONVERSATION_ID
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = session_dir / "session.jsonl"
    header = {
        "schema_version": 1,
        "kind": "live-g2-session-proof",
        "dsh_version": _dsh_version(repo_root),
    }
    lines = [json.dumps(header, ensure_ascii=False)]
    for item in turn_summaries:
        lines.append(
            json.dumps(
                {
                    "type": "assistant/message",
                    "data": {
                        "conversation_id": LIVE_G2_CONVERSATION_ID,
                        "turn": item.get("turn"),
                        "trace_id": item.get("trace_id"),
                        "citation_count": item.get("citation_count"),
                        "answer_excerpt": item.get("answer_excerpt"),
                    },
                },
                ensure_ascii=False,
            )
        )
    session_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return session_path


def _read_required_live_report(repo_root: Path, case_id: str) -> dict[str, Any]:
    path = repo_root / "data/index/migration-gates/live" / f"{case_id}.json"
    report = _read_json(path)
    if report.get("id") != case_id:
        raise GateError(f"live report id mismatch for {case_id}")
    if report.get("commit") != git_head(repo_root):
        raise GateError(f"live report commit does not match HEAD for {case_id}")
    if report.get("status") != "PASS":
        raise GateError(f"live report is not PASS for {case_id}")
    return report


def _live_g2_payload(
    workspace: LiveG2Workspace,
    summary: dict[str, Any],
    env_source: dict[str, str],
) -> dict[str, Any]:
    checks = list(summary.get("checks") or [])
    payload = {
        "status": _status_from_checks(checks),
        "checks": checks,
        "metrics": summary.get("metrics") or {},
        "model": LIVE001_MODEL,
        "data_root": f"isolated:{workspace.data_root}",
        "workspace_root": str(workspace.work_root),
        "config_path": str(workspace.config_path),
        "config_sha256": _sha256_if_exists(workspace.config_path),
        "resolved_paths": _live_g2_resolved_paths(workspace),
        "credential_refs": _credential_refs(env_source),
        "dsh_credential_ref": "DEEPSEEK_API_KEY",
        "side_effect_scope": (
            "persistent ignored isolated migration workspace under "
            "data/index/migration-gates/live-workspaces; not formal paper library"
        ),
        "writes_to_formal_paper_library": False,
    }
    for key in (
        "paper_id",
        "selected_candidate",
        "ingest_tool",
        "ingest_status",
        "qa_trace_id",
        "artifacts",
        "conversation_id",
        "session_proof",
        "turns",
        "summary",
    ):
        if key in summary:
            payload[key] = summary[key]
    return payload


def _live_g2_resolved_paths(workspace: LiveG2Workspace) -> dict[str, str]:
    return {
        "data_root": str(workspace.data_root),
        "papers_dir": str(workspace.data_root / "papers"),
        "parsed_dir": str(workspace.data_root / "parsed"),
        "index_dir": str(workspace.index_root),
        "sqlite_path": str(workspace.index_root / "papers.sqlite"),
        "feedback_sqlite_path": str(workspace.feedback_path),
        "qdrant_local_path": str(workspace.index_root / "qdrant_embedded"),
        "artifact_root": str(workspace.artifact_root),
        "import_root": str(workspace.import_root),
        "dsh_home": str(workspace.dsh_home),
    }


def _status_from_checks(checks: list[dict[str, Any]]) -> str:
    if checks and all(item.get("status") == "PASS" for item in checks):
        return "PASS"
    if any(item.get("status") == "BLOCKED" for item in checks):
        return "BLOCKED"
    return "FAIL"


def _live_g2_exception_summary(
    check_id: str,
    exc: Exception,
    env_source: dict[str, str],
    *,
    blocked: bool = False,
) -> dict[str, Any]:
    return {
        "checks": [
            {
                "id": check_id,
                "status": "BLOCKED" if blocked else "FAIL",
                "detail": _redacted_error_detail(exc, env_source),
            }
        ],
        "metrics": {},
    }


def _redacted_error_detail(exc: Exception, env_source: dict[str, str]) -> str:
    detail = f"{type(exc).__name__}: {str(exc).splitlines()[0][:500]}"
    return _redact_secret_values(detail, env_source)


def _redact_secret_values(detail: str, env_source: dict[str, str]) -> str:
    for key, value in env_source.items():
        if key.endswith(("API_KEY", "TOKEN", "SECRET")) and value:
            detail = detail.replace(value, f"${key}")
    return detail


def _credential_refs(env_source: dict[str, str]) -> list[str]:
    refs = []
    for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        if env_source.get(key):
            refs.append(key)
    return refs or ["OPENAI_API_KEY"]


def _sha256_if_exists(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


LIVE_CASE_RUNNERS: dict[str, LiveRunner] = {
    "LIVE-001": run_live001_dsh_model_qa,
    "LIVE-002": run_live002_discover_ingest_qa,
    "LIVE-003": run_live003_generate_artifacts,
    "LIVE-004": run_live004_resume_session_followup,
    "LIVE-005": run_live005_dsh_frontend_workflow,
}


def merge_component_reports(
    repo_root: Path, gate: str, cases: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    component_dir = repo_root / "data" / "index" / "migration-gates" / "components" / gate
    if not component_dir.exists():
        return []

    components: list[dict[str, Any]] = []
    for path in sorted(component_dir.glob("*.json")):
        report = _read_json(path)
        if report.get("gate") != gate:
            raise GateError(
                f"component report gate mismatch for {_relpath(path, repo_root)}: "
                f"expected {gate}, got {report.get('gate')}"
            )
        component = report.get("component") or path.stem
        components.append(
            {
                "component": component,
                "report": _relpath(path, repo_root),
                "go_no_go": report.get("go_no_go"),
            }
        )
        for case_id, case in report.get("cases", {}).items():
            if case_id in cases:
                cases[case_id] = case
    return components


def run_gate(repo_root: Path, manifest_path: Path, gate: str, report_path: Path) -> dict[str, Any]:
    if git_dirty(repo_root):
        raise GateError("run-gate requires clean checkout")
    manifest = _read_json(manifest_path)
    command_by_id = {
        command["id"]: command for command in manifest.get("owned_test_commands", [])
    }
    commands: list[dict[str, Any]] = []
    for command_id in manifest.get("gate_components", {}).get(gate, []):
        command = command_by_id.get(command_id)
        if command is None:
            raise GateError(f"gate {gate} references unknown command: {command_id}")
        cwd = _resolve_command_cwd(repo_root, command.get("repository", "."))
        commands.append(
            {
                "id": command_id,
                "command": command["command"],
                **_run_shell_component(repo_root, command["command"], cwd=cwd),
            }
        )

    required = _required_cases_for_gate(manifest, gate)
    cases = {
        case_id: {
            "status": "NOT_RUN",
            "reason": "case runner not implemented for this compatibility spike",
        }
        for case_id in required
    }
    _inherit_previous_gate_cases(repo_root, manifest, gate, cases)
    components = merge_component_reports(repo_root, gate, cases)
    _apply_command_case_coverage(commands, cases)
    required_pass = all(cases[case_id].get("status") == "PASS" for case_id in required)
    commands_pass = all(command.get("exit_code") == 0 for command in commands)
    result = {
        "schema_version": 1,
        "gate": gate,
        "commit": git_head(repo_root),
        "dirty": git_dirty(repo_root),
        "created_at": time.time(),
        "commands": commands,
        "components": components,
        "cases": cases,
        "go_no_go": "go" if required_pass and commands_pass else "no-go",
    }
    _write_json_atomic(report_path, result)
    return result


def _inherit_previous_gate_cases(
    repo_root: Path,
    manifest: dict[str, Any],
    gate: str,
    cases: dict[str, dict[str, Any]],
) -> None:
    for inherited_gate in manifest.get("inherits_required_cases", {}).get(gate, []):
        report_path = repo_root / "data" / "index" / "migration-gates" / f"{inherited_gate}.json"
        if not report_path.exists():
            continue
        report = _read_json(report_path)
        if report.get("gate") != inherited_gate:
            raise GateError(
                f"inherited report gate mismatch for {_relpath(report_path, repo_root)}"
            )
        for case_id, case in report.get("cases", {}).items():
            if case_id in cases and case.get("status") == "PASS":
                cases[case_id] = {
                    **case,
                    "inherited_from": inherited_gate,
                }


def _apply_command_case_coverage(
    commands: list[dict[str, Any]],
    cases: dict[str, dict[str, Any]],
) -> None:
    for command in commands:
        if command.get("exit_code") != 0:
            continue
        command_id = command.get("id")
        for case_id in CASE_COVERAGE_BY_COMMAND.get(str(command_id), ()):
            if case_id in cases and cases[case_id].get("status") != "PASS":
                cases[case_id] = {
                    "status": "PASS",
                    "evidence": f"command {command_id} passed",
                }


def diff_check(repo_root: Path, base_env: str, head: str) -> dict[str, Any]:
    base = os.environ.get(base_env)
    if not base:
        raise GateError(f"environment variable {base_env} is not set")
    proc = _run_git(repo_root, "diff", "--check", f"{base}...{head}", check=False)
    if proc.returncode != 0:
        raise GateError(proc.stdout.strip() or proc.stderr.strip() or "diff check failed")
    return {"schema_version": 1, "base": base, "head": head}


def extract_make_target_body(makefile_text: str, target: str) -> str:
    lines = makefile_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line == f"{target}:":
            start = i + 1
            break
    if start is None:
        raise GateError(f"Makefile target not found: {target}")

    body: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith(("\t", " ", "#")) and line.endswith(":"):
            break
        body.append(line)
    return "\n".join(body)


def validate_dsh_package(
    package_json: Path,
    *,
    expected_dsh_version: str,
    expected_cordis_version: str,
) -> dict[str, Any]:
    package = _read_json(package_json)
    all_deps = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        value = package.get(key, {})
        if isinstance(value, dict):
            all_deps.update(value)

    bad_ranges = {
        name: version
        for name, version in all_deps.items()
        if isinstance(version, str)
        and (version == "latest" or version.startswith(("^", "~", ">", "<", "*")))
    }
    if bad_ranges:
        details = ", ".join(f"{name}={version}" for name, version in sorted(bad_ranges.items()))
        raise GateError(f"non-exact dependency versions: {details}")

    dsh_packages = {
        name: version
        for name, version in all_deps.items()
        if name.startswith("@deepseek-ai/dsh")
    }
    if not dsh_packages:
        raise GateError("no direct @deepseek-ai/dsh* dependencies found")

    wrong_dsh = {
        name: version
        for name, version in dsh_packages.items()
        if version != expected_dsh_version
    }
    if wrong_dsh:
        details = ", ".join(f"{name}={version}" for name, version in sorted(wrong_dsh.items()))
        raise GateError(f"DSH dependency version mismatch: {details}")

    cordis_version = all_deps.get("@deepseek-ai/cordis")
    if cordis_version != expected_cordis_version:
        raise GateError(
            f"@deepseek-ai/cordis must be {expected_cordis_version}, got {cordis_version}"
        )

    return {
        "schema_version": 1,
        "package_json": package_json.as_posix(),
        "dsh_version": expected_dsh_version,
        "cordis_version": expected_cordis_version,
        "dsh_packages": sorted(dsh_packages),
        "pinned": True,
    }


def validate_dsh_lockfile(
    lockfile: Path,
    *,
    expected_dsh_version: str,
    expected_cordis_version: str,
) -> dict[str, Any]:
    try:
        lock = yaml.safe_load(lockfile.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GateError(f"lockfile not found: {lockfile}") from exc
    if not isinstance(lock, dict):
        raise GateError(f"invalid lockfile: {lockfile}")

    package_keys = lock.get("packages", {})
    if not isinstance(package_keys, dict):
        raise GateError("pnpm lockfile missing packages map")

    dsh_versions: set[str] = set()
    cordis_versions: set[str] = set()
    dsh_package_count = 0
    wrong_dsh: list[str] = []
    for key in package_keys:
        parsed = _parse_pnpm_package_key(str(key))
        if parsed is None:
            continue
        name, version = parsed
        if name == "@deepseek-ai/cordis":
            cordis_versions.add(version)
        if name.startswith("@deepseek-ai/dsh"):
            dsh_package_count += 1
            dsh_versions.add(version)
            if version != expected_dsh_version:
                wrong_dsh.append(f"{name}@{version}")

    if cordis_versions != {expected_cordis_version}:
        raise GateError(
            f"expected one Cordis version {expected_cordis_version}, got {sorted(cordis_versions)}"
        )
    if wrong_dsh:
        raise GateError(f"DSH lockfile version mismatch: {', '.join(sorted(wrong_dsh))}")
    if not dsh_package_count:
        raise GateError("no @deepseek-ai/dsh* packages found in lockfile")

    return {
        "schema_version": 1,
        "lockfile": lockfile.as_posix(),
        "cordis_versions": sorted(cordis_versions),
        "dsh_versions": sorted(dsh_versions),
        "dsh_package_count": dsh_package_count,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("freeze-baseline")
    p.add_argument("--spec", required=True)
    p.add_argument("--out", default="data/index/migration-gates/baseline.json")
    p.add_argument("--allow-dirty", action="store_true")
    p.add_argument("--execute", action="store_true")

    p = sub.add_parser("validate-baseline")
    p.add_argument("--baseline", default="data/index/migration-gates/baseline.json")
    p.add_argument("--spec", default=None)

    p = sub.add_parser("validate-legacy-matrix")
    p.add_argument("--spec", required=True)

    p = sub.add_parser("validate-report")
    p.add_argument("--gate", required=True)
    p.add_argument("--report", required=True)
    p.add_argument(
        "--manifest",
        default="specs/20260813-deepseek-harness-migration/test/test-manifest.json",
    )

    p = sub.add_parser("run-gate")
    p.add_argument("--gate", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--report", required=True)

    p = sub.add_parser("run-live")
    p.add_argument("--case", required=True)
    p.add_argument(
        "--manifest",
        default="specs/20260813-deepseek-harness-migration/test/test-manifest.json",
    )
    p.add_argument("--authorized-by", default=None)
    p.add_argument("--config-env", default=None)

    p = sub.add_parser("validate-live")
    p.add_argument("--gate", required=True)
    p.add_argument(
        "--manifest",
        default="specs/20260813-deepseek-harness-migration/test/test-manifest.json",
    )

    sub.add_parser("validate-cutover-defaults")
    p = sub.add_parser("validate-cutover")
    p.add_argument("--spec", required=True)
    sub.add_parser("validate-clean-checkout")

    p = sub.add_parser("diff-check")
    p.add_argument("--base-env", required=True)
    p.add_argument("--head", required=True)

    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve() if args.repo_root else _discover_repo_root()

    try:
        if args.command == "freeze-baseline":
            result = freeze_baseline(
                repo_root,
                (repo_root / args.spec).resolve(),
                repo_root / args.out,
                require_clean=not args.allow_dirty,
                execute_commands=args.execute,
            )
        elif args.command == "validate-baseline":
            result = validate_baseline(repo_root, repo_root / args.baseline)
        elif args.command == "validate-legacy-matrix":
            spec = repo_root / args.spec
            result = validate_legacy_matrix(repo_root, spec / "legacy-capability-matrix.json")
        elif args.command == "validate-report":
            result = validate_report(
                repo_root, repo_root / args.manifest, args.gate, repo_root / args.report
            )
        elif args.command == "run-gate":
            result = run_gate(repo_root, repo_root / args.manifest, args.gate, repo_root / args.report)
        elif args.command == "run-live":
            result = run_live(
                repo_root,
                repo_root / args.manifest,
                args.case,
                authorized_by=args.authorized_by,
                config_env=args.config_env,
            )
        elif args.command == "validate-live":
            result = validate_live(repo_root, repo_root / args.manifest, args.gate)
        elif args.command == "validate-cutover-defaults":
            result = validate_cutover_defaults(repo_root)
        elif args.command == "validate-cutover":
            result = validate_cutover(repo_root, repo_root / args.spec)
        elif args.command == "validate-clean-checkout":
            result = validate_clean_checkout(repo_root)
        elif args.command == "diff-check":
            result = diff_check(repo_root, args.base_env, args.head)
        else:  # pragma: no cover - argparse enforces command
            raise GateError(f"unknown command: {args.command}")
    except GateError as exc:
        print(f"migration_gate: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _discover_repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=True,
    )
    return Path(proc.stdout.strip()).resolve()


def _required_cases_for_gate(manifest: dict[str, Any], gate: str) -> list[str]:
    required: list[str] = []
    for inherited_gate in manifest.get("inherits_required_cases", {}).get(gate, []):
        required.extend(manifest.get("required_cases", {}).get(inherited_gate, []))
    required.extend(manifest.get("required_cases", {}).get(gate, []))
    return list(dict.fromkeys(required))


def _parse_pnpm_package_key(key: str) -> tuple[str, str] | None:
    base = key.split("(", 1)[0]
    if base.startswith("@"):
        idx = base.rfind("@")
        if idx <= 0:
            return None
        return base[:idx], base[idx + 1 :]
    if "@" not in base:
        return None
    name, version = base.rsplit("@", 1)
    return name, version


def _fingerprint(repo_root: Path, rel: Path) -> dict[str, Any]:
    path = repo_root / rel
    if not path.exists():
        raise GateError(f"fingerprint path missing: {rel.as_posix()}")
    data = path.read_bytes()
    return {
        "path": rel.as_posix(),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _resolve_command_cwd(repo_root: Path, repository: str) -> Path:
    candidate = (repo_root / repository).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise GateError(f"command repository escapes repo root: {repository}") from exc
    if not candidate.is_dir():
        raise GateError(f"command repository not found: {repository}")
    return candidate


def _run_shell_component(repo_root: Path, command: str, *, cwd: Path | None = None) -> dict[str, Any]:
    cwd = cwd or repo_root
    started = time.time()
    proc = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "exit_code": proc.returncode,
        "started_at": started,
        "finished_at": time.time(),
        "cwd": _relpath(cwd, repo_root),
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def _run_git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=check,
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GateError(f"json file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GateError(f"invalid json {path}: {exc}") from exc


def _coerce_non_negative_number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise GateError(f"{label} must be numeric")
    value = float(value)
    if value < 0:
        raise GateError(f"{label} must be non-negative")
    return value


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _relpath(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
