"""Portable, project-relative URI helpers.

The canonical forms are ``project://<relative-path>`` for files stored inside
an editable project and ``external-data://<dataset-id>/<relative-path>`` for
raw data that must be rebound on another machine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

_SUPPORTED_SCHEMES = {"project", "external-data"}
_DATASET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:($|/)")


def _normalize_relative_path(value: str, *, label: str) -> PurePosixPath:
    """Return a safe POSIX relative path or raise ``ValueError``."""
    normalized = value.replace("\\", "/")
    if not normalized or normalized.startswith("/") or _WINDOWS_DRIVE_PATTERN.match(normalized):
        raise ValueError(f"{label} must be a non-empty relative path")

    raw_parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(f"{label} contains an unsafe path segment")

    path = PurePosixPath(*raw_parts)
    if path.is_absolute():
        raise ValueError(f"{label} must be relative")
    return path


def _validate_dataset_id(dataset_id: str) -> str:
    if not _DATASET_ID_PATTERN.fullmatch(dataset_id):
        raise ValueError("dataset_id must contain only letters, numbers, '.', '_' or '-'")
    if dataset_id in {".", ".."}:
        raise ValueError("dataset_id cannot be '.' or '..'")
    return dataset_id


class ProjectURI:
    """Parsed, validated project or external-data URI."""

    def __init__(self, uri: str) -> None:
        parsed = urlsplit(uri)
        if parsed.scheme not in _SUPPORTED_SCHEMES:
            raise ValueError(f"Unsupported project URI scheme: {parsed.scheme!r}")
        if parsed.query or parsed.fragment:
            raise ValueError("Project URIs cannot contain a query or fragment")
        if not parsed.netloc:
            raise ValueError("Project URIs must use the canonical scheme://authority form")

        self._scheme = parsed.scheme
        self._authority = parsed.netloc
        path_tail = parsed.path.removeprefix("/")

        if self._scheme == "project":
            combined = self._authority if not path_tail else f"{self._authority}/{path_tail}"
            self._path = _normalize_relative_path(combined, label="project path")
            self._dataset_id: str | None = None
            self._uri = f"project://{self._path.as_posix()}"
        else:
            self._dataset_id = _validate_dataset_id(self._authority)
            self._path = _normalize_relative_path(path_tail, label="external data path")
            self._uri = f"external-data://{self._dataset_id}/{self._path.as_posix()}"

    @property
    def scheme(self) -> str:
        return self._scheme

    @property
    def authority(self) -> str:
        return self._authority

    @property
    def dataset_id(self) -> str | None:
        return self._dataset_id

    @property
    def path(self) -> PurePosixPath:
        """Return the project-relative or dataset-relative resource path."""
        return self._path

    @property
    def uri(self) -> str:
        return self._uri

    def __str__(self) -> str:
        return self._uri

    def __repr__(self) -> str:
        return f"ProjectURI({self._uri!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ProjectURI):
            return self._uri == other._uri
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._uri)


def create_project_uri(relative_path: str) -> ProjectURI:
    """Create a canonical ``project://`` URI from a safe relative path."""
    path = _normalize_relative_path(relative_path, label="project path")
    return ProjectURI(f"project://{path.as_posix()}")


def create_external_data_uri(dataset_id: str, relative_path: str) -> ProjectURI:
    """Create a canonical ``external-data://`` URI."""
    safe_dataset_id = _validate_dataset_id(dataset_id)
    path = _normalize_relative_path(relative_path, label="external data path")
    return ProjectURI(f"external-data://{safe_dataset_id}/{path.as_posix()}")


def _resolve_within(root: Path, relative_path: PurePosixPath) -> Path | None:
    root_resolved = root.resolve()
    candidate = (root_resolved / Path(*relative_path.parts)).resolve()
    if not candidate.is_relative_to(root_resolved):
        return None
    return candidate if candidate.exists() else None


def resolve_project_uri(uri: ProjectURI, project_dir: Path) -> Path | None:
    """Resolve a ``project://`` URI without allowing project-root escape."""
    if uri.scheme != "project":
        return None
    return _resolve_within(project_dir, uri.path)


def resolve_external_data_uri(uri: ProjectURI, bindings: dict[str, Path]) -> Path | None:
    """Resolve an ``external-data://`` URI using a dataset binding."""
    if uri.scheme != "external-data" or uri.dataset_id is None:
        return None
    binding = bindings.get(uri.dataset_id)
    if binding is None:
        return None
    return _resolve_within(binding, uri.path)


def path_to_project_uri(path: Path, project_dir: Path) -> ProjectURI | None:
    """Convert a path inside *project_dir* to a portable URI."""
    try:
        relative = path.resolve().relative_to(project_dir.resolve())
        return create_project_uri(relative.as_posix())
    except ValueError:
        return None


def path_to_external_data_uri(path: Path, bindings: dict[str, Path]) -> ProjectURI | None:
    """Convert a path inside a bound dataset to a portable URI."""
    resolved_path = path.resolve()
    for dataset_id, binding_dir in bindings.items():
        try:
            relative = resolved_path.relative_to(binding_dir.resolve())
            return create_external_data_uri(dataset_id, relative.as_posix())
        except ValueError:
            continue
    return None


class URIBindingStore:
    """Manage local bindings for portable external-data URIs."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._bindings_file = project_dir / "uri_bindings.json"
        self._bindings: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._bindings_file.exists():
            try:
                data = json.loads(self._bindings_file.read_text(encoding="utf-8"))
                bindings = data.get("bindings", {})
                if isinstance(bindings, dict):
                    self._bindings = {str(key): str(value) for key, value in bindings.items()}
            except (json.JSONDecodeError, OSError):
                self._bindings = {}

    def _save(self) -> None:
        self._project_dir.mkdir(parents=True, exist_ok=True)
        data = {"version": "1.0.0", "bindings": self._bindings}
        self._bindings_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def bind(self, dataset_id: str, local_path: Path) -> None:
        safe_dataset_id = _validate_dataset_id(dataset_id)
        self._bindings[safe_dataset_id] = str(local_path.resolve())
        self._save()

    def unbind(self, dataset_id: str) -> None:
        safe_dataset_id = _validate_dataset_id(dataset_id)
        if safe_dataset_id in self._bindings:
            del self._bindings[safe_dataset_id]
            self._save()

    def get_binding(self, dataset_id: str) -> Path | None:
        safe_dataset_id = _validate_dataset_id(dataset_id)
        path_str = self._bindings.get(safe_dataset_id)
        if path_str is None:
            return None
        path = Path(path_str)
        return path if path.exists() else None

    def list_bindings(self) -> dict[str, Path]:
        return {
            dataset_id: path
            for dataset_id, path_str in self._bindings.items()
            if (path := Path(path_str)).exists()
        }

    def resolve_uri(self, uri: ProjectURI) -> Path | None:
        return resolve_external_data_uri(uri, self.list_bindings())
