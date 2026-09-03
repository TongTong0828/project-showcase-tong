from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts import migration_gate

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "specs" / "20260813-deepseek-harness-migration"


def test_collect_legacy_tests_reads_configured_source_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    rel = Path("tests/test_gateway_paper_rag.py")
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text(
        """
def helper():
    return None


def test_first_case():
    pass


async def test_second_case():
    pass
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(migration_gate, "LEGACY_TEST_FILES", (rel,))

    tests = migration_gate.collect_legacy_tests(tmp_path)

    assert tests == [
        {"file": "tests/test_gateway_paper_rag.py", "test_name": "test_first_case", "line": 5},
        {"file": "tests/test_gateway_paper_rag.py", "test_name": "test_second_case", "line": 9},
    ]


def test_validate_legacy_matrix_rejects_missing_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    rel = Path("tests/test_gateway_paper_rag.py")
    source = tmp_path / rel
    source.parent.mkdir(parents=True)
    source.write_text(
        """
def test_routes_registered():
    pass


def test_missing_from_matrix():
    pass
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(migration_gate, "LEGACY_TEST_FILES", (rel,))
    matrix = {
        "schema_version": 1,
        "source_files": ["tests/test_gateway_paper_rag.py"],
        "entries": [
            {
                "file": "tests/test_gateway_paper_rag.py",
                "test_name": "test_routes_registered",
                "classification": "host-specific-delete",
                "replacement": "DSH-G0-003",
                "rationale": "covered by preset composition tests",
            }
        ],
    }
    path = tmp_path / "legacy-capability-matrix.json"
    path.write_text(json.dumps(matrix), encoding="utf-8")

    with pytest.raises(migration_gate.GateError, match="missing 1 legacy tests"):
        migration_gate.validate_legacy_matrix(tmp_path, path)


def test_validate_committed_legacy_matrix_covers_all_65_tests():
    result = migration_gate.validate_legacy_matrix(
        ROOT, SPEC / "legacy-capability-matrix.json"
    )

    assert result["total"] == 65
    assert result["by_file"]["tests/test_gateway_paper_rag.py"] == 17
    assert result["by_file"]["tests/test_middleware.py"] == 25
    assert result["by_file"]["tests/test_langgraph_middleware.py"] == 23
    assert set(result["by_classification"]) <= {
        "host-specific-delete",
        "capability-replaced-by-broker-or-mcp",
        "still-required-and-moved",
    }


def test_validate_legacy_matrix_accepts_frozen_inventory_after_source_removal(tmp_path: Path):
    matrix = {
        "schema_version": 1,
        "source_files": ["tests/test_gateway_paper_rag.py"],
        "entries": [
            {
                "file": "tests/test_gateway_paper_rag.py",
                "test_name": "test_routes_registered",
                "classification": "host-specific-delete",
                "replacement": "CUT-004",
                "rationale": "old host-specific test is removed after cutover",
            }
        ],
    }
    path = tmp_path / "legacy-capability-matrix.json"
    path.write_text(json.dumps(matrix), encoding="utf-8")

    result = migration_gate.validate_legacy_matrix(tmp_path, path)

    assert result["total"] == 1
    assert result["source_inventory"] == "matrix"


def test_freeze_baseline_records_dataset_hashes_and_quality_commands(tmp_path: Path):
    out = tmp_path / "baseline.json"
    expected_dirty = migration_gate.git_dirty(ROOT)

    result = migration_gate.freeze_baseline(
        ROOT, SPEC, out, require_clean=False, execute_commands=False
    )

    assert result["schema_version"] == 1
    assert result["commit"]
    assert result["dirty"] == expected_dirty
    paths = {fp["path"] for fp in result["fingerprints"]}
    assert {
        "tests/eval/qa_set.golden.jsonl",
        "tests/eval/gates.strict.json",
        "tests/eval/qa_set.claims.jsonl",
        "tests/eval/gates.claims.json",
        "specs/20260813-deepseek-harness-migration/test/test-manifest.json",
    } <= paths
    commands = {cmd["id"] for cmd in result["commands"]}
    assert {
        "eval-golden",
        "eval-golden-qa",
        "eval-citation-audit",
        "eval-claims",
        "verify-p0",
    } <= commands
    assert json.loads(out.read_text(encoding="utf-8")) == result


def test_validate_baseline_cli_accepts_manifest_spec_argument(tmp_path: Path, capsys):
    baseline = {"fingerprints": []}
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    code = migration_gate.main(
        [
            "--repo-root",
            str(tmp_path),
            "validate-baseline",
            "--spec",
            "specs/20260813-deepseek-harness-migration",
            "--baseline",
            str(baseline_path),
        ]
    )

    assert code == 0
    assert "fingerprints" in capsys.readouterr().out


def test_validate_report_requires_all_g0_cases(tmp_path: Path):
    report = {
        "schema_version": 1,
        "gate": "G0",
        "commit": migration_gate.git_head(ROOT),
        "dirty": False,
        "cases": {"DSH-G0-001": {"status": "PASS"}},
        "commands": [],
        "go_no_go": "no-go",
    }
    path = tmp_path / "G0.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(migration_gate.GateError, match="missing required cases"):
        migration_gate.validate_report(ROOT, SPEC / "test" / "test-manifest.json", "G0", path)


def test_merge_component_reports_updates_required_cases(tmp_path: Path):
    component_dir = tmp_path / "data/index/migration-gates/components/G0"
    component_dir.mkdir(parents=True)
    component = {
        "schema_version": 1,
        "gate": "G0",
        "component": "dsh-g0-compat",
        "cases": {
            "DSH-G0-001": {"status": "PASS", "evidence": "ok"},
            "DSH-G0-002": {"status": "BLOCKED", "reason": "pending"},
            "IGNORED-001": {"status": "PASS", "evidence": "not required"},
        },
        "go_no_go": "no-go",
    }
    (component_dir / "dsh-g0-compat.json").write_text(
        json.dumps(component), encoding="utf-8"
    )
    cases = {
        "DSH-G0-001": {"status": "NOT_RUN"},
        "DSH-G0-002": {"status": "NOT_RUN"},
    }

    components = migration_gate.merge_component_reports(tmp_path, "G0", cases)

    assert components == [
        {
            "component": "dsh-g0-compat",
            "report": "data/index/migration-gates/components/G0/dsh-g0-compat.json",
            "go_no_go": "no-go",
        }
    ]
    assert cases["DSH-G0-001"] == {"status": "PASS", "evidence": "ok"}
    assert cases["DSH-G0-002"] == {"status": "BLOCKED", "reason": "pending"}
    assert "IGNORED-001" not in cases


def test_run_gate_executes_component_in_declared_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = tmp_path
    component_root = repo / "component"
    component_root.mkdir()
    (component_root / "marker.txt").write_text("ok", encoding="utf-8")
    manifest = {
        "owned_test_commands": [
            {
                "id": "cwd-check",
                "repository": "component",
                "command": (
                    f"{sys.executable} -c "
                    "\"from pathlib import Path; "
                    "print(Path.cwd().name); "
                    "assert Path('marker.txt').read_text() == 'ok'\""
                ),
            }
        ],
        "gate_components": {"G0": ["cwd-check"]},
        "required_cases": {"G0": []},
    }
    manifest_path = repo / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report_path = repo / "G0.json"
    monkeypatch.setattr(migration_gate, "git_dirty", lambda _repo_root: False)
    monkeypatch.setattr(migration_gate, "git_head", lambda _repo_root: "test-head")

    report = migration_gate.run_gate(repo, manifest_path, "G0", report_path)

    command = report["commands"][0]
    assert command["status"] == "PASS"
    assert command["cwd"] == "component"
    assert command["stdout"].strip() == "component"


def test_run_gate_inherits_previous_gate_cases_and_marks_command_covered_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    report_root = tmp_path / "data/index/migration-gates"
    report_root.mkdir(parents=True)
    (report_root / "G0.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "G0",
                "commit": "previous-head",
                "dirty": False,
                "cases": {"DSH-G0-001": {"status": "PASS", "evidence": "locked"}},
                "commands": [],
                "go_no_go": "go",
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "owned_test_commands": [
            {
                "id": "mcp-contract",
                "repository": ".",
                "command": f"{sys.executable} -c \"print('contract ok')\"",
            },
            {
                "id": "mcp-operations",
                "repository": ".",
                "command": f"{sys.executable} -c \"print('operations ok')\"",
            }
        ],
        "gate_components": {"G1": ["mcp-contract", "mcp-operations"]},
        "required_cases": {
            "G0": ["DSH-G0-001"],
            "G1": [
                "MCP-001",
                "MCP-002",
                "MCP-003",
                "MCP-004",
                "MCP-005",
                "MCP-006",
                "MCP-007",
                "MCP-008",
            ],
        },
        "inherits_required_cases": {"G1": ["G0"]},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report_path = report_root / "G1.json"
    monkeypatch.setattr(migration_gate, "git_dirty", lambda _repo_root: False)
    monkeypatch.setattr(migration_gate, "git_head", lambda _repo_root: "test-head")

    report = migration_gate.run_gate(tmp_path, manifest_path, "G1", report_path)

    assert report["cases"]["DSH-G0-001"]["status"] == "PASS"
    assert report["cases"]["MCP-001"]["status"] == "PASS"
    assert report["cases"]["MCP-007"]["evidence"] == "command mcp-contract passed"
    assert report["cases"]["MCP-008"]["evidence"] == "command mcp-operations passed"
    assert report["go_no_go"] == "go"


def test_run_gate_marks_g2_research_artifact_and_session_cases_from_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = {
        "owned_test_commands": [
            {
                "id": "mcp-artifacts",
                "repository": ".",
                "command": f"{sys.executable} -c \"print('artifacts ok')\"",
            },
            {
                "id": "dsh-test",
                "repository": ".",
                "command": f"{sys.executable} -c \"print('session ok')\"",
            },
        ],
        "gate_components": {"G2": ["mcp-artifacts", "dsh-test"]},
        "required_cases": {
            "G2": [
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
                "SESSION-001",
                "SESSION-002",
                "SESSION-003",
                "SESSION-004",
                "SESSION-005",
                "SESSION-006",
            ],
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(migration_gate, "git_dirty", lambda _repo_root: False)
    monkeypatch.setattr(migration_gate, "git_head", lambda _repo_root: "test-head")

    report = migration_gate.run_gate(tmp_path, manifest_path, "G2", tmp_path / "G2.json")

    for case_id in manifest["required_cases"]["G2"]:
        assert report["cases"][case_id]["status"] == "PASS"
    assert report["cases"]["WRITE-001"]["evidence"] == "command mcp-artifacts passed"
    assert report["cases"]["SESSION-006"]["evidence"] == "command dsh-test passed"
    assert report["go_no_go"] == "go"


def test_run_gate_maps_g3_proactive_cases_from_python_core(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = {
        "owned_test_commands": [
            {
                "id": "python-core",
                "repository": ".",
                "command": f"{sys.executable} -c \"print('core ok')\"",
            }
        ],
        "gate_components": {"G3": ["python-core"]},
        "required_cases": {
            "G3": ["PRO-001", "PRO-002", "PRO-003", "PRO-004", "PRO-005"],
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(migration_gate, "git_dirty", lambda _repo_root: False)
    monkeypatch.setattr(migration_gate, "git_head", lambda _repo_root: "test-head")

    report = migration_gate.run_gate(tmp_path, manifest_path, "G3", tmp_path / "G3.json")

    for case_id in manifest["required_cases"]["G3"]:
        assert report["cases"][case_id] == {
            "status": "PASS",
            "evidence": "command python-core passed",
        }
    assert report["go_no_go"] == "go"


def test_run_gate_maps_g4_cutover_cases_from_component_validators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = {
        "owned_test_commands": [
            {
                "id": "cutover-defaults",
                "repository": ".",
                "command": f"{sys.executable} -c \"print('cutover defaults ok')\"",
            },
            {
                "id": "dsh-smoke",
                "repository": ".",
                "command": f"{sys.executable} -c \"print('dsh smoke ok')\"",
            },
            {
                "id": "clean-checkout",
                "repository": ".",
                "command": f"{sys.executable} -c \"print('clean checkout ok')\"",
            },
        ],
        "gate_components": {
            "G4": ["cutover-defaults", "dsh-smoke", "clean-checkout"]
        },
        "required_cases": {"G4": ["CUT-002", "CUT-003", "CUT-005"]},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(migration_gate, "git_dirty", lambda _repo_root: False)
    monkeypatch.setattr(migration_gate, "git_head", lambda _repo_root: "test-head")

    report = migration_gate.run_gate(tmp_path, manifest_path, "G4", tmp_path / "G4.json")

    assert report["cases"]["CUT-002"] == {
        "status": "PASS",
        "evidence": "command cutover-defaults passed",
    }
    assert report["cases"]["CUT-003"] == {
        "status": "PASS",
        "evidence": "command dsh-smoke passed",
    }
    assert report["cases"]["CUT-005"] == {
        "status": "PASS",
        "evidence": "command clean-checkout passed",
    }
    assert report["go_no_go"] == "go"


def test_run_gate_maps_g5_cutover_cases_from_cut_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = {
        "owned_test_commands": [
            {
                "id": "cut-validator",
                "repository": ".",
                "command": f"{sys.executable} -c \"print('cutover removal ok')\"",
            }
        ],
        "gate_components": {"G5": ["cut-validator"]},
        "required_cases": {"G5": ["CUT-001", "CUT-004", "CUT-006"]},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(migration_gate, "git_dirty", lambda _repo_root: False)
    monkeypatch.setattr(migration_gate, "git_head", lambda _repo_root: "test-head")

    report = migration_gate.run_gate(tmp_path, manifest_path, "G5", tmp_path / "G5.json")

    assert report["cases"]["CUT-001"] == {
        "status": "PASS",
        "evidence": "command cut-validator passed",
    }
    assert report["cases"]["CUT-004"] == {
        "status": "PASS",
        "evidence": "command cut-validator passed",
    }
    assert report["cases"]["CUT-006"] == {
        "status": "PASS",
        "evidence": "command cut-validator passed",
    }
    assert report["go_no_go"] == "go"


def test_validate_cutover_defaults_requires_dsh_default_entrypoints():
    result = migration_gate.validate_cutover_defaults(ROOT)

    assert result["schema_version"] == 1
    assert result["checks"]
    assert all(check["status"] == "PASS" for check in result["checks"])


def test_validate_cutover_rejects_deerflow_runtime_residue(tmp_path: Path):
    (tmp_path / "docs/adrs").mkdir(parents=True)
    (tmp_path / "docs/adrs/0008-deerflow-integration-and-guardrails.md").write_text(
        "# ADR\n\nStatus: Superseded\n\nHistorical DeerFlow decision.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/CHANGELOG.md").write_text(
        "G5 removed the old DeerFlow host.\n",
        encoding="utf-8",
    )
    (tmp_path / "src/paper_rag").mkdir(parents=True)
    (tmp_path / "src/paper_rag/runtime.py").write_text(
        "DEERFLOW_GATEWAY_URL = 'http://127.0.0.1:8000'\n",
        encoding="utf-8",
    )
    spec_dir = tmp_path / "specs/20260813-deepseek-harness-migration"
    spec_dir.mkdir(parents=True)

    with pytest.raises(migration_gate.GateError, match="runtime residue"):
        migration_gate.validate_cutover(tmp_path, spec_dir)


def test_validate_cutover_allows_historical_deerflow_records(tmp_path: Path):
    (tmp_path / "docs/adrs").mkdir(parents=True)
    (tmp_path / "docs/adrs/0008-deerflow-integration-and-guardrails.md").write_text(
        "# ADR\n\nStatus: Superseded by ADR-0022\n\nHistorical DeerFlow integration.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/CHANGELOG.md").write_text(
        "G5 removed the old DeerFlow host.\n",
        encoding="utf-8",
    )
    spec_dir = tmp_path / "specs/20260813-deepseek-harness-migration"
    spec_dir.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "tag", "deepseek-harness-g5-pre-removal"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    result = migration_gate.validate_cutover(tmp_path, spec_dir)

    assert result["schema_version"] == 1
    assert {check["id"]: check["status"] for check in result["checks"]} == {
        "deerflow-workspace-removed": "PASS",
        "deerflow-smoke-removed": "PASS",
        "makefile-deerflow-targets-removed": "PASS",
        "pyproject-deerflow-extra-removed": "PASS",
        "residual-runtime-references": "PASS",
        "pre-removal-ref-recorded": "PASS",
    }
    assert result["residual_references"] == [
        {
            "path": "docs/CHANGELOG.md",
            "line": 1,
            "classification": "historical-changelog",
        },
        {
            "path": "docs/adrs/0008-deerflow-integration-and-guardrails.md",
            "line": 5,
            "classification": "superseded-adr",
        },
    ]


def test_validate_clean_checkout_reports_clean(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(migration_gate, "git_dirty", lambda _repo_root: False)
    monkeypatch.setattr(migration_gate, "git_head", lambda _repo_root: "clean-head")

    result = migration_gate.validate_clean_checkout(ROOT)

    assert result == {
        "schema_version": 1,
        "commit": "clean-head",
        "dirty": False,
        "status": "PASS",
    }


def test_validate_clean_checkout_rejects_dirty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(migration_gate, "git_dirty", lambda _repo_root: True)

    with pytest.raises(migration_gate.GateError, match="clean checkout required"):
        migration_gate.validate_clean_checkout(ROOT)


def test_validate_live_requires_authorized_fresh_pass_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    report_path = tmp_path / "data/index/migration-gates/live/LIVE-001.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "LIVE-001",
                "gate": "G1",
                "commit": "test-head",
                "status": "PASS",
                "authorized": True,
                "created_at": time.time(),
                "side_effects": ["real LLM calls"],
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "live_cases": [
            {
                "id": "LIVE-001",
                "gate": "G1",
                "report": "data/index/migration-gates/live/LIVE-001.json",
                "max_age_hours": 24,
                "requires_authorization": True,
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(migration_gate, "git_head", lambda _repo_root: "test-head")

    result = migration_gate.validate_live(tmp_path, manifest_path, "G1")

    assert result["gate"] == "G1"
    assert result["live_cases"] == ["LIVE-001"]


def test_validate_live_rejects_missing_or_unauthorized_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = {
        "live_cases": [
            {
                "id": "LIVE-001",
                "gate": "G1",
                "report": "data/index/migration-gates/live/LIVE-001.json",
                "max_age_hours": 24,
                "requires_authorization": True,
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(migration_gate.GateError, match="live report not found"):
        migration_gate.validate_live(tmp_path, manifest_path, "G1")

    report_path = tmp_path / "data/index/migration-gates/live/LIVE-001.json"
    report_path.parent.mkdir(parents=True)
    monkeypatch.setattr(migration_gate, "git_head", lambda _repo_root: "test-head")
    report_path.write_text(
        json.dumps(
            {
                "id": "LIVE-001",
                "gate": "G1",
                "commit": "test-head",
                "status": "PASS",
                "authorized": False,
                "created_at": time.time(),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(migration_gate.GateError, match="not authorized"):
        migration_gate.validate_live(tmp_path, manifest_path, "G1")


def test_run_live_requires_explicit_authorization_before_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = {
        "live_cases": [
            {
                "id": "LIVE-001",
                "gate": "G1",
                "report": "data/index/migration-gates/live/LIVE-001.json",
                "requires_authorization": True,
                "side_effects": ["real LLM calls"],
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(migration_gate, "git_dirty", lambda _repo_root: False)
    called = {"runner": False}

    def fake_runner(*args, **kwargs):
        called["runner"] = True
        return {"status": "PASS"}

    with pytest.raises(migration_gate.GateError, match="requires explicit authorization"):
        migration_gate.run_live(
            tmp_path,
            manifest_path,
            "LIVE-001",
            runner_registry={"LIVE-001": fake_runner},
        )

    assert called["runner"] is False
    assert not (tmp_path / "data/index/migration-gates/live/LIVE-001.json").exists()


def test_run_live_writes_authorized_current_commit_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = {
        "live_cases": [
            {
                "id": "LIVE-001",
                "gate": "G1",
                "report": "data/index/migration-gates/live/LIVE-001.json",
                "max_age_hours": 24,
                "requires_authorization": True,
                "side_effects": ["real LLM calls"],
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(migration_gate, "git_dirty", lambda _repo_root: False)
    monkeypatch.setattr(migration_gate, "git_head", lambda _repo_root: "test-head")

    def fake_runner(repo_root, live_case, *, config_env, authorized_by):
        return {
            "status": "PASS",
            "checks": [{"id": "fixed-paper-qa", "status": "PASS"}],
            "metrics": {"cite_precision": 1.0, "abstain_ok": 1.0},
            "data_root": "data/index",
            "credential_refs": ["OPENAI_API_KEY"],
            "model": "deepseek-v4-flash",
        }

    result = migration_gate.run_live(
        tmp_path,
        manifest_path,
        "LIVE-001",
        authorized_by="at",
        config_env="PAPER_RAG_CONFIG",
        runner_registry={"LIVE-001": fake_runner},
    )

    assert result["id"] == "LIVE-001"
    assert result["gate"] == "G1"
    assert result["status"] == "PASS"
    assert result["authorized"] is True
    assert result["authorized_by"] == "at"
    assert result["commit"] == "test-head"
    assert result["side_effects"] == ["real LLM calls"]
    assert result["config_env"] == "PAPER_RAG_CONFIG"
    assert result["checks"] == [{"id": "fixed-paper-qa", "status": "PASS"}]
    assert json.loads((tmp_path / "data/index/migration-gates/live/LIVE-001.json").read_text()) == result
    assert migration_gate.validate_live(tmp_path, manifest_path, "G1")["live_cases"] == ["LIVE-001"]


def test_live001_runner_uses_isolated_workspace_and_flash_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source_env = {
        "OPENAI_API_KEY": "test-secret",
        "OPENAI_BASE_URL": "https://api.deepseek.com",
        "CHAT_MODEL": "deepseek-v4-flash",
        "SMALL_MODEL": "deepseek-v4-flash",
    }
    workspace = migration_gate.Live001Workspace(
        work_root=tmp_path / "work",
        dsh_home=tmp_path / "work/dsh-home",
        data_root=tmp_path / "work/data",
        config_path=tmp_path / "work/config.yaml",
        source_data_root=tmp_path / "data/index",
    )
    captured = {}

    monkeypatch.setattr(
        migration_gate,
        "_prepare_live001_workspace",
        lambda repo_root, work_root: workspace,
    )

    def fake_headless(repo_root, prepared, env):
        captured["repo_root"] = repo_root
        captured["workspace"] = prepared
        captured["env"] = env
        return {
            "checks": [
                {"id": "dsh-headless-exit", "status": "PASS"},
                {"id": "fixed-paper-citation", "status": "PASS"},
                {"id": "no-evidence-abstain", "status": "PASS"},
            ],
            "metrics": {
                "tool_calls": 2,
                "paper_qa_calls": 2,
                "citation_checks_passed": 1,
                "abstain_checks_passed": 1,
            },
            "dsh_model": "deepseek-v4-flash",
            "assistant_excerpt": "ok",
        }

    monkeypatch.setattr(migration_gate, "_run_live001_headless", fake_headless)

    result = migration_gate.run_live001_dsh_model_qa(
        tmp_path,
        {"id": "LIVE-001"},
        config_env=None,
        authorized_by="at",
        source_env=source_env,
    )

    assert result["status"] == "PASS"
    assert result["model"] == "deepseek-v4-flash"
    assert result["dsh_model"] == "deepseek-v4-flash"
    assert result["data_root"].startswith("isolated:")
    assert result["source_data_root"] == "data/index"
    assert result["credential_refs"] == ["OPENAI_API_KEY"]
    assert "test-secret" not in json.dumps(result)
    assert captured["env"]["CHAT_MODEL"] == "deepseek-v4-flash"
    assert captured["env"]["SMALL_MODEL"] == "deepseek-v4-flash"
    assert captured["env"]["DEEPSEEK_API_KEY"] == "test-secret"
    assert captured["env"]["PAPER_RAG_CONFIG"] == str(workspace.config_path)
    assert captured["env"]["DSH_HOME"] == str(workspace.dsh_home)
    assert captured["env"]["PAPER_RAG_MCP_TOOLSET"] == "readonly"


def test_prepare_live001_workspace_copies_headless_runner_into_profile(tmp_path: Path):
    repo_root = tmp_path / "repo"
    (repo_root / "data/index/qdrant_embedded").mkdir(parents=True)
    (repo_root / "data/index/papers.sqlite").write_text("sqlite", encoding="utf-8")
    (repo_root / "data/index/qdrant_embedded/collection").write_text("qdrant", encoding="utf-8")
    (repo_root / "config").mkdir()
    (repo_root / "config/local.yaml").write_text(
        """
paths: {}
qdrant: {}
llm: {}
""".lstrip(),
        encoding="utf-8",
    )
    preset_source = repo_root / "integrations/deepseek-harness/presets/paper-research"
    preset_source.mkdir(parents=True)
    (preset_source / "preset.yml").write_text("name: Paper Research\n", encoding="utf-8")
    (preset_source / "agent.cordis.yml").write_text(
        "- id: tool-skill\n  name: '@deepseek-ai/dsh-tool-skill'\n",
        encoding="utf-8",
    )
    runner_source = repo_root / "integrations/deepseek-harness/src/paper-rag-headless-runner.mjs"
    runner_source.parent.mkdir(parents=True)
    runner_source.write_text("export const name = 'paper-rag-headless-runner';\n", encoding="utf-8")
    cards_source = repo_root / "integrations/deepseek-harness/src/paper-rag-cards.mjs"
    cards_source.write_text("export function cardTypeForTool() {}\n", encoding="utf-8")

    workspace = migration_gate._prepare_live001_workspace(repo_root, tmp_path / "work")

    runner_dest = workspace.dsh_home / "profiles/headless/src/paper-rag-headless-runner.mjs"
    cards_dest = workspace.dsh_home / "profiles/headless/src/paper-rag-cards.mjs"
    assert runner_dest.read_text(encoding="utf-8") == runner_source.read_text(encoding="utf-8")
    assert cards_dest.read_text(encoding="utf-8") == cards_source.read_text(encoding="utf-8")


def test_prepare_live_g2_workspace_writes_isolated_config(tmp_path: Path):
    repo_root = tmp_path / "repo"
    (repo_root / "config").mkdir(parents=True)
    (repo_root / "config/local.yaml").write_text(
        """
paths: {}
embedding: {}
qdrant: {}
llm: {}
mineru: {}
wiki: {}
""".lstrip(),
        encoding="utf-8",
    )
    (repo_root / "integrations/deepseek-harness").mkdir(parents=True)
    (repo_root / "integrations/deepseek-harness/package.json").write_text(
        json.dumps({"dependencies": {"@deepseek-ai/dsh": "0.1.0-rc.6"}}),
        encoding="utf-8",
    )

    workspace = migration_gate._prepare_live_g2_workspace(
        repo_root, tmp_path / "work", reset=True
    )
    raw = yaml.safe_load(workspace.config_path.read_text(encoding="utf-8"))

    assert Path(raw["paths"]["sqlite_path"]).is_relative_to(workspace.work_root)
    assert Path(raw["paths"]["papers_dir"]).is_relative_to(workspace.work_root)
    assert Path(raw["paths"]["parsed_dir"]).is_relative_to(workspace.work_root)
    assert Path(raw["qdrant"]["local_path"]).is_relative_to(workspace.work_root)
    assert raw["qdrant"]["collection_chunks"].startswith("paper_chunks_live_g2_")
    assert workspace.feedback_path == workspace.index_root / "feedback.sqlite"
    assert workspace.artifact_root.is_dir()
    assert workspace.import_root.is_dir()
    assert workspace.dsh_home.parent.name == "0.1.0-rc.6"
    assert migration_gate._assert_live_g2_workspace_isolated(repo_root, workspace) == {
        "isolated": True,
        "workspace_root": str(workspace.work_root),
    }


def test_live_g2_runners_are_registered_and_use_flash_isolated_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source_env = {
        "OPENAI_API_KEY": "test-secret",
        "OPENAI_BASE_URL": "https://api.deepseek.com",
        "CHAT_MODEL": "deepseek-v4-flash",
        "SMALL_MODEL": "deepseek-v4-flash",
    }
    workspace = migration_gate.LiveG2Workspace(
        work_root=tmp_path / "work",
        data_root=tmp_path / "work/data",
        index_root=tmp_path / "work/data/index",
        artifact_root=tmp_path / "work/artifacts",
        import_root=tmp_path / "work/imports",
        dsh_home=tmp_path / "work/runtime/deepseek-harness/versions/0.1.0-rc.6",
        config_path=tmp_path / "work/config.live-g2.yaml",
        feedback_path=tmp_path / "work/data/index/feedback.sqlite",
    )
    prepare_resets = []
    captured = {}

    monkeypatch.setattr(
        migration_gate,
        "_prepare_live_g2_workspace",
        lambda repo_root, work_root, *, reset=False: (
            prepare_resets.append(reset) or workspace
        ),
    )
    monkeypatch.setattr(
        migration_gate,
        "_assert_live_g2_workspace_isolated",
        lambda repo_root, prepared: {"isolated": True, "workspace_root": str(prepared.work_root)},
    )

    def fake_workflow(repo_root, prepared, env):
        captured["workspace"] = prepared
        captured["env"] = env
        return {
            "checks": [{"id": "fake-live-g2", "status": "PASS"}],
            "metrics": {"tool_calls": 3},
            "paper_id": "arxiv:2601.00001",
        }

    monkeypatch.setattr(migration_gate, "_run_live002_workflow", fake_workflow)

    result = migration_gate.run_live002_discover_ingest_qa(
        tmp_path,
        {"id": "LIVE-002"},
        config_env="PAPER_RAG_CONFIG",
        authorized_by="at",
        source_env=source_env,
    )

    assert {"LIVE-002", "LIVE-003", "LIVE-004"} <= set(migration_gate.LIVE_CASE_RUNNERS)
    assert result["status"] == "PASS"
    assert result["model"] == "deepseek-v4-flash"
    assert result["paper_id"] == "arxiv:2601.00001"
    assert result["data_root"] == f"isolated:{workspace.data_root}"
    assert result["writes_to_formal_paper_library"] is False
    assert captured["env"]["PAPER_RAG_CONFIG"] == str(workspace.config_path)
    assert captured["env"]["FEEDBACK_SQLITE_PATH"] == str(workspace.feedback_path)
    assert captured["env"]["PAPER_RAG_ARTIFACT_ROOT"] == str(workspace.artifact_root)
    assert captured["env"]["PAPER_RAG_IMPORT_ROOT"] == str(workspace.import_root)
    assert captured["env"]["CHAT_MODEL"] == "deepseek-v4-flash"
    assert captured["env"]["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path / "src")
    assert "test-secret" not in json.dumps(result)


def test_live005_runner_uses_dsh_headless_isolated_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source_env = {
        "OPENAI_API_KEY": "test-secret",
        "OPENAI_BASE_URL": "https://api.deepseek.com",
        "CHAT_MODEL": "deepseek-v4-flash",
        "SMALL_MODEL": "deepseek-v4-flash",
    }
    workspace = migration_gate.LiveG2Workspace(
        work_root=tmp_path / "work",
        data_root=tmp_path / "work/data",
        index_root=tmp_path / "work/data/index",
        artifact_root=tmp_path / "work/artifacts",
        import_root=tmp_path / "work/imports",
        dsh_home=tmp_path / "work/runtime/deepseek-harness/versions/0.1.0-rc.6/dsh-home",
        config_path=tmp_path / "work/config.live-g2.yaml",
        feedback_path=tmp_path / "work/data/index/feedback.sqlite",
    )
    prepare_resets = []
    captured = {}

    monkeypatch.setattr(
        migration_gate,
        "_prepare_live_g2_workspace",
        lambda repo_root, work_root, *, reset=False: (
            prepare_resets.append(reset) or workspace
        ),
    )
    monkeypatch.setattr(
        migration_gate,
        "_assert_live_g2_workspace_isolated",
        lambda repo_root, prepared: {"isolated": True, "workspace_root": str(prepared.work_root)},
    )

    def fake_headless(repo_root, prepared, env):
        captured["workspace"] = prepared
        captured["env"] = env
        return {
            "preset": "paper-research",
            "tool_calls": [
                "paper_discover",
                "discovery_candidate_ingest",
                "paper_qa",
                "paper_deliver",
            ],
            "cards": [
                "discovery_candidates",
                "ingest_receipt",
                "evidence_answer",
                "artifact_delivery",
            ],
            "text": "done",
        }

    monkeypatch.setattr(
        migration_gate,
        "_run_live005_headless_workflow",
        fake_headless,
        raising=False,
    )

    result = migration_gate.run_live005_dsh_frontend_workflow(
        tmp_path,
        {"id": "LIVE-005"},
        config_env="PAPER_RAG_CONFIG",
        authorized_by="at",
        source_env=source_env,
    )

    assert "LIVE-005" in migration_gate.LIVE_CASE_RUNNERS
    assert result["status"] == "PASS"
    assert result["writes_to_formal_paper_library"] is False
    assert result["summary"]["tool_calls"][-1] == "paper_deliver"
    assert "artifact_delivery" in result["summary"]["cards"]
    assert prepare_resets == [False]
    assert captured["env"]["PAPER_RAG_MCP_TOOLSET"] == "research"
    assert captured["env"]["PAPER_RAG_DSH_HEADLESS_REPORT_JSON"] == "1"
    assert captured["env"]["PAPER_RAG_DSH_HEADLESS_SCRIPTED_WORKFLOW"] == "1"
    assert captured["env"]["PAPER_RAG_DSH_CREDENTIALS_PATH"].endswith(".credentials.yaml")
    assert captured["env"]["DSH_HOME"] == str(workspace.dsh_home)
    assert "test-secret" not in json.dumps(result)


def test_manifest_declares_live005_dsh_frontend_smoke():
    manifest = json.loads((SPEC / "test" / "test-manifest.json").read_text(encoding="utf-8"))

    live005 = next(
        (case for case in manifest["live_cases"] if case.get("id") == "LIVE-005"),
        None,
    )

    assert live005 is not None
    assert live005["gate"] == "G2"
    assert live005["runner"] == (
        ".venv/bin/python scripts/migration_gate.py run-live "
        "--case LIVE-005 --config-env PAPER_RAG_CONFIG"
    )
    assert live005["report"] == "data/index/migration-gates/live/LIVE-005.json"
    assert live005["requires_authorization"] is True
    assert "versioned durable DSH session" in live005["side_effects"]


def test_live005_headless_failure_includes_redacted_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    integration_root = tmp_path / "integrations/deepseek-harness"
    dsh_bin = integration_root / "node_modules/.bin/dsh"
    dsh_bin.parent.mkdir(parents=True)
    dsh_bin.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    dsh_bin.chmod(0o755)
    (integration_root / "live-headless.patch.yml").write_text("patch: true\n", encoding="utf-8")
    workspace = migration_gate.LiveG2Workspace(
        work_root=tmp_path / "work",
        data_root=tmp_path / "work/data",
        index_root=tmp_path / "work/data/index",
        artifact_root=tmp_path / "work/artifacts",
        import_root=tmp_path / "work/imports",
        dsh_home=tmp_path / "work/runtime/deepseek-harness/versions/0.1.0-rc.6/dsh-home",
        config_path=tmp_path / "work/config.live-g2.yaml",
        feedback_path=tmp_path / "work/data/index/feedback.sqlite",
    )
    monkeypatch.setattr(
        migration_gate,
        "_install_live_g2_dsh_headless_assets",
        lambda _repo_root, _workspace: None,
    )
    monkeypatch.setattr(
        migration_gate.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            stdout="",
            stderr="dsh: discovery_candidate_ingest failed: [Errno 61] Connection refused test-secret\n",
        ),
    )

    with pytest.raises(migration_gate.GateError) as excinfo:
        migration_gate._run_live005_headless_workflow(
            tmp_path,
            workspace,
            {"OPENAI_API_KEY": "test-secret"},
        )

    detail = str(excinfo.value)
    assert "exit=1" in detail
    assert "Connection refused" in detail
    assert "test-secret" not in detail
    assert "$OPENAI_API_KEY" in detail


def test_live_g2_env_adds_repo_src_to_import_path(tmp_path: Path):
    (tmp_path / "src").mkdir()
    env = {"PAPER_RAG_REPO_ROOT": str(tmp_path)}
    before = list(sys.path)

    with migration_gate._live_g2_env(env):
        assert sys.path[0] == str(tmp_path / "src")

    assert sys.path == before


def test_live002_workflow_initializes_qdrant_before_candidate_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace = migration_gate.LiveG2Workspace(
        work_root=tmp_path / "work",
        data_root=tmp_path / "work/data",
        index_root=tmp_path / "work/data/index",
        artifact_root=tmp_path / "work/artifacts",
        import_root=tmp_path / "work/imports",
        dsh_home=tmp_path / "work/runtime/deepseek-harness/versions/0.1.0-rc.6/dsh-home",
        config_path=tmp_path / "work/config.live-g2.yaml",
        feedback_path=tmp_path / "work/data/index/feedback.sqlite",
    )
    env = {"PAPER_RAG_REPO_ROOT": str(tmp_path)}
    ensure_calls = []
    tool_calls = []

    monkeypatch.setattr(migration_gate, "_reset_paper_rag_runtime", lambda: None)
    monkeypatch.setattr(
        migration_gate, "_live_g2_mcp_context", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(
        migration_gate,
        "_ensure_live_g2_qdrant_collections",
        lambda: ensure_calls.append("ensure"),
        raising=False,
    )

    def fake_mcp_call(name, args, ctx):
        del args, ctx
        tool_calls.append(name)
        if name == "paper_discover":
            return {
                "structuredContent": {
                    "ok": True,
                    "tool": name,
                    "data": {
                        "candidates": [
                            {
                                "id": 11,
                                "selected": True,
                                "paper_id": "arxiv:2601.00001",
                                "title": "Candidate",
                            }
                        ]
                    },
                }
            }
        if name == "discovery_candidate_ingest":
            return {
                "structuredContent": {
                    "ok": True,
                    "tool": name,
                    "data": {
                        "results": [
                            {
                                "paper_id": "arxiv:2601.00001",
                                "status": "ingested",
                            }
                        ]
                    },
                }
            }
        return {
            "structuredContent": {
                "ok": True,
                "tool": name,
                "trace_id": "trace-1",
                "data": {
                    "citations": ["chunk-1"],
                    "chunks": [{"chunk_id": "chunk-1"}],
                },
            }
        }

    monkeypatch.setattr(migration_gate, "_mcp_call", fake_mcp_call)

    result = migration_gate._run_live002_workflow(tmp_path, workspace, env)

    assert result["checks"][-2]["id"] == "qa-citations"
    assert ensure_calls == ["ensure"]
    assert tool_calls == ["paper_discover", "discovery_candidate_ingest", "paper_qa"]


def test_live_g2_artifact_validation_allows_zero_citations_when_file_opens(tmp_path: Path):
    artifact_root = tmp_path / "work/artifacts"
    artifact_dir = artifact_root / "artifact-1"
    artifact_dir.mkdir(parents=True)
    pptx_path = artifact_dir / "deck.pptx"
    with zipfile.ZipFile(pptx_path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
    manifest_path = artifact_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": str(pptx_path),
                        "size_bytes": pptx_path.stat().st_size,
                        "sha256": "0" * 64,
                    }
                ],
                "metadata": {"deliver": {"n_citations": 0}},
            }
        ),
        encoding="utf-8",
    )
    workspace = migration_gate.LiveG2Workspace(
        work_root=tmp_path / "work",
        data_root=tmp_path / "work/data",
        index_root=tmp_path / "work/data/index",
        artifact_root=artifact_root,
        import_root=tmp_path / "work/imports",
        dsh_home=tmp_path / "work/runtime/deepseek-harness/versions/0.1.0-rc.6/dsh-home",
        config_path=tmp_path / "work/config.live-g2.yaml",
        feedback_path=tmp_path / "work/data/index/feedback.sqlite",
    )

    summary, checks = migration_gate._validate_live_g2_artifact(
        {
            "data": {
                "artifact": {
                    "artifact_id": "artifact-1",
                    "manifest_path": str(manifest_path),
                }
            }
        },
        workspace,
        "pptx",
    )

    assert summary["n_citations"] == 0
    assert {check["id"]: check["status"] for check in checks} == {
        "deliver-pptx-under-artifact-root": "PASS",
        "deliver-pptx-opens": "PASS",
    }


def test_live004_followup_accepts_explicit_no_evidence_abstain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace = migration_gate.LiveG2Workspace(
        work_root=tmp_path / "work",
        data_root=tmp_path / "work/data",
        index_root=tmp_path / "work/data/index",
        artifact_root=tmp_path / "work/artifacts",
        import_root=tmp_path / "work/imports",
        dsh_home=tmp_path / "work/runtime/deepseek-harness/versions/0.1.0-rc.6/dsh-home",
        config_path=tmp_path / "work/config.live-g2.yaml",
        feedback_path=tmp_path / "work/data/index/feedback.sqlite",
    )
    workspace.dsh_home.mkdir(parents=True)
    calls: list[str] = []

    monkeypatch.setattr(migration_gate, "_live_g2_mcp_context", lambda *args, **kwargs: object())
    monkeypatch.setattr(migration_gate, "_dsh_version", lambda repo_root: "0.1.0-rc.6")

    from paper_rag.rag import conversation_turn_store

    monkeypatch.setattr(
        conversation_turn_store,
        "recent_turns",
        lambda **kwargs: [{"turn": 1}, {"turn": 2}],
    )

    def fake_mcp_call(name, args, ctx):
        del ctx
        assert name == "paper_qa"
        calls.append(args["question"])
        if len(calls) == 1:
            return {
                "structuredContent": {
                    "ok": True,
                    "tool": "paper_qa",
                    "trace_id": "trace-1",
                    "data": {
                        "answer": "Cited answer",
                        "citations": ["chunk-1"],
                        "abstain": {"decision": "answer"},
                    },
                }
            }
        return {
            "structuredContent": {
                "ok": True,
                "tool": "paper_qa",
                "trace_id": "trace-2",
                "data": {
                    "answer": "No indexed evidence supports this follow-up.",
                    "citations": [],
                    "abstain": {"decision": "no_evidence"},
                },
            }
        }

    monkeypatch.setattr(migration_gate, "_mcp_call", fake_mcp_call)

    result = migration_gate._run_live004_workflow(tmp_path, workspace, {}, "paper-1")

    checks = {check["id"]: check for check in result["checks"]}
    assert checks["followup-turn-1-evidence"]["status"] == "PASS"
    assert checks["followup-turn-2-evidence"]["status"] == "PASS"
    assert "abstain=no_evidence" in checks["followup-turn-2-evidence"]["detail"]
    assert result["turns"][1]["abstain_decision"] == "no_evidence"
    assert "paper-rag-session-proofs" in result["session_proof"]
    assert "Cite indexed chunks" in calls[0]
    assert "weak/no-evidence abstain" in calls[1]


def test_live001_summary_requires_paper_qa_citation_and_abstain():
    events = [
        {
            "type": "request/header",
            "data": {"config": {"provider": "deepseek-official", "model": "deepseek-v4-flash"}},
        },
        {
            "type": "tool/call",
            "data": {
                "name": "paper_qa",
                "arguments": json.dumps(
                    {"question": migration_gate.LIVE001_POSITIVE_QUESTION}
                ),
            },
        },
        {
            "type": "tool/result",
            "data": {
                "message": {
                    "content": [
                        {
                            "type": "tool-result",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "ok=true tool=paper_qa citations=563088608864d1932716",
                                }
                            ],
                        }
                    ]
                }
            },
        },
        {
            "type": "tool/call",
            "data": {
                "name": "paper_qa",
                "arguments": json.dumps(
                    {"question": migration_gate.LIVE001_NEGATIVE_QUESTION}
                ),
            },
        },
        {
            "type": "tool/result",
            "data": {
                "message": {
                    "content": [
                        {
                            "type": "tool-result",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "ok=true tool=paper_qa abstain=no_evidence citations=",
                                }
                            ],
                        }
                    ]
                }
            },
        },
        {
            "type": "assistant/message",
            "data": {
                "message": {
                    "content": [{"type": "text", "text": "LIVE-001 complete"}],
                    "source": {"provider": "deepseek-official", "model": "deepseek-v4-flash"},
                }
            },
        },
    ]

    summary = migration_gate.summarize_live001_events(events, stdout="", stderr="")

    assert summary["dsh_model"] == "deepseek-v4-flash"
    assert summary["metrics"] == {
        "tool_calls": 2,
        "paper_qa_calls": 2,
        "citation_checks_passed": 1,
        "abstain_checks_passed": 1,
    }
    assert all(check["status"] == "PASS" for check in summary["checks"])

    broken = [
        event
        for event in events
        if event.get("type") != "tool/result"
        or "abstain=no_evidence" not in json.dumps(event)
    ]
    broken_summary = migration_gate.summarize_live001_events(broken, stdout="", stderr="")

    assert broken_summary["metrics"]["abstain_checks_passed"] == 0
    assert any(
        check["id"] == "no-evidence-abstain" and check["status"] == "FAIL"
        for check in broken_summary["checks"]
    )


def test_quality_gate_make_targets_use_migration_python():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    for target in [
        "eval-golden",
        "eval-golden-qa",
        "eval-citation-audit",
        "eval-claims",
        "eval-claims-report",
        "eval-claims-judge",
        "eval-llm-recall",
        "verify-p0",
    ]:
        body = migration_gate.extract_make_target_body(makefile, target)
        assert "DEERFLOW_BACKEND_PY" not in body
        assert "$(PY)" in body


def test_g0_manifest_citation_audit_writes_to_gate_artifact_dir():
    manifest = json.loads((SPEC / "test" / "test-manifest.json").read_text(encoding="utf-8"))
    command_by_id = {command["id"]: command["command"] for command in manifest["owned_test_commands"]}

    command = command_by_id["eval-citation-audit"]

    assert "EVAL_CITATION_AUDIT_MD=data/index/migration-gates/" in command
    assert "docs/RAG_CITATION_AUDIT.md" not in command


def test_dsh_package_uses_exact_compatible_versions():
    result = migration_gate.validate_dsh_package(
        ROOT / "integrations" / "deepseek-harness" / "package.json",
        expected_dsh_version="0.1.0-rc.6",
        expected_cordis_version="4.0.1",
    )

    assert result["dsh_version"] == "0.1.0-rc.6"
    assert result["cordis_version"] == "4.0.1"
    assert "@deepseek-ai/dsh-tool-call-timeout-policy" in result["dsh_packages"]
    assert result["pinned"] is True


def test_dsh_lockfile_resolves_single_cordis_and_dsh_version():
    result = migration_gate.validate_dsh_lockfile(
        ROOT / "integrations" / "deepseek-harness" / "pnpm-lock.yaml",
        expected_dsh_version="0.1.0-rc.6",
        expected_cordis_version="4.0.1",
    )

    assert result["cordis_versions"] == ["4.0.1"]
    assert result["dsh_versions"] == ["0.1.0-rc.6"]
    assert result["dsh_package_count"] >= 100
