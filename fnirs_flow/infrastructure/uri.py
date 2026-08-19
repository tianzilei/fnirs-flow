"""Portable project and external-data URI infrastructure."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

_SUPPORTED_SCHEMES = {"project", "external-data"}
_DATASET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:($|/)")


def _normalize_relative_path(value: str, *, label: str) -> PurePosixPath:
    normalized = str(value).replace("\\", "/")
    if not normalized or normalized.startswith("/") or _WINDOWS_DRIVE_PATTERN.match(normalized):
        raise ValueError(f"{label} must be a non-empty relative path")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{label} contains an unsafe path segment")
    path = PurePosixPath(*parts)
    if path.is_absolute():
        raise ValueError(f"{label} must be relative")
    return path


def _validate_dataset_id(dataset_id: str) -> str:
    if not _DATASET_ID_PATTERN.fullmatch(dataset_id) or dataset_id in {".", ".."}:
        raise ValueError("dataset_id must contain only letters, numbers, '.', '_' or '-' and cannot be '.' or '..'")
    return dataset_id


class ProjectURI:
    """Parsed, validated project or external-data URI."""

    def __init__(self, uri: str) -> None:
        parsed = urlsplit(uri)
        if parsed.scheme not in _SUPPORTED_SCHEMES:
            raise ValueError(f"Unsupported project URI scheme: {parsed.scheme!r}")
        if parsed.query or parsed.fragment or not parsed.netloc:
            raise ValueError("Project URIs must use scheme://authority form without query or fragment")
        self._scheme = parsed.scheme
        self._authority = parsed.netloc
        tail = parsed.path.removeprefix("/")
        if parsed.scheme == "project":
            self._dataset_id = None
            self._path = _normalize_relative_path(
                self._authority if not tail else f"{self._authority}/{tail}", label="project path"
            )
            self._uri = f"project://{self._path.as_posix()}"
        else:
            self._dataset_id = _validate_dataset_id(self._authority)
            self._path = _normalize_relative_path(tail, label="external data path")
            self._uri = f"external-data://{self._dataset_id}/{self._path.as_posix()}"

    @property
    def scheme(self) -> str: return self._scheme
    @property
    def authority(self) -> str: return self._authority
    @property
    def dataset_id(self) -> str | None: return self._dataset_id
    @property
    def path(self) -> PurePosixPath: return self._path
    @property
    def uri(self) -> str: return self._uri
    def __str__(self) -> str: return self._uri
    def __repr__(self) -> str: return f"ProjectURI({self._uri!r})"
    def __eq__(self, other: object) -> bool:
        return self._uri == other._uri if isinstance(other, ProjectURI) else NotImplemented
    def __hash__(self) -> int: return hash(self._uri)


def create_project_uri(relative_path: str) -> ProjectURI:
    return ProjectURI(f"project://{_normalize_relative_path(relative_path, label='project path').as_posix()}")


def create_external_data_uri(dataset_id: str, relative_path: str) -> ProjectURI:
    safe_id = _validate_dataset_id(dataset_id)
    path = _normalize_relative_path(relative_path, label="external data path")
    return ProjectURI(f"external-data://{safe_id}/{path.as_posix()}")


def _resolve_within(root: Path, relative_path: PurePosixPath) -> Path | None:
    base = root.resolve()
    candidate = (base / Path(*relative_path.parts)).resolve()
    return candidate if candidate.is_relative_to(base) and candidate.exists() else None


def resolve_project_uri(uri: ProjectURI, project_dir: Path) -> Path | None:
    return _resolve_within(project_dir, uri.path) if uri.scheme == "project" else None


def resolve_external_data_uri(uri: ProjectURI, bindings: dict[str, Path]) -> Path | None:
    if uri.scheme != "external-data" or uri.dataset_id is None:
        return None
    binding = bindings.get(uri.dataset_id)
    return _resolve_within(binding, uri.path) if binding is not None else None


def path_to_project_uri(path: Path, project_dir: Path) -> ProjectURI | None:
    try:
        return create_project_uri(path.resolve().relative_to(project_dir.resolve()).as_posix())
    except ValueError:
        return None


def path_to_external_data_uri(path: Path, bindings: dict[str, Path]) -> ProjectURI | None:
    resolved = path.resolve()
    for dataset_id, binding in bindings.items():
        try:
            return create_external_data_uri(dataset_id, resolved.relative_to(binding.resolve()).as_posix())
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
        try:
            data = json.loads(self._bindings_file.read_text(encoding="utf-8"))
            bindings = data.get("bindings", {})
            self._bindings = {str(k): str(v) for k, v in bindings.items()} if isinstance(bindings, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._bindings = {}

    def _save(self) -> None:
        self._project_dir.mkdir(parents=True, exist_ok=True)
        self._bindings_file.write_text(
            json.dumps({"version": "1.0.0", "bindings": self._bindings}, indent=2),
            encoding="utf-8",
        )

    def bind(self, dataset_id: str, local_path: Path) -> None:
        self._bindings[_validate_dataset_id(dataset_id)] = str(local_path.resolve())
        self._save()

    def unbind(self, dataset_id: str) -> None:
        self._bindings.pop(_validate_dataset_id(dataset_id), None)
        self._save()

    def get_binding(self, dataset_id: str) -> Path | None:
        path = self._bindings.get(_validate_dataset_id(dataset_id))
        candidate = Path(path) if path else None
        return candidate if candidate and candidate.exists() else None

    def list_bindings(self) -> dict[str, Path]:
        return {key: path for key, value in self._bindings.items() if (path := Path(value)).exists()}

    def resolve_uri(self, uri: ProjectURI) -> Path | None:
        return resolve_external_data_uri(uri, self.list_bindings())
