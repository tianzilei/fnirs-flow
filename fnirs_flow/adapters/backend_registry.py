"""Backend registry for fnirs-flow execution backends.

This module provides the backend registry with lazy loading support.
Backends are registered with string entry points and only loaded when
explicitly requested via load() or create().

Implements §7.1 of the design document:
- register_lazy() stores string entry points, not class objects
- describe() returns metadata without loading the backend
- is_available() uses lightweight detection without importing
- load() explicitly loads and caches the backend class
- create() loads and instantiates
- unload() clears the cache (does not unload Python modules)
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from collections.abc import Callable
from typing import Any

from fnirs_flow.adapters.backend_protocol import BackendProtocol

logger = logging.getLogger(__name__)


class BackendNotAvailableError(Exception):
    """Raised when a required backend is not available."""

    def __init__(self, backend_id: str, message: str | None = None) -> None:
        self.backend_id = backend_id
        self.message = message or f"Backend '{backend_id}' is not available"
        super().__init__(self.message)


class BackendLoadError(Exception):
    """Raised when a backend fails to load."""

    def __init__(self, backend_id: str, class_path: str, cause: Exception | None = None) -> None:
        self.backend_id = backend_id
        self.class_path = class_path
        self.cause = cause
        message = f"Failed to load backend '{backend_id}' from '{class_path}'"
        if cause:
            message += f": {cause}"
        super().__init__(message)


class BackendEntry:
    """Static entry for a backend in the registry."""

    def __init__(
        self,
        backend_id: str,
        class_path: str,
        dependency_profile_id: str | None = None,
        detector: Callable[[], bool] | None = None,
        display_name: str = "",
        description: str = "",
    ) -> None:
        self.backend_id = backend_id
        self.class_path = class_path
        self.dependency_profile_id = dependency_profile_id
        self.detector = detector
        self.display_name = display_name or backend_id
        self.description = description


class BackendRegistry:
    """Registry for execution backends with lazy loading.

    Stores string entry points instead of class objects. Backends are
    only loaded when explicitly requested via load() or create().
    """

    def __init__(self) -> None:
        self._entries: dict[str, BackendEntry] = {}
        self._loaded_classes: dict[str, type[BackendProtocol]] = {}
        self._instances: dict[str, BackendProtocol] = {}

    def register(
        self,
        backend_id: str,
        class_path: str,
        dependency_profile_id: str | None = None,
        detector: Callable[[], bool] | None = None,
        display_name: str = "",
        description: str = "",
    ) -> None:
        """Register a backend with lazy loading.

        Args:
            backend_id: Unique backend identifier
            class_path: Python class path (e.g., "fnirs_flow.adapters.cedalion_adapter:CedalionAdapter")
            dependency_profile_id: Associated dependency profile ID
            detector: Lightweight availability detector (uses find_spec, not import)
            display_name: Human-readable name
            description: Backend description
        """
        self._entries[backend_id] = BackendEntry(
            backend_id=backend_id,
            class_path=class_path,
            dependency_profile_id=dependency_profile_id,
            detector=detector,
            display_name=display_name,
            description=description,
        )

    def describe(self, backend_id: str) -> dict[str, Any] | None:
        """Describe a backend without loading it.

        Returns metadata only - no imports, no instantiation.
        Implements §7.1: registry.describe(backend_id) returns metadata only
        and does not load the backend.
        """
        entry = self._entries.get(backend_id)
        if entry is None:
            return None

        return {
            "backend_id": entry.backend_id,
            "class_path": entry.class_path,
            "dependency_profile_id": entry.dependency_profile_id,
            "display_name": entry.display_name,
            "description": entry.description,
            "is_available": self.is_available(backend_id),
            "is_loaded": backend_id in self._loaded_classes,
        }

    def is_available(self, backend_id: str) -> bool:
        """Check if a backend is available without loading it.

        Uses the lightweight detector if provided, otherwise checks
        if the module exists using find_spec.
        Implements §7.1: registry.is_available(backend_id) is a read-only
        lightweight check.
        """
        entry = self._entries.get(backend_id)
        if entry is None:
            return False

        # Use detector if available
        if entry.detector is not None:
            try:
                return entry.detector()
            except Exception:
                return False

        # Fallback: check if module exists
        module_path = entry.class_path.split(":")[0]
        return importlib.util.find_spec(module_path) is not None

    def get(self, backend_id: str) -> type[BackendProtocol] | None:
        """Get backend class by ID (loads if not cached).

        Prefer load() for explicit loading.
        """
        if backend_id in self._loaded_classes:
            return self._loaded_classes[backend_id]
        # Lazy load on get
        return self.load(backend_id)

    def load(self, backend_id: str) -> type[BackendProtocol] | None:
        """Load and cache a backend class.

        Implements §7.1: registry.load(backend_id) explicitly loads backend
        code.
        """
        if backend_id in self._loaded_classes:
            return self._loaded_classes[backend_id]

        entry = self._entries.get(backend_id)
        if entry is None:
            return None

        # Parse class path (module:ClassName)
        if ":" in entry.class_path:
            module_path, class_name = entry.class_path.rsplit(":", 1)
        else:
            module_path = entry.class_path
            class_name = entry.class_path.rsplit(".", 1)[-1]

        try:
            module = importlib.import_module(module_path)
            backend_class: type[BackendProtocol] = getattr(module, class_name)
            self._loaded_classes[backend_id] = backend_class
            logger.info("Loaded backend: %s", backend_id)
            return backend_class
        except (ImportError, AttributeError) as e:
            logger.warning("Failed to load backend '%s' from '%s': %s", backend_id, entry.class_path, e)
            return None

    def create(self, backend_id: str, **kwargs: Any) -> BackendProtocol:
        """Load and instantiate a backend.

        Implements §7.1: registry.create(backend_id, **kw) loads and
        instantiates the backend.
        """
        if not self.is_available(backend_id):
            raise BackendNotAvailableError(backend_id)

        backend_class = self.load(backend_id)
        if backend_class is None:
            entry = self._entries.get(backend_id)
            class_path = entry.class_path if entry else "unknown"
            raise BackendLoadError(backend_id, class_path)
        return backend_class(**kwargs)

    def unload(self, backend_id: str) -> None:
        """Unload a backend from the cache.

        Implements §7.1: registry.unload(backend_id) clears only the registry
        cache and does not promise to unload Python modules.
        """
        self._loaded_classes.pop(backend_id, None)

    def list_available(self) -> list[str]:
        """List all available backend IDs."""
        return [bid for bid in self._entries if self.is_available(bid)]

    def list_all(self) -> list[str]:
        """List all registered backend IDs."""
        return list(self._entries.keys())


class LazyAdapterPool:
    """Pool that lazily creates and caches backend adapters.

    Used by the execution service to avoid creating a single backend
    for the entire DAG. Instead, backends are created on-demand when
    a specific MethodAtom needs them.
    """

    def __init__(self, registry: BackendRegistry | None = None) -> None:
        self._registry = registry or get_registry()
        self._instances: dict[str, BackendProtocol] = {}

    def get(self, backend_id: str, **kwargs: Any) -> BackendProtocol:
        """Get or create a backend adapter.

        Returns the cached instance if available, otherwise creates one.
        """
        if backend_id not in self._instances:
            self._instances[backend_id] = self._registry.create(backend_id, **kwargs)
        return self._instances[backend_id]

    def has(self, backend_id: str) -> bool:
        """Check if a backend is already instantiated in the pool."""
        return backend_id in self._instances

    def unload(self, backend_id: str) -> None:
        """Remove a backend from the pool."""
        self._instances.pop(backend_id, None)

    def unload_all(self) -> None:
        """Remove all backends from the pool."""
        self._instances.clear()

    def items(self) -> list[tuple[str, BackendProtocol]]:
        """Return all instantiated backend (id, adapter) pairs."""
        return list(self._instances.items())


# Global registry instance
_registry = BackendRegistry()


def get_registry() -> BackendRegistry:
    """Get the global backend registry."""
    return _registry


# Lightweight detectors (no imports)
def detect_mne() -> bool:
    """Detect if MNE-NIRS is available."""
    return (
        importlib.util.find_spec("mne") is not None
        and importlib.util.find_spec("mne_nirs") is not None
    )


def detect_cedalion() -> bool:
    """Detect if Cedalion is available."""
    return importlib.util.find_spec("cedalion") is not None


def _register_known_backends() -> None:
    """Register known backends with lazy loading.

    Uses string entry points instead of importing adapter classes.
    Implements §7.1: do not call import_module() during registration.
    """
    _registry.register(
        backend_id="mne_nirs",
        class_path="fnirs_flow.adapters.mne_nirs_adapter:MneNirsAdapter",
        dependency_profile_id="mne-nirs-1.0",
        detector=detect_mne,
        display_name="MNE-NIRS",
        description="MNE-based fNIRS analysis backend",
    )

    _registry.register(
        backend_id="cedalion",
        class_path="fnirs_flow.adapters.cedalion_adapter:CedalionAdapter",
        dependency_profile_id="cedalion-26.5",
        detector=detect_cedalion,
        display_name="Cedalion",
        description="Cedalion scientific computing backend",
    )


# Register backends at module load time (no imports)
_register_known_backends()
