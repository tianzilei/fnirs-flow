"""Editable single-file project bundles with managed working directories."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from fnirs_flow.api.portability import find_absolute_path_records, is_trackable_bundle_path

logger = logging.getLogger(__name__)


BUNDLE_SUFFIX = ".fnirsflow"
BUNDLE_MANIFEST = "bundle_manifest.json"
BUNDLE_SCHEMA_VERSION = "1.1.0"
SUPPORTED_BUNDLE_SCHEMA_VERSIONS = {"1.0.0", BUNDLE_SCHEMA_VERSION}
MAX_BUNDLE_FILES = 5_000
MAX_BUNDLE_BYTES = 10 * 1024**2
MAX_BUNDLE_UNCOMPRESSED_BYTES = MAX_BUNDLE_BYTES
MAX_BUNDLE_MANIFEST_BYTES = 1024**2
MAX_PROJECT_METADATA_BYTES = 1024**2
MAX_MEMBER_BYTES = 8 * 1024**2  # single file must not exceed 8 MiB
MAX_COMPRESSION_RATIO = 1000  # reject zip-bomb-like ratios


class ProjectBundleError(ValueError):
    """Raised when an editable project bundle is corrupt or unsafe."""


class ProjectBundleManager:
    """Own canonical bundles and their hidden, disposable working copies."""

    def __init__(self, base_dir: Path, *, retained_versions: int = 10) -> None:
        self.base_dir = Path(base_dir)
        self.workspace_root = self.base_dir / ".workspaces"
        self.version_root = self.base_dir / ".versions"
        self.temp_root = self.base_dir / ".tmp"
        self.retained_versions = retained_versions
        for directory in (self.base_dir, self.workspace_root, self.version_root, self.temp_root):
            directory.mkdir(parents=True, exist_ok=True)

    def bundle_path(self, project_id: str) -> Path:
        return self.base_dir / f"{project_id}{BUNDLE_SUFFIX}"

    def workspace_path(self, project_id: str) -> Path:
        return self.workspace_root / project_id

    def migrate_legacy_directories(self) -> list[str]:
        """Move legacy visible project folders into managed workspaces and bundle them.

        Uses staging to ensure atomicity: the original directory is only removed
        after the bundle is successfully created.
        """
        migrated: list[str] = []
        staging_root = self.base_dir / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)

        for candidate in sorted(self.base_dir.iterdir()):
            if not candidate.is_dir() or candidate.name.startswith("."):
                continue
            if not (candidate / "project.json").is_file():
                continue
            project_id = candidate.name
            workspace = self.workspace_path(project_id)
            if workspace.exists():
                continue

            # Use staging for atomic migration
            staging = staging_root / f"{project_id}-migration"
            try:
                shutil.copytree(candidate, staging, dirs_exist_ok=True)
                self.save_from_staging(
                    project_id, staging, reason="legacy_folder_migration", keep_previous=False
                )
                # Bundle created successfully — remove original
                shutil.rmtree(candidate)
                migrated.append(project_id)
            except Exception:
                # Migration failed — original is untouched
                logger.warning("Migration failed for legacy project '%s'", project_id, exc_info=True)
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)

        return migrated

    def read_bundle_header(self, bundle_path: Path) -> dict[str, Any]:
        """Read bounded project-list metadata without verifying or extracting payload files."""
        try:
            if bundle_path.stat().st_size > MAX_BUNDLE_BYTES:
                raise ProjectBundleError("Project bundle exceeds the 10 MiB size limit")
            with zipfile.ZipFile(bundle_path, "r") as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise ProjectBundleError("Project bundle contains duplicate paths")
                if len(names) > MAX_BUNDLE_FILES:
                    raise ProjectBundleError("Project bundle contains too many files")
                if BUNDLE_MANIFEST not in names:
                    raise ProjectBundleError("Missing bundle manifest")
                manifest_info = archive.getinfo(BUNDLE_MANIFEST)
                if manifest_info.file_size > MAX_BUNDLE_MANIFEST_BYTES:
                    raise ProjectBundleError("Bundle manifest exceeds the header size limit")
                manifest: dict[str, Any] = json.loads(archive.read(manifest_info))

                if "project.json" in names:
                    project_info = archive.getinfo("project.json")
                    if project_info.file_size > MAX_PROJECT_METADATA_BYTES:
                        raise ProjectBundleError("Project metadata exceeds the header size limit")
                    project_metadata = json.loads(archive.read(project_info))
                    manifest["project_metadata"] = project_metadata

                # The file-level manifest can be large and is irrelevant to the project list.
                return {key: value for key, value in manifest.items() if key != "files"}
        except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, OSError) as exc:
            raise ProjectBundleError(f"Cannot read bundle header: {exc}") from exc

    def load_all(self, *, lazy: bool = True) -> dict[str, dict[str, Any]]:
        """Verify all canonical bundles and materialize fresh managed workspaces.

        If lazy=True, only read bundle headers without full extraction.
        If lazy=False, extract and verify all bundles (original behavior).
        """
        self.migrate_legacy_directories()
        projects: dict[str, dict[str, Any]] = {}
        for bundle in sorted(self.base_dir.glob(f"*{BUNDLE_SUFFIX}")):
            if bundle.name.startswith("._"):
                continue
            project_id = bundle.name[: -len(BUNDLE_SUFFIX)]
            try:
                if lazy:
                    # Lazy mode: only read header, don't extract
                    manifest = self.read_bundle_header(bundle)
                    project_metadata = manifest.get("project_metadata", {})
                    metadata = {
                        "id": project_metadata.get("id", manifest.get("project_id", project_id)),
                        "name": project_metadata.get("name", project_id),
                        "description": project_metadata.get("description", ""),
                        "revision": manifest.get("revision", 0),
                        "integrity_status": "unknown",
                        "last_verified_at": None,
                        "verification_scope": "header",
                    }
                    if metadata["id"] != project_id:
                        raise ProjectBundleError(
                            f"Bundle name/project id mismatch: {bundle.name} contains {metadata['id']!r}"
                        )
                else:
                    # Full mode: extract and verify
                    self.extract_verified(project_id)
                    metadata_path = self.workspace_path(project_id) / "project.json"
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if metadata.get("id") != project_id:
                        raise ProjectBundleError(
                            f"Bundle name/project id mismatch: {bundle.name} contains {metadata.get('id')!r}"
                        )
                    metadata["integrity_status"] = "verified"
            except (ProjectBundleError, json.JSONDecodeError, OSError) as exc:
                logger.warning("Corrupt editable project '%s': %s", bundle.name, exc)
                # Include corrupt projects in the list with failed integrity status
                metadata = {
                    "id": project_id,
                    "name": project_id,
                    "description": f"Corrupt project: {exc}",
                    "integrity_status": "failed",
                    "integrity_error": str(exc),
                }
            projects[project_id] = metadata
        return projects

    def save(self, project_id: str, *, reason: str, keep_previous: bool = True) -> dict[str, Any]:
        """Atomically replace the canonical bundle and retain a rolling full version."""
        workspace = self.workspace_path(project_id)
        metadata_path = workspace / "project.json"
        if not metadata_path.is_file():
            raise ProjectBundleError(f"Managed workspace has no project.json: {project_id}")

        bundle = self.bundle_path(project_id)
        previous_manifest: dict[str, Any] = {}
        bundle_was_valid = False
        if bundle.exists():
            try:
                previous_manifest = self.verify(bundle, expected_project_id=project_id)
                bundle_was_valid = True
            except ProjectBundleError:
                self._retain_corrupt(project_id, bundle)
                previous_manifest = {"revision": self._highest_retained_revision(project_id)}
        revision = int(previous_manifest.get("revision", 0)) + 1
        saved_at = datetime.now(timezone.utc).isoformat()
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f"{project_id}-",
            suffix=f"{BUNDLE_SUFFIX}.tmp",
            dir=self.temp_root,
        )
        os.close(temp_fd)
        temp_path = Path(temp_name)
        try:
            file_manifest: dict[str, dict[str, Any]] = {}
            previous_files: dict[str, dict[str, Any]] = previous_manifest.get("files", {})
            # Try to open the previous bundle for copying unchanged entries
            previous_archive: zipfile.ZipFile | None = None
            if bundle_was_valid and bundle.exists():
                try:
                    previous_archive = zipfile.ZipFile(bundle, "r")
                except (zipfile.BadZipFile, OSError):
                    previous_archive = None
            try:
                with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for source in self._iter_bundle_files(workspace):
                        relative = source.relative_to(workspace).as_posix()
                        current_size = source.stat().st_size
                        prev_entry = previous_files.get(relative)
                        # Change detection: skip re-read/re-compress if file is unchanged
                        if (prev_entry
                                and current_size == int(prev_entry.get("size", 0))
                                and previous_archive is not None):
                            cached_sha256 = prev_entry.get("sha256")
                            # Quick size match — now verify sha256
                            if cached_sha256 == self._compute_file_sha256(source):
                                try:
                                    compressed = previous_archive.read(relative)
                                    archive.writestr(relative, compressed)
                                    file_manifest[relative] = prev_entry
                                    continue
                                except KeyError:
                                    pass  # fall through to normal write
                        # File changed or not in previous manifest — write from scratch
                        digest = hashlib.sha256()
                        size = 0
                        with source.open("rb") as input_stream, archive.open(relative, "w") as output_stream:
                            while chunk := input_stream.read(1024 * 1024):
                                output_stream.write(chunk)
                                digest.update(chunk)
                                size += len(chunk)
                        file_manifest[relative] = {"sha256": digest.hexdigest(), "size": size}
                    manifest = {
                        "schema_version": BUNDLE_SCHEMA_VERSION,
                        "project_id": project_id,
                        "revision": revision,
                        "saved_at": saved_at,
                        "reason": reason,
                        "files": file_manifest,
                    }
                    archive.writestr(BUNDLE_MANIFEST, json.dumps(manifest, indent=2))
            finally:
                if previous_archive is not None:
                    previous_archive.close()

            compressed_size = temp_path.stat().st_size
            if compressed_size > MAX_BUNDLE_BYTES:
                raise ProjectBundleError("Project bundle exceeds the 10 MiB size limit")

            uncompressed_size = sum(int(f.get("size", 0)) for f in file_manifest.values())
            if compressed_size > 0 and uncompressed_size / compressed_size > MAX_COMPRESSION_RATIO:
                raise ProjectBundleError(
                    f"Compression ratio {uncompressed_size / compressed_size:.0f}:1 exceeds the "
                    f"{MAX_COMPRESSION_RATIO}:1 limit (possible zip bomb)"
                )

            self.verify(temp_path, expected_project_id=project_id)

            # fsync the temporary file to ensure durability (best-effort on Windows)
            try:
                with open(temp_path, "rb") as f:
                    os.fsync(f.fileno())
            except OSError:
                pass

            if keep_previous and bundle.exists() and bundle_was_valid:
                self._retain_previous(project_id, bundle, previous_manifest)

            # Atomic replace
            os.replace(temp_path, bundle)

            # fsync the parent directory to ensure the replace is durable
            parent_dir = bundle.parent
            try:
                dir_fd = os.open(parent_dir, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                # Some systems don't support fsync on directories
                pass

            self._prune_versions(project_id)
            return manifest
        finally:
            temp_path.unlink(missing_ok=True)

    def verify(self, bundle_path: Path, *, expected_project_id: str | None = None) -> dict[str, Any]:
        """Validate archive paths, project identity, sizes, and SHA-256 checksums."""
        try:
            if bundle_path.stat().st_size > MAX_BUNDLE_BYTES:
                raise ProjectBundleError("Project bundle exceeds the 10 MiB size limit")
            with zipfile.ZipFile(bundle_path, "r") as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise ProjectBundleError("Project bundle contains duplicate paths")
                if len(names) > MAX_BUNDLE_FILES:
                    raise ProjectBundleError("Project bundle contains too many files")
                if BUNDLE_MANIFEST not in names:
                    raise ProjectBundleError(f"Missing {BUNDLE_MANIFEST}")
                manifest_info = archive.getinfo(BUNDLE_MANIFEST)
                if manifest_info.file_size > MAX_BUNDLE_MANIFEST_BYTES:
                    raise ProjectBundleError("Bundle manifest exceeds the header size limit")
                manifest: dict[str, Any] = json.loads(archive.read(manifest_info))
                schema_version = manifest.get("schema_version")
                if schema_version not in SUPPORTED_BUNDLE_SCHEMA_VERSIONS:
                    raise ProjectBundleError("Unsupported editable project bundle version")
                if expected_project_id and manifest.get("project_id") != expected_project_id:
                    raise ProjectBundleError("Project bundle identity does not match its filename")
                declared = manifest.get("files", {})
                actual = {name for name in names if name != BUNDLE_MANIFEST}
                if actual != set(declared):
                    raise ProjectBundleError("Project bundle file manifest does not match archive contents")
                total_size = manifest_info.file_size
                for name, details in declared.items():
                    self._validate_member_path(name)
                    if schema_version == BUNDLE_SCHEMA_VERSION and not is_trackable_bundle_path(PurePosixPath(name)):
                        raise ProjectBundleError(f"Untrackable file in project bundle: {name}")
                    info = archive.getinfo(name)
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise ProjectBundleError(f"Symbolic links are not allowed: {name}")
                    declared_size = int(details.get("size", -1))
                    if info.file_size != declared_size:
                        raise ProjectBundleError(f"Size mismatch for {name}")
                    total_size += info.file_size
                    if total_size > MAX_BUNDLE_UNCOMPRESSED_BYTES:
                        raise ProjectBundleError("Project bundle is too large when extracted")
                    digest = hashlib.sha256()
                    with archive.open(info) as stream:
                        while chunk := stream.read(1024 * 1024):
                            digest.update(chunk)
                    if digest.hexdigest() != details.get("sha256"):
                        raise ProjectBundleError(f"Checksum mismatch for {name}")
                    if schema_version == BUNDLE_SCHEMA_VERSION and PurePosixPath(name).suffix.lower() in {
                        ".cfg", ".csv", ".html", ".json", ".jsonl", ".md", ".r",
                        ".rst", ".svg", ".toml", ".tsv", ".txt", ".yaml", ".yml",
                    }:
                        file_bytes = archive.read(info)
                        findings = find_absolute_path_records(
                            Path(name), content=file_bytes,
                        )
                        if findings:
                            raise ProjectBundleError(
                                f"Machine-local absolute path in {name}: {findings[0]}"
                            )
                if "project.json" not in declared:
                    raise ProjectBundleError("Project bundle has no project.json")
                # Validate history integrity if history files are present
                self._verify_history_integrity(archive, names)
                return manifest
        except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, OSError) as exc:
            raise ProjectBundleError(f"Unreadable project bundle {bundle_path.name}: {exc}") from exc

    def extract_verified(self, project_id: str) -> Path:
        """Replace the disposable workspace with verified archive contents."""
        return self._extract_bundle(self.bundle_path(project_id), project_id)

    def list_versions(self, project_id: str) -> list[dict[str, Any]]:
        """List verified retained bundles, newest revision first."""
        versions = []
        current = self.bundle_path(project_id)
        candidates = [current] if current.exists() else []
        version_dir = self.version_root / project_id
        candidates.extend(
            path
            for path in version_dir.glob(f"*{BUNDLE_SUFFIX}")
            if not path.name.startswith("._")
        )
        for path in candidates:
            try:
                manifest = self.verify(path, expected_project_id=project_id)
            except ProjectBundleError:
                continue
            versions.append(
                {
                    "revision": int(manifest.get("revision", 0)),
                    "saved_at": manifest.get("saved_at", ""),
                    "reason": manifest.get("reason", ""),
                    "current": path == current,
                    "path": str(path.resolve()),
                }
            )
        return sorted(versions, key=lambda item: item["revision"], reverse=True)

    def restore(self, project_id: str, revision: int) -> dict[str, Any]:
        """Restore a retained full bundle as a new canonical revision."""
        candidate = self.version_root / project_id / f"revision-{revision:08d}{BUNDLE_SUFFIX}"
        if not candidate.is_file():
            raise ProjectBundleError(f"Retained project revision not found: {revision}")
        self._extract_bundle(candidate, project_id)
        return self.save(project_id, reason=f"restored_revision_{revision}")

    def extract_retained_to(
        self, project_id: str, revision: int, target_dir: Path
    ) -> None:
        """Extract a retained version to *target_dir* instead of the workspace.

        This is the transactional variant of :meth:`restore` — the caller is
        responsible for bundling *target_dir* via :meth:`save_from_staging`.
        The *target_dir* is cleared before extraction.
        """
        candidate = self.version_root / project_id / f"revision-{revision:08d}{BUNDLE_SUFFIX}"
        if not candidate.is_file():
            raise ProjectBundleError(f"Retained project revision not found: {revision}")
        self.verify(candidate, expected_project_id=project_id)
        # Clear target before extracting
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(candidate, "r") as archive:
            for name in archive.namelist():
                if name == BUNDLE_MANIFEST:
                    continue
                self._validate_member_path(name)
                dest = target_dir / PurePosixPath(name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, dest.open("wb") as destination:
                    shutil.copyfileobj(source, destination)

    def _extract_bundle(self, bundle: Path, project_id: str) -> Path:
        self.verify(bundle, expected_project_id=project_id)
        workspace = self.workspace_path(project_id)
        staging = self.workspace_root / f".{project_id}.extracting"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            with zipfile.ZipFile(bundle, "r") as archive:
                for name in archive.namelist():
                    if name == BUNDLE_MANIFEST:
                        continue
                    self._validate_member_path(name)
                    target = staging / PurePosixPath(name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
            if workspace.exists():
                shutil.rmtree(workspace)
            staging.replace(workspace)
            return workspace
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def read_manifest(self, bundle_path: Path) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(bundle_path, "r") as archive:
                result: dict[str, Any] = json.loads(archive.read(BUNDLE_MANIFEST))
                return result
        except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, OSError) as exc:
            raise ProjectBundleError(f"Cannot read project bundle manifest: {exc}") from exc

    def read_current_revision(self, project_id: str) -> int:
        """Return the revision number of the current bundle without full verification."""
        bundle = self.bundle_path(project_id)
        if not bundle.exists():
            return 0
        try:
            manifest = self.read_manifest(bundle)
            return int(manifest.get("revision", 0))
        except ProjectBundleError:
            return 0

    def save_from_staging(
        self,
        project_id: str,
        staging_dir: Path,
        *,
        reason: str,
        keep_previous: bool = True,
    ) -> dict[str, Any]:
        """Create a bundle from *staging_dir* and atomically replace the workspace.

        This is the transactional variant of :meth:`save`.  It expects
        *staging_dir* to contain a complete, valid project tree (including
        ``project.json``).  On success the staging directory is moved into the
        workspace location.
        """
        metadata_path = staging_dir / "project.json"
        if not metadata_path.is_file():
            raise ProjectBundleError(f"Staging directory has no project.json: {project_id}")

        bundle = self.bundle_path(project_id)
        previous_manifest: dict[str, Any] = {}
        bundle_was_valid = False
        if bundle.exists():
            try:
                previous_manifest = self.verify(bundle, expected_project_id=project_id)
                bundle_was_valid = True
            except ProjectBundleError:
                self._retain_corrupt(project_id, bundle)
                previous_manifest = {"revision": self._highest_retained_revision(project_id)}

        revision = int(previous_manifest.get("revision", 0)) + 1
        saved_at = datetime.now(timezone.utc).isoformat()

        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f"{project_id}-",
            suffix=f"{BUNDLE_SUFFIX}.tmp",
            dir=self.temp_root,
        )
        os.close(temp_fd)
        temp_path = Path(temp_name)

        try:
            file_manifest: dict[str, dict[str, Any]] = {}
            with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for source in self._iter_bundle_files(staging_dir):
                    relative = source.relative_to(staging_dir).as_posix()
                    digest = hashlib.sha256()
                    size = 0
                    with source.open("rb") as inp, archive.open(relative, "w") as out:
                        while chunk := inp.read(1024 * 1024):
                            out.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    file_manifest[relative] = {"sha256": digest.hexdigest(), "size": size}
                manifest = {
                    "schema_version": BUNDLE_SCHEMA_VERSION,
                    "project_id": project_id,
                    "revision": revision,
                    "saved_at": saved_at,
                    "reason": reason,
                    "files": file_manifest,
                }
                archive.writestr(BUNDLE_MANIFEST, json.dumps(manifest, indent=2))

            compressed_size = temp_path.stat().st_size
            if compressed_size > MAX_BUNDLE_BYTES:
                raise ProjectBundleError("Project bundle exceeds the 10 MiB size limit")

            uncompressed_size = sum(int(f.get("size", 0)) for f in file_manifest.values())
            if compressed_size > 0 and uncompressed_size / compressed_size > MAX_COMPRESSION_RATIO:
                raise ProjectBundleError(
                    f"Compression ratio {uncompressed_size / compressed_size:.0f}:1 exceeds the "
                    f"{MAX_COMPRESSION_RATIO}:1 limit (possible zip bomb)"
                )

            self.verify(temp_path, expected_project_id=project_id)

            # fsync the temporary file to ensure durability (best-effort on Windows)
            try:
                with open(temp_path, "rb") as f:
                    os.fsync(f.fileno())
            except OSError:
                pass

            if keep_previous and bundle.exists() and bundle_was_valid:
                self._retain_previous(project_id, bundle, previous_manifest)

            # Atomic replace
            os.replace(temp_path, bundle)

            # fsync the parent directory to ensure the replace is durable
            parent_dir = bundle.parent
            try:
                dir_fd = os.open(parent_dir, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                # Some systems don't support fsync on directories
                pass

            # Swap staging into workspace
            workspace = self.workspace_path(project_id)
            if workspace.exists():
                shutil.rmtree(workspace)
            shutil.move(str(staging_dir), str(workspace))

            self._prune_versions(project_id)
            return manifest
        finally:
            temp_path.unlink(missing_ok=True)

    def _retain_previous(
        self,
        project_id: str,
        bundle: Path,
        previous_manifest: dict[str, Any],
    ) -> None:
        revision = int(previous_manifest.get("revision", 0))
        if revision <= 0:
            return
        version_dir = self.version_root / project_id
        version_dir.mkdir(parents=True, exist_ok=True)
        destination = version_dir / f"revision-{revision:08d}{BUNDLE_SUFFIX}"
        if not destination.exists():
            shutil.copy2(bundle, destination)

    @staticmethod
    def _compute_file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _prune_versions(self, project_id: str) -> None:
        if self.retained_versions < 0:
            return
        versions = sorted(
            path
            for path in (self.version_root / project_id).glob(f"*{BUNDLE_SUFFIX}")
            if not path.name.startswith("._") and not path.name.startswith("corrupt-")
        )
        for obsolete in versions[: max(0, len(versions) - self.retained_versions)]:
            obsolete.unlink(missing_ok=True)

    def _retain_corrupt(self, project_id: str, bundle: Path) -> None:
        version_dir = self.version_root / project_id
        version_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        shutil.copy2(bundle, version_dir / f"corrupt-{timestamp}{BUNDLE_SUFFIX}")

    def _highest_retained_revision(self, project_id: str) -> int:
        revisions = []
        for path in (self.version_root / project_id).glob(f"revision-*{BUNDLE_SUFFIX}"):
            if path.name.startswith("._"):
                continue
            try:
                revisions.append(int(path.name.removeprefix("revision-").removesuffix(BUNDLE_SUFFIX)))
            except ValueError:
                continue
        return max(revisions, default=0)

    @staticmethod
    def _iter_bundle_files(workspace: Path):
        total_size = 0
        file_count = 0
        for path in sorted(workspace.rglob("*")):
            if path.is_symlink():
                raise ProjectBundleError(f"Managed project contains a symbolic link: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(workspace)
            if any(part.startswith("._") or part in {".DS_Store", ".git"} for part in relative.parts):
                continue
            relative_posix = PurePosixPath(relative.as_posix())
            if not is_trackable_bundle_path(relative_posix):
                continue
            findings = find_absolute_path_records(path)
            if findings:
                raise ProjectBundleError(
                    f"Machine-local absolute path in {relative_posix.as_posix()}: {findings[0]}"
                )
            member_size = path.stat().st_size
            if member_size > MAX_MEMBER_BYTES:
                raise ProjectBundleError(
                    f"Single file exceeds the 8 MiB per-member limit: {relative_posix.as_posix()} ({member_size} bytes)"
                )
            file_count += 1
            if file_count > MAX_BUNDLE_FILES:
                raise ProjectBundleError("Project bundle contains too many files")
            total_size += member_size
            if total_size > MAX_BUNDLE_UNCOMPRESSED_BYTES:
                raise ProjectBundleError("Project bundle exceeds the 10 MiB extracted-size limit")
            yield path

    @staticmethod
    def _validate_member_path(name: str) -> None:
        if not name or "\\" in name or name.startswith(("/", "~/", "//")):
            raise ProjectBundleError(f"Unsafe path in project bundle: {name!r}")
        if len(name) >= 3 and name[0].isalpha() and name[1:3] in {":/", ":\\"}:
            raise ProjectBundleError(f"Unsafe path in project bundle: {name!r}")
        if any(part in {"", ".", ".."} for part in name.split("/")):
            raise ProjectBundleError(f"Unsafe path in project bundle: {name!r}")
        path = PurePosixPath(name)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise ProjectBundleError(f"Unsafe path in project bundle: {name!r}")

    @staticmethod
    def _verify_history_integrity(archive: zipfile.ZipFile, names: list[str]) -> None:
        """Validate history graph integrity if history files are present.

        Checks:
        - state.json is valid JSON with head and refs
        - HEAD commit exists
        - All branch refs point to existing commits
        - Each commit's parent(s) and design_object_id exist
        """
        state_path = "history/state.json"
        if state_path not in names:
            return  # no history — nothing to check
        try:
            state_data = json.loads(archive.read(state_path))
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProjectBundleError(f"Corrupt history state.json: {exc}") from exc

        head_commit_id = state_data.get("head", {}).get("commit_id", "")
        refs = state_data.get("refs", {}).get("heads", {})

        def _commit_path(cid: str) -> str:
            return f"history/commits/{cid[:2]}/{cid[2:]}.json"

        def _object_path(oid: str) -> str:
            return f"history/objects/{oid[:2]}/{oid[2:]}.json"

        # Validate HEAD commit exists
        if head_commit_id and _commit_path(head_commit_id) not in names:
            raise ProjectBundleError(f"History HEAD commit missing: {head_commit_id[:16]}")

        # Validate all branch refs
        all_commit_ids: set[str] = set()
        for branch, cid in refs.items():
            if _commit_path(cid) not in names:
                raise ProjectBundleError(f"Branch {branch!r} points to missing commit: {cid[:16]}")
            all_commit_ids.add(cid)

        # Walk reachable commits and validate parents + objects
        visited: set[str] = set()
        queue = list(all_commit_ids)
        while queue:
            cid = queue.pop(0)
            if cid in visited:
                continue
            visited.add(cid)
            cpath = _commit_path(cid)
            if cpath not in names:
                raise ProjectBundleError(f"Commit missing: {cid[:16]}")
            try:
                commit_data = json.loads(archive.read(cpath))
            except (json.JSONDecodeError, KeyError) as exc:
                raise ProjectBundleError(f"Corrupt commit {cid[:16]}: {exc}") from exc
            # Validate parent commits
            for parent_id in commit_data.get("parents", []):
                if _commit_path(parent_id) not in names:
                    raise ProjectBundleError(f"Parent commit missing: {parent_id[:16]}")
                queue.append(parent_id)
            # Validate design object
            obj_id = commit_data.get("design_object_id", "")
            if obj_id and _object_path(obj_id) not in names:
                raise ProjectBundleError(f"Design object missing: {obj_id[:16]}")
