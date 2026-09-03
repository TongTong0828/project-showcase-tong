"""MinerU local CLI wrapper.

Adapted to magic-pdf's actual output layout:

    out_dir/
        <pdf_basename>/
            auto/
                <pdf_basename>.md         <-- main markdown
                <pdf_basename>_layout.pdf
                <pdf_basename>_origin.pdf
                <pdf_basename>_content_list.json
                <pdf_basename>_middle.json
                images/                    <-- figures
                ...

We normalize this into:

    parsed_dir/
        paper.md          (rewritten image paths)
        layout.json       (alias for content_list / middle)
        figures/          (copied from images/)
        tables/           (best-effort)

If anything goes wrong (no .md, empty output, timeout) raises MineruError so
the caller can fall back to pymupdf.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from .. import config as cfg
from ..utils.logger import get_logger
from ..utils.paths import parsed_dir

log = get_logger("parse.mineru")


def _runtime_cache_dir() -> Path:
    return Path(cfg.load().paths.index_dir) / "runtime_cache"


def _ensure_runtime_env(env: dict[str, str] | None = None) -> dict[str, str]:
    out = env if env is not None else os.environ
    cache_dir = _runtime_cache_dir()
    out.setdefault("MPLCONFIGDIR", str(cache_dir / "matplotlib"))
    out.setdefault("YOLO_CONFIG_DIR", str(cache_dir / "ultralytics"))
    out.setdefault("XDG_CACHE_HOME", str(cache_dir / "xdg"))
    for key in ("MPLCONFIGDIR", "YOLO_CONFIG_DIR", "XDG_CACHE_HOME"):
        Path(out[key]).mkdir(parents=True, exist_ok=True)
    return out


class MineruError(RuntimeError):
    pass


@dataclass
class MineruCheck:
    name: str
    ok: bool
    detail: str
    hint: str = ""


@dataclass
class MineruDoctorReport:
    ok: bool
    cli_path: str | None
    config_path: str
    checks: list[MineruCheck]

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["checks"] = [asdict(check) for check in self.checks]
        return out


def _mineru_config_path() -> Path:
    return (cfg.PROJECT_ROOT / "config" / "magic-pdf.json").resolve()


def _resolve_cli(cli_name: str | None = None) -> str | None:
    """Resolve MinerU/magic-pdf CLI from PATH or the active Python env."""
    name = cli_name or cfg.load().mineru.cli
    cli = shutil.which(name)
    if cli is not None:
        return cli
    for candidate in (
        Path(sys.executable).parent / name,
        Path(sys.prefix) / "bin" / name,
    ):
        if candidate.exists():
            return str(candidate)
    return None


def diagnose() -> MineruDoctorReport:
    """Check whether the local MinerU runtime is ready before ingest."""
    c = cfg.load()
    _ensure_runtime_env()
    config_path = _mineru_config_path()
    checks: list[MineruCheck] = []

    cli = _resolve_cli(c.mineru.cli)
    checks.append(
        MineruCheck(
            name="cli",
            ok=cli is not None,
            detail=cli or f"{c.mineru.cli} not found",
            hint=f"Install MinerU with `{sys.executable} -m pip install -e '.[mineru]'`.",
        )
    )
    checks.append(_import_check("magic_pdf", "magic_pdf", "Install `magic-pdf`."))
    checks.extend(_full_extra_checks())
    checks.append(
        _import_check(
            "cv2",
            "cv2",
            "Install `opencv-python-headless`; MinerU imports cv2 during parsing.",
        )
    )
    checks.append(
        MineruCheck(
            name="magic-pdf config",
            ok=config_path.exists(),
            detail=str(config_path),
            hint="Create config/magic-pdf.json or set MINERU_TOOLS_CONFIG_JSON.",
        )
    )
    checks.extend(_model_dir_checks(config_path))
    checks.extend(_enabled_model_weight_checks(config_path))
    if cli:
        checks.append(_cli_version_check(cli))

    return MineruDoctorReport(
        ok=all(check.ok for check in checks),
        cli_path=cli,
        config_path=str(config_path),
        checks=checks,
    )


def _import_check(name: str, module: str, hint: str) -> MineruCheck:
    try:
        imported = import_module(module)
        version = getattr(imported, "__version__", "")
        detail = f"import ok{f' ({version})' if version else ''}"
        return MineruCheck(name=name, ok=True, detail=detail)
    except Exception as exc:
        return MineruCheck(name=name, ok=False, detail=f"{type(exc).__name__}: {exc}", hint=hint)


def _full_extra_checks() -> list[MineruCheck]:
    hint = f"Install the full MinerU extra: {sys.executable} -m pip install -e '.[mineru]'"
    return [
        _import_check("magic-pdf[full]: doclayout_yolo", "doclayout_yolo", hint),
        _import_check("magic-pdf[full]: ultralytics", "ultralytics", hint),
        _import_check("magic-pdf[full]: rapid_table", "rapid_table", hint),
        _import_check("magic-pdf[full]: pyclipper", "pyclipper", hint),
        _import_check("magic-pdf[full]: shapely", "shapely", hint),
    ]


def _model_dir_checks(config_path: Path) -> list[MineruCheck]:
    if not config_path.exists():
        return []
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [
            MineruCheck(
                name="models-dir",
                ok=False,
                detail=f"cannot parse {config_path}: {type(exc).__name__}: {exc}",
            )
        ]
    raw_models_dir = payload.get("models-dir") or ""
    models_dir = Path(raw_models_dir)
    if raw_models_dir and not models_dir.is_absolute():
        models_dir = (cfg.PROJECT_ROOT / models_dir).resolve()
    exists = models_dir.exists()
    has_files = any(path.is_file() for path in models_dir.rglob("*")) if exists and models_dir.is_dir() else False
    return [
        MineruCheck(
            name="models-dir",
            ok=exists,
            detail=str(models_dir) if raw_models_dir else "not configured",
            hint="Run MinerU's model download/setup step or point models-dir at cached weights.",
        ),
        MineruCheck(
            name="models-dir nonempty",
            ok=has_files,
            detail=str(models_dir) if exists else "models-dir missing",
            hint="MinerU may download/use OCR/layout models here; keep this directory populated.",
        ),
    ]


def _enabled_model_weight_checks(config_path: Path) -> list[MineruCheck]:
    if not config_path.exists():
        return []
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        weights = _mineru_weight_map()
    except Exception as exc:
        return [
            MineruCheck(
                name="enabled model weights",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                hint="Check magic-pdf.json and magic_pdf resource files.",
            )
        ]

    models_dir = Path(payload.get("models-dir") or "/tmp/models")
    if not models_dir.is_absolute():
        models_dir = (cfg.PROJECT_ROOT / models_dir).resolve()

    expected: list[tuple[str, Path]] = []
    layout_model = (payload.get("layout-config") or {}).get("model", "layoutlmv3")
    if layout_model in weights:
        expected.append((f"layout:{layout_model}", models_dir / weights[layout_model]))

    formula_config = payload.get("formula-config") or {}
    if formula_config.get("enable", True):
        for key in ("mfd_model", "mfr_model"):
            model_name = formula_config.get(key)
            if model_name in weights:
                expected.append((f"formula:{model_name}", models_dir / weights[model_name]))

    table_config = payload.get("table-config") or {}
    if table_config.get("enable", False):
        model_name = table_config.get("model")
        if model_name in weights:
            expected.append((f"table:{model_name}", models_dir / weights[model_name]))

    checks: list[MineruCheck] = []
    for name, path in expected:
        checks.append(
            MineruCheck(
                name=f"model weight {name}",
                ok=path.exists(),
                detail=str(path),
                hint="Download MinerU model weights and keep the directory layout from model_configs.yaml.",
            )
        )
    return checks


def _mineru_weight_map() -> dict[str, str]:
    import yaml

    magic_pdf = import_module("magic_pdf")
    root = Path(magic_pdf.__file__).resolve().parent
    config_path = root / "resources" / "model_config" / "model_configs.yaml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return dict(payload.get("weights") or {})


def _cli_version_check(cli: str) -> MineruCheck:
    try:
        proc = subprocess.run(
            [cli, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return MineruCheck(name="cli version", ok=False, detail=f"{type(exc).__name__}: {exc}")
    output = (proc.stdout or proc.stderr).strip()
    return MineruCheck(
        name="cli version",
        ok=proc.returncode == 0,
        detail=output or f"rc={proc.returncode}",
    )


def classify_failure(detail: str) -> tuple[str, str]:
    """Return (reason, hint) for common MinerU failures."""
    lower = detail.lower()
    if "no module named 'cv2'" in lower or "no module named cv2" in lower:
        return (
            "missing_cv2",
            f"Install MinerU dependencies in this venv: {sys.executable} -m pip install -e '.[mineru]'",
        )
    for module in ("doclayout_yolo", "ultralytics", "rapid_table", "pyclipper", "shapely"):
        if f"no module named '{module}'" in lower or f"no module named {module}" in lower:
            return (
                "missing_mineru_full_extra",
                f"Install MinerU full dependencies: {sys.executable} -m pip install -e '.[mineru]'",
            )
    if "no such file or directory" in lower and ("magic-pdf" in lower or "mineru" in lower):
        return ("missing_cli", "Install magic-pdf or set mineru.cli in config.")
    if (
        "missing_models_or_offline" in lower
        or (
        ("api.github.com" in lower or "github.com" in lower or "huggingface.co" in lower)
        and (
            "failed to resolve" in lower
            or "connectionerror" in lower
            or "max retries" in lower
            or "environment is not online" in lower
        )
        )
    ):
        return (
            "missing_models_or_offline",
            "MinerU attempted to download model weights but network/DNS is unavailable. "
            "Download weights in a network-enabled terminal and place them under data/index/mineru_models.",
        )
    if "model" in lower and ("not found" in lower or "no such file" in lower or "download" in lower):
        return (
            "missing_models",
            "Populate config/magic-pdf.json models-dir or run MinerU's model download/setup step.",
        )
    return ("unknown", "")


def parse_pdf(paper_id: str, pdf_path: str | Path) -> Path:
    """Run MinerU on `pdf_path`, return the normalized parsed_dir.

    Raises MineruError on timeout / non-zero exit / empty output.
    """
    c = cfg.load()
    pdf_path = Path(pdf_path).resolve()
    out_dir = parsed_dir(paper_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_out_dir = out_dir / "_mineru_raw"
    if raw_out_dir.exists():
        shutil.rmtree(raw_out_dir)
    raw_out_dir.mkdir(parents=True, exist_ok=True)

    cli = _resolve_cli(c.mineru.cli)
    if cli is None:
        raise MineruError(
            f"MinerU CLI '{c.mineru.cli}' not found on PATH. "
            f"Install via `{sys.executable} -m pip install -e '.[mineru]'` "
            "or set mineru.cli in config."
        )

    method = getattr(c.mineru, "method", "auto") or "auto"
    cmd = [cli, "-p", str(pdf_path), "-o", str(raw_out_dir), "-m", method]
    lang = getattr(c.mineru, "lang", None)
    if lang:
        cmd.extend(["-l", lang])
    env = _ensure_runtime_env(os.environ.copy())
    env.setdefault("MINERU_TOOLS_CONFIG_JSON", str(_mineru_config_path()))
    log.info(f"mineru exec: {' '.join(cmd)} (timeout={c.mineru.timeout_sec}s)")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=c.mineru.timeout_sec,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise MineruError(f"mineru timeout after {c.mineru.timeout_sec}s") from e
    if proc.returncode != 0:
        detail = "\n".join(x for x in (proc.stdout[-1000:], proc.stderr[-2000:]) if x)
        reason, hint = classify_failure(detail)
        raise MineruError(
            f"mineru failed (rc={proc.returncode}, reason={reason}): {detail}"
            + (f"\nHint: {hint}" if hint else "")
        )

    md_path, mineru_assets_dir = _locate_outputs(raw_out_dir)
    if md_path is None or not md_path.exists() or md_path.stat().st_size == 0:
        detail = "\n".join(x for x in (proc.stdout[-1000:], proc.stderr[-1000:]) if x)
        reason, hint = classify_failure(detail)
        raise MineruError(
            f"mineru produced no markdown under {raw_out_dir} (reason={reason}): {detail}"
            + (f"\nHint: {hint}" if hint else "")
        )

    _normalize_into(out_dir, md_path, mineru_assets_dir)
    log.info(f"mineru ok -> {out_dir}")
    return out_dir


def _locate_outputs(out_dir: Path) -> tuple[Path | None, Path | None]:
    """Find (main_md, assets_dir).

    magic-pdf typical layout: <out>/<basename>/auto/<basename>.md and ../images/.
    Some versions put files at <out>/<basename>.md directly.
    """
    candidates = [
        p for p in out_dir.rglob("*.md")
        if p.name != "paper.md" and "_mineru_raw" in p.parts
    ]
    if not candidates:
        candidates = list(out_dir.rglob("*.md"))
    if not candidates:
        return None, None
    candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
    md = candidates[0]

    assets = md.parent / "images"
    if not assets.is_dir():
        for sibling in md.parent.iterdir():
            if sibling.is_dir() and sibling.name.lower() in {"images", "figures", "assets"}:
                assets = sibling
                break
    return md, assets if assets.is_dir() else None


_IMAGE_REF_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _normalize_into(out_dir: Path, src_md: Path, mineru_assets: Path | None) -> None:
    """Copy figures into out_dir/figures/ and rewrite image paths in paper.md."""
    figures_dir = out_dir / "figures"
    if figures_dir.exists():
        shutil.rmtree(figures_dir)
    figures_dir.mkdir(parents=True, exist_ok=True)

    asset_map: dict[str, str] = {}
    if mineru_assets and mineru_assets.is_dir():
        for f in mineru_assets.iterdir():
            if not f.is_file():
                continue
            target = figures_dir / f.name
            if not target.exists():
                shutil.copy2(f, target)
            asset_map[f.name] = f"figures/{f.name}"

    md = src_md.read_text(encoding="utf-8", errors="replace").replace("\x00", "")

    def _rewrite(match: re.Match) -> str:
        alt, path = match.group(1), match.group(2)
        basename = Path(path).name
        new_path = asset_map.get(basename, path)
        return f"![{alt}]({new_path})"

    md = _IMAGE_REF_RE.sub(_rewrite, md)
    (out_dir / "paper.md").write_text(md, encoding="utf-8")

    # Mirror layout/content_list as layout.json if present.
    for cand in [*src_md.parent.glob("*content_list*.json"), *src_md.parent.glob("*middle*.json")]:
        try:
            (out_dir / "layout.json").write_text(
                json.dumps(json.loads(cand.read_text(encoding="utf-8")),
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            break
        except Exception as e:
            log.debug("mineru layout candidate %s failed: %s", cand.name, e)
            continue
