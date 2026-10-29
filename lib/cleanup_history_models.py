"""Typed stage results for history package planning."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, TYPE_CHECKING

from cleanup_types import (
    DatabaseRow,
    DatabaseState,
    DeferredRow,
    Evidence,
    SpellRow,
)

if TYPE_CHECKING:
    from spell_metadata import Metadata


@dataclass
class HistoryOptions:
    """Resolved policy flags and the implementation evidence they require."""

    absent_teachers: bool
    action_catalog: str | None
    action_mode: bool
    alias_mode: bool
    cast_script_mode: bool
    child_mode: bool
    config_contract: Evidence | None
    cower_proof: Evidence | None
    direct_mode: bool
    direct_ownership_reader: str | None
    direct_reader: str | None
    dual_mode: bool
    dual_sources: dict[str, str] | None
    eligibility_reader: str | None
    exact_mode: bool
    foreign_inventory_mode: bool
    foreign_mode: bool
    foreign_skill_mode: bool
    foreign_training: bool
    inactive_defaults: bool
    invalid_equipment: bool
    legacy_mode: bool
    legacy_reader: str | None
    native_action: str | None
    native_death_coil: bool
    native_selector: ModuleType
    numeric_reader: str | None
    offhand_mode: bool
    ordinary_mode: bool
    ordinary_reader: str | None
    overlevel_unselected: bool
    ownership_mode: bool
    ownership_reader: str | None
    parent_mode: bool
    parent_reader: str | None
    pending_death_coil: bool
    pending_defaults: bool
    pending_history: bool
    pending_native_sources: dict[str, str] | None
    pending_ownership: bool
    pending_professions: bool
    pet_mode: bool
    pet_reader: str | None
    prefix_mode: bool
    preview: bool
    profession_catalog: str | None
    profession_mode: bool
    profession_reader: str | None
    racial_catalog: str | None
    racial_mode: bool
    rekey_mode: bool
    reviewed_cower: bool
    riding_catalog: str | None
    riding_catalog_file: Path
    riding_horse: bool
    riding_invalid_items: bool
    riding_item_catalog: str | None
    riding_mode: bool
    riding_reader: str | None
    selected_mode: bool
    shaman_mode: bool
    shaman_reader: str | None
    skill_teaching_mode: bool
    specialization_catalog: str | None
    specialization_mode: bool
    specialization_reader: str | None
    strong_history_mode: bool
    swipe_catalog: str | None
    swipe_mode: bool
    teaching_catalog: str | None
    teaching_reader: str | None
    trained_mode: bool
    training_prerequisites: bool
    two_world_mode: bool
    world_guard_reader: str | None


@dataclass
class HistoryEvidence:
    """Captured inspection, effective metadata and source context."""

    audit: Evidence
    capture_report: Evidence | None
    captured_layout: DatabaseState | None
    context: DatabaseState | None
    effective: Metadata
    inspection_sha: str
    path: Path
    report: Evidence
    rows: list[DatabaseRow]
    state: DatabaseState
    world: Evidence


@dataclass
class HistoryPolicy:
    """Selected policy and its relationship and target metadata scope."""

    include_relations: bool
    include_routes: bool
    include_scripts: bool
    policy: str
    target_effective: Metadata | None
    target_world: Evidence | None


@dataclass
class HistorySelection:
    """Exact candidates and the evidence needed to archive them."""

    bindings: list[Sequence[Any]] | None
    default_skills: Evidence | None
    eligibility_proofs: list[Evidence] | None
    equipment: Evidence | None
    excluded: list[DeferredRow]
    foreign_defaults: Evidence | None
    foreign_equipment: Evidence | None
    foreign_inventory_moves: list[Sequence[Any]] | None
    foreign_items: Evidence | None
    foreign_readers: dict[str, str] | None
    foreign_scope: list[int] | None
    foreign_selected_equipment: Evidence | None
    foreign_selected_items: Evidence | None
    foreign_sources: dict[str, str] | None
    guid_set: set[int]
    guids: list[int]
    inventory_meta: Evidence | None
    inventory_moves: list[Sequence[Any]] | None
    native_base_proofs: list[Evidence] | None
    offhand_capture: Evidence | None
    offhand_rows: list[Sequence[Any]] | None
    offhand_sources: dict[str, str] | None
    ownership_native_proofs: list[Evidence] | None
    rank_proof: list[Sequence[Any]] | None
    rekeys: list[Sequence[Any]] | None
    relation_edges: list[Sequence[Any]] | None
    relation_proof: list[Sequence[Any]] | None
    relation_rows: list[Sequence[Any]] | None
    relation_summary: Evidence
    retired_skill_rows: list[Sequence[Any]] | None
    reviewed: list[Sequence[Any]] | None
    riding_defaults: Evidence | None
    riding_items: Evidence | None
    riding_scope: list[int] | None
    riding_sources: dict[str, str] | None
    scripted_families: set[int]
    selected: list[SpellRow]
    selected_offhand_capture: Evidence | None
    specialization_native_sources: dict[str, str] | None
    training_proofs: list[Evidence] | None


@dataclass
class HistorySnapshot:
    """Verified full-row fingerprints and source table layout."""

    after: list[tuple[str, int, int, str]]
    cells: list[tuple[str, int, int, str]]
    counts: dict[str, int]
    live: DatabaseState
    meta: DatabaseState
    source: str


@dataclass
class HistoryBatch:
    """Identity and template of one reviewed cleanup package."""

    archive: str
    batch: str
    template: Path
