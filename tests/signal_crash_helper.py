from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from codex_wake.event_wake import EventWake
from codex_wake.signal_records import (
    ManagedReaderCapability,
    WakeRecordPublisher,
    signal_journal_path,
)
from codex_wake.signal_store import SQLiteSignalModule
from codex_wake.signals import EvaluationLimits, SourceCommit
from codex_wake.records import archive_record, cancel_record, cleanup_archived_records
from tests.test_signal_store import make_observation
from tests.test_signals import make_adapter, make_intent


NOW = datetime(2026, 9, 14, 14, 0, tzinfo=UTC)


def publisher(root: Path, checkpoint=None) -> WakeRecordPublisher:
    return WakeRecordPublisher(
        root,
        ManagedReaderCapability(root, "crash-reader", 1, frozenset({1, 2}), True),
        checkpoint=checkpoint,
    )


def crash_at(expected: str):
    def checkpoint(name: str) -> None:
        if name == expected:
            os._exit(91)

    return checkpoint


def register(
    root: Path,
    *,
    expires: bool = False,
    checkpoint_name: str | None = None,
) -> SQLiteSignalModule:
    checkpoint = crash_at(checkpoint_name) if checkpoint_name else None
    module = SQLiteSignalModule(
        signal_journal_path(root),
        record_publisher=publisher(root, checkpoint),
        checkpoint=checkpoint,
        source_lease_seconds=30,
        lease_clock=lambda: NOW,
    )
    intent = make_intent()
    if expires:
        intent = replace(intent, expires_at=NOW + timedelta(seconds=1))
    EventWake(
        module,
        adapters=[make_adapter()],
        clock=lambda: NOW,
        id_factory=lambda: "wake_signal",
    ).register(intent, idempotency_key="job-42")
    return module


def ingest(module: SQLiteSignalModule) -> None:
    module.ingest(
        [make_observation()],
        SourceCommit("memory", "contract-test", "checkpoint-1", 1, NOW),
    )


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    mode = sys.argv[2]
    registration_checkpoints = {
        "prepared_before": "before_prepared_commit",
        "prepared_after": "after_prepared_commit",
        "temp_write": "after_temp_write",
        "registration_replace": "after_replace",
        "before_published": "before_published_commit",
        "published_after": "after_published_commit",
    }
    if mode in registration_checkpoints:
        register(root, checkpoint_name=registration_checkpoints[mode])
    elif mode in {"ingest_before", "ingest_after"}:
        register(root)
        expected = "before_ingest_commit" if mode.endswith("before") else "after_ingest_commit"
        module = SQLiteSignalModule(
            signal_journal_path(root),
            record_publisher=publisher(root),
            checkpoint=crash_at(expected),
        )
        ingest(module)
    elif mode == "reservation_after":
        module = register(root)
        ingest(module)
        module = SQLiteSignalModule(
            signal_journal_path(root),
            record_publisher=publisher(root),
            checkpoint=crash_at("after_match_reservation_commit"),
        )
        armed = module.load_armed_signal("wake_signal")
        module.evaluate("wake_signal", armed, NOW, EvaluationLimits(10))
    elif mode == "firing_after_replace":
        module = register(root)
        ingest(module)
        armed = module.load_armed_signal("wake_signal")
        module.evaluate("wake_signal", armed, NOW, EvaluationLimits(10))
        module = SQLiteSignalModule(
            signal_journal_path(root),
            record_publisher=publisher(root, crash_at("after_firing_replace")),
        )
        module.reconcile_publications()
    elif mode == "terminal_after":
        module = register(root)
        pending = json.loads((root / "pending" / "wake_signal.json").read_text())
        terminal = dict(pending)
        terminal["status"] = "cancelled"
        terminal["record_revision"] = 2
        module = SQLiteSignalModule(
            signal_journal_path(root),
            checkpoint=crash_at("after_terminal_commit"),
        )
        module.retire_terminal_record(terminal, now=NOW)
    elif mode == "expiry_after":
        register(root, expires=True)
        module = SQLiteSignalModule(
            signal_journal_path(root),
            checkpoint=crash_at("after_expiry_commit"),
        )
        module.expire_unreserved("wake_signal", now=NOW + timedelta(seconds=2))
    elif mode == "archive_after":
        register(root)
        cancel_record(root, "wake_signal", now=NOW)
        archive_record(
            root,
            "wake_signal",
            now=NOW,
            checkpoint=crash_at("after_archive_replace"),
        )
    elif mode == "cleanup_after":
        register(root)
        cancel_record(root, "wake_signal", now=NOW)
        archive_record(root, "wake_signal", now=NOW)
        cleanup_archived_records(
            root,
            older_than=timedelta(seconds=1),
            now=NOW + timedelta(seconds=2),
            delete=True,
            checkpoint=crash_at("after_cleanup_unlink"),
        )
    elif mode == "retention_after":
        module = register(root)
        ingest(module)
        module.release_retention_pins(
            "wake_signal", reasons=frozenset({"active_anchor"}), released_at=NOW
        )
        module = SQLiteSignalModule(
            signal_journal_path(root), checkpoint=crash_at("after_compaction_commit")
        )
        module.compact_receipts(through_sequence=1, limit=1, now=NOW)
    elif mode == "migration_before":
        from tests.test_signal_records import SignalRecordPublicationTests

        database = signal_journal_path(root)
        SQLiteSignalModule(database)
        SignalRecordPublicationTests._downgrade_empty_journal_to_v1(database)
        SQLiteSignalModule(
            database, checkpoint=crash_at("before_migration_commit")
        )
    raise SystemExit(f"checkpoint did not exit for mode {mode}")


if __name__ == "__main__":
    main()
