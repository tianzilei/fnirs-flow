"""Sync a code-only public release tree from the working repository.

The script copies a conservative whitelist of source files into a sibling
``fnirs-flow-public`` directory by default. It intentionally omits manuscript
drafts, literature extraction materials, outputs, sample data, reference repos,
tool caches, and platform metadata files.

Usage:

    python scripts/sync_public_release.py --dry-run
    python scripts/sync_public_release.py --clean
    python scripts/sync_public_release.py --target ../fnirs-flow-public --clean --init-git
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT_FILES = [
    ".gitignore",
    "CHANGELOG.md",
    "PUBLIC_SYNC_SPEC.md",
    "README.md",
    "ai_flow_generation_guide.md",
    "cli.py",
    "environment.yml",
    "pyproject.toml",
    "LICENSE",
    "LICENSE.md",
    "THIRD_PARTY_NOTICES.md",
]

REQUIRED_ROOT_FILES = [
    "README.md",
    "pyproject.toml",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
]

DIRS = [
    "config",
    "configs",
    "fnirs_flow",
    "schemas",
    "tests",
]

WEBUI_FILES = [
    "webui/index.html",
    "webui/package.json",
    "webui/package-lock.json",
    "webui/playwright.config.ts",
    "webui/tsconfig.json",
    "webui/tsconfig.node.json",
    "webui/vite.config.ts",
]

WEBUI_DIRS = [
    "webui/e2e",
    "webui/src",
]

PUBLIC_DOC_FILES = [
    "docs/README.md",
    "docs/specs/fnirs_flow_public_api.md",
    "docs/specs/package_profile_spec.md",
    "docs/specs/mvp_task_glm_acceptance_checklist.md",
]

# These scripts are part of the public test/runtime contract.  Keep this list
# explicit so private analysis and manuscript automation are not copied by
# broadening the whitelist to the entire scripts directory.
PUBLIC_SCRIPT_FILES = [
    "scripts/analyze_ds007738_qc_sensitivity.py",
    "scripts/audit_ds007738_outputs.py",
    "scripts/benchmark_performance.py",
    "scripts/build_ds007738_exclusion_manifests.py",
    "scripts/compare_ds007738_golden_rerun.py",
    "scripts/run_ds007738_full_analysis.py",
    "scripts/sync_public_release.py",
]

EXCLUDED_NAMES = {
    ".DS_Store",
    ".AppleDouble",
    ".LSOverride",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "__MACOSX",
}

EXCLUDED_PREFIXES = (
    "._",
    ".__",
)

EXCLUDED_SUFFIXES = (
    ".bak",
    ".log",
    ".pyc",
    ".pyo",
    ".tmp",
    ".swp",
    ".swo",
)

# The public repository owns these paths. A clean sync must preserve them
# instead of replacing release-specific Git attributes or CI configuration.
PRESERVED_TARGET_NAMES = {
    ".git",
    ".gitattributes",
    ".github",
}

FORBIDDEN_PUBLIC_PATHS = (
    ".agents",
    ".mimocode",
    ".tmp",
    "References",
    "Sample",
    "audit",
    "docs/literature",
    "docs/manuscript",
    "legacy",
    "outputs",
)

PUBLIC_RELEASE_README = """# Public Release Tree

This directory was generated from the private working repository by
`scripts/sync_public_release.py`.

It contains only the code-oriented public release whitelist for the
submission/public repository:

- Python packages and CLI
- JSON schemas and demo configs
- tests
- WebUI source and package metadata
- selected public docs/specs
- license and third-party notice files

It intentionally excludes manuscript drafts, literature extraction materials,
sample data, generated outputs, reference repositories, caches, and local
platform metadata. The submission manuscript package is handled separately and
is not copied by this script.
"""

PUBLIC_RELEASE_MANIFEST = "PUBLIC_RELEASE_MANIFEST.json"


@dataclass(frozen=True)
class CopyItem:
    source: Path
    target: Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_target(root: Path) -> Path:
    return root.parent / "fnirs-flow-public"


def is_excluded(path: Path) -> bool:
    return (
        path.name in EXCLUDED_NAMES or path.name.startswith(EXCLUDED_PREFIXES) or path.name.endswith(EXCLUDED_SUFFIXES)
    )


def is_forbidden_public_rel(rel: Path) -> bool:
    normalized = rel.as_posix()
    return any(normalized == blocked or normalized.startswith(f"{blocked}/") for blocked in FORBIDDEN_PUBLIC_PATHS)


def rel_to_target(path: Path, target: Path) -> Path:
    try:
        return path.relative_to(target)
    except ValueError as exc:
        raise SystemExit(f"Refusing to write outside target directory: {path}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def iter_files(root: Path, rel_dir: str) -> list[Path]:
    base = root / rel_dir
    if not base.exists():
        return []

    files: list[Path] = []
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            continue
        repo_rel = path.relative_to(root)
        if is_forbidden_public_rel(repo_rel):
            continue
        if any(is_excluded(part) for part in path.relative_to(base).parents):
            continue
        if is_excluded(path):
            continue
        if path.is_file():
            files.append(path)
    return files


def build_copy_plan(root: Path, target: Path) -> list[CopyItem]:
    plan: list[CopyItem] = []

    for rel in ROOT_FILES + WEBUI_FILES + PUBLIC_DOC_FILES + PUBLIC_SCRIPT_FILES:
        source = root / rel
        if is_forbidden_public_rel(Path(rel)):
            continue
        if source.exists() and source.is_file() and not is_excluded(source):
            plan.append(CopyItem(source=source, target=target / rel))

    for rel_dir in DIRS + WEBUI_DIRS:
        if is_forbidden_public_rel(Path(rel_dir)):
            continue
        for source in iter_files(root, rel_dir):
            rel = source.relative_to(root)
            plan.append(CopyItem(source=source, target=target / rel))

    return sorted(plan, key=lambda item: str(item.target))


def validate_required_sources(root: Path, dry_run: bool) -> None:
    missing = [rel for rel in REQUIRED_ROOT_FILES if not (root / rel).is_file()]
    if not missing:
        return

    message = "Missing required public release file(s): " + ", ".join(missing)
    if dry_run:
        print(f"warning: {message}")
        return
    raise SystemExit(message)


def validate_plan(plan: list[CopyItem], target: Path) -> None:
    blocked: list[str] = []
    seen_targets: set[str] = set()
    duplicates: list[str] = []
    for item in plan:
        rel = rel_to_target(item.target, target)
        normalized = rel.as_posix()
        key = normalized.lower()
        if key in seen_targets:
            duplicates.append(normalized)
        seen_targets.add(key)
        if is_forbidden_public_rel(rel):
            blocked.append(normalized)
        if item.source.is_symlink():
            blocked.append(f"{normalized} (symlink source)")

    if blocked:
        sample = ", ".join(sorted(blocked)[:10])
        raise SystemExit(f"Refusing to copy forbidden public path(s): {sample}")
    if duplicates:
        sample = ", ".join(sorted(duplicates)[:10])
        raise SystemExit(f"Refusing to copy duplicate target path(s): {sample}")


def audit_target(target: Path, dry_run: bool) -> None:
    if dry_run or not target.exists():
        return

    blocked: list[str] = []
    for blocked_rel in FORBIDDEN_PUBLIC_PATHS:
        path = target / blocked_rel
        if path.exists():
            blocked.append(blocked_rel)

    if blocked:
        sample = ", ".join(sorted(blocked))
        raise SystemExit(
            "Forbidden path(s) exist in the public release target: "
            f"{sample}. Re-run with --clean or remove them from the target repository."
        )


def clean_target(target: Path, dry_run: bool) -> None:
    if not target.exists():
        return

    for child in sorted(target.iterdir()):
        if child.name in PRESERVED_TARGET_NAMES:
            continue
        if dry_run:
            print(f"would remove {child}")
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def copy_items(plan: list[CopyItem], dry_run: bool) -> None:
    for item in plan:
        if dry_run:
            print(f"would copy {item.source} -> {item.target}")
            continue
        item.target.parent.mkdir(parents=True, exist_ok=True)
        # Copy content without inheriting filesystem-specific executable bits.
        # The private working tree can live on a volume that reports every file
        # as executable; propagating that metadata creates noisy public diffs.
        shutil.copyfile(item.source, item.target)


def init_git(target: Path, dry_run: bool) -> None:
    git_dir = target / ".git"
    if git_dir.exists():
        print(f"git already initialized: {target}")
        return
    if dry_run:
        print(f"would initialize git repository in {target}")
        return
    subprocess.run(["git", "init"], cwd=target, check=True)


def write_release_readme(target: Path, dry_run: bool) -> None:
    path = target / "PUBLIC_RELEASE.md"
    if dry_run:
        print(f"would write {path}")
        return
    path.write_text(PUBLIC_RELEASE_README, encoding="utf-8")


def build_manifest(root: Path, target: Path, plan: list[CopyItem]) -> dict[str, object]:
    files = []
    for item in plan:
        rel = rel_to_target(item.target, target).as_posix()
        files.append(
            {
                "path": rel,
                "source": item.source.relative_to(root).as_posix(),
                "bytes": item.source.stat().st_size,
                "sha256": sha256_file(item.source),
            }
        )

    return {
        "schema_version": 1,
        "source_root_name": root.name,
        "target_root_name": target.name,
        "copied_file_count": len(files),
        "forbidden_public_paths": list(FORBIDDEN_PUBLIC_PATHS),
        "generated_files": [
            {
                "path": "PUBLIC_RELEASE.md",
                "bytes": len(PUBLIC_RELEASE_README.encode("utf-8")),
                "sha256": sha256_text(PUBLIC_RELEASE_README),
            }
        ],
        "files": files,
    }


def write_manifest(root: Path, target: Path, plan: list[CopyItem], dry_run: bool) -> None:
    path = target / PUBLIC_RELEASE_MANIFEST
    if dry_run:
        print(f"would write {path}")
        return

    manifest = build_manifest(root, target, plan)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(description="Sync a code-only public release tree for GitHub publication.")
    parser.add_argument(
        "--target",
        type=Path,
        default=default_target(root),
        help="Target directory. Default: sibling fnirs-flow-public directory.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove target contents before copying, preserving target .git.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without writing files.",
    )
    parser.add_argument(
        "--init-git",
        action="store_true",
        help="Run git init in the target directory if it is not already a repo.",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Do not write PUBLIC_RELEASE_MANIFEST.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repo_root()
    target = args.target.resolve()

    if target == root or root in target.parents:
        raise SystemExit(
            "Refusing to sync into the source repository or one of its subdirectories. "
            "Use a sibling directory such as ../fnirs-flow-public."
        )
    if target in root.parents:
        raise SystemExit(
            "Refusing to sync into an ancestor of the source repository. "
            "Use a dedicated sibling directory such as ../fnirs-flow-public."
        )

    validate_required_sources(root, args.dry_run)
    plan = build_copy_plan(root, target)
    validate_plan(plan, target)
    print(f"Source: {root}")
    print(f"Target: {target}")
    print(f"Files selected: {len(plan)}")

    if not args.clean:
        audit_target(target, args.dry_run)

    if args.clean:
        clean_target(target, args.dry_run)

    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)

    copy_items(plan, args.dry_run)
    write_release_readme(target, args.dry_run)
    if not args.no_manifest:
        write_manifest(root, target, plan, args.dry_run)
    audit_target(target, args.dry_run)

    if args.init_git:
        init_git(target, args.dry_run)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
