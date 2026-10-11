"""Registry of available datasources.

Open question #1 in INTEGRATION_SQL_SOURCE.md was "one database or several".
The answer here is several: the benchmark suites carry hundreds of SQLite
files, and restarting the service per database is not a usable workflow.

A datasource id is the file stem (`GeoNuclearData.sqlite` → `GeoNuclearData`),
which is also how schema profiles are named — so a profile is found without
any extra mapping.

Only paths are scanned at startup; databases are opened lazily on first use.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Datasource:
    id: str
    path: str

    @property
    def size_bytes(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0


class DatasourceRegistry:
    def __init__(self, roots: list[str], explicit_path: str = "", explicit_id: str = "") -> None:
        self._sources: dict[str, Datasource] = {}
        self._default_id: str | None = None

        if explicit_path:
            resolved = str(Path(explicit_path).expanduser())
            source_id = explicit_id or Path(resolved).stem
            self._sources[source_id] = Datasource(id=source_id, path=resolved)
            self._default_id = source_id

        for root in roots:
            self._scan(root)

        if self._default_id is None and self._sources:
            self._default_id = sorted(self._sources)[0]

        logger.info(
            "datasource registry: %d sources, default=%s",
            len(self._sources), self._default_id,
        )

    def _scan(self, root: str) -> None:
        root = (root or "").strip()
        if not root:
            return
        base = Path(root).expanduser()
        if not base.is_dir():
            logger.warning("datasource root not a directory, skipped: %s", base)
            return

        for path in sorted(base.rglob("*.sqlite")):
            source_id = path.stem
            existing = self._sources.get(source_id)
            if existing is not None:
                if existing.path != str(path):
                    # Ambiguous ids are a real risk across benchmark suites;
                    # first one wins so behaviour stays deterministic.
                    logger.warning(
                        "duplicate datasource id '%s': keeping %s, ignoring %s",
                        source_id, existing.path, path,
                    )
                continue
            self._sources[source_id] = Datasource(id=source_id, path=str(path))

    @property
    def default_id(self) -> str | None:
        return self._default_id

    def __len__(self) -> int:
        return len(self._sources)

    def list(self) -> list[Datasource]:
        return [self._sources[key] for key in sorted(self._sources)]

    def get(self, source_id: str | None) -> Datasource:
        resolved = (source_id or "").strip() or self._default_id
        if not resolved:
            raise KeyError("нет ни одного настроенного источника данных")
        if resolved not in self._sources:
            raise KeyError(f"неизвестный источник данных '{resolved}'")
        return self._sources[resolved]
