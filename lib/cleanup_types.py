"""Shared row shapes and records at database and JSON boundaries.

SQL metadata and policy-specific evidence have variable layouts. Keep
those boundaries explicit while giving native character and spell state
precise types.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Literal, Protocol, TypeAlias, TypedDict


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list['JsonValue'] | dict[str, 'JsonValue']
DatabaseRow: TypeAlias = list[JsonScalar]
DatabaseState: TypeAlias = dict[str, list[DatabaseRow]]
Evidence: TypeAlias = dict[str, Any]
Character: TypeAlias = tuple[int, int, int, int]
SpellRow: TypeAlias = tuple[int, int, int, int]
DeferredRow: TypeAlias = tuple[int, int, str]
SpellFlags: TypeAlias = tuple[int, ...]
SpellBook: TypeAlias = dict[int, SpellFlags]
TalentMasks: TypeAlias = dict[int, int]
Skills: TypeAlias = dict[int, tuple[int, int]]
DbcStores: TypeAlias = dict[str, dict[int, list[int]]]
Direction: TypeAlias = Literal['tc-to-ac', 'ac-to-tc']
SelectionResult: TypeAlias = tuple[
    list[SpellRow], list[DeferredRow], list[tuple[Any, ...]], Evidence,
    list[tuple[int, int]],
]


class SpellResult(TypedDict, total=False):
    """Existing dictionary representation of one reconstructed spell."""

    mask: int
    disposition: str
    proofs: list[list[Any]]
    original: list[int] | None
    authorization: Evidence
    active: int
    disabled: int
    derived: bool


SpellResults: TypeAlias = dict[int, SpellResult]


class BatchManifest(TypedDict, total=False):
    """Common fields; policy-specific evidence remains dictionary data."""

    policy: str
    archive_schema: str
    batch_key: str
    cleanup_session: str
    source_uuid: str
    source_schema: str
    implementation_sha256: dict[str, str]


class OperationReport(TypedDict, total=False):
    """Persisted operation state, retaining the existing JSON field names."""

    command: str
    state: str
    started_utc: str
    finished_utc: str
    toolkit_sha256: dict[str, str]
    exit_code: int
    error: Evidence


class QueryRunner(Protocol):
    """Minimal database dependency for read-only snapshot generation."""

    def sql(
        self,
        query: str,
        role: str = 'audit',
        headers: bool = False,
    ) -> str:
        """Execute SQL using the caller's existing client and role boundary."""
        ...


class MetadataReader(Protocol):
    """Read effective metadata from MySQL or a captured immutable snapshot."""

    def rows(self, label: str, query: str) -> Iterable[Sequence[Any]]:
        """Read labeled rows without changing source state."""
        ...

    def table(
        self,
        schema: str,
        table: str,
        columns: list[str],
        optional: bool = False,
    ) -> list[list[Any]]:
        """Read selected metadata fields in their existing representation."""
        ...
