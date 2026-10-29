"""Coordinate the ordered history-planning stages."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal, TYPE_CHECKING

from cleanup_history_evidence import (
    capture_history_evidence,
    resolve_history_policy,
    verify_history_evidence,
)
from cleanup_history_options import resolve_history_options
from cleanup_history_package import build_history_batch, build_history_manifest
from cleanup_history_publication import publish_history_package
from cleanup_history_selection import (
    report_history_selection,
    select_history_candidates,
)
from cleanup_history_snapshot import capture_history_snapshot
from cleanup_history_sql import build_history_sql_values

if TYPE_CHECKING:
    from cleanup_config import Settings
    from cleanup_workspace import Workspace


def plan_history(
    settings: Settings,
    work: Workspace,
    args: argparse.Namespace,
    output: Path,
) -> Literal[False] | None:
    options = resolve_history_options(settings, args)
    evidence = capture_history_evidence(settings, work, args, options)
    policy = resolve_history_policy(settings, args, options)
    selection = select_history_candidates(settings, work, args, options,
        evidence, policy)
    if selection is False:
        return False
    snapshot = capture_history_snapshot(settings, evidence, options, selection,
        policy)
    batch = build_history_batch(output, options, snapshot, selection, evidence,
        policy)
    values = build_history_sql_values(settings, work, options, snapshot, batch,
        evidence, selection, policy)
    verify_history_evidence(settings, options, evidence, selection, snapshot,
        policy)
    manifest = build_history_manifest(options, batch, evidence, snapshot,
        selection, policy, values)
    publish_history_package(settings, work, output, batch, selection, options,
        policy, manifest, snapshot, values, evidence)
    report_history_selection(args, options, selection, policy, manifest)
