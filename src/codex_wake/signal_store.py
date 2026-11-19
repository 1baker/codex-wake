from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Sequence

from .signal_records import WakeRecordPublisher, build_signal_record, decode_signal_record
from .signals import (
    ArmContext,
    ArmId,
    ArmedSignal,
    Degraded,
    Eq,
    EvaluationLimits,
    EvidenceSummary,
    Expired,
    In,
    Ingested,
    Invalid,
    Matched,
    MatchToken,
    NormalizedObservation,
    NotReady,
    ReceiptId,
    ReceiptRef,
    Resume,
    SignalEngine,
    SignalRequest,
    SourceAnchor,
    SourceCommit,
    SourceContract,
    Verification,
    WakeId,
    _matches,
    _occurrence_is_after_anchor,
    _validate_occurrence_anchor,
    _validate_signal,
)


JOURNAL_SCHEMA_VERSION = 2
JOURNAL_APPLICATION_ID = 0x4357414B  # CWAK


class SignalStoreError(RuntimeError):
    """Raised when a journal cannot be opened without risking stored state."""


@dataclass(frozen=True, slots=True)
class JournalStatus:
    schema_version: int
    journal_uuid: str
    journal_mode: str
    synchronous: int
    foreign_keys: bool


@dataclass(frozen=True, slots=True)
class RetentionPin:
    pin_id: str
    wake_id: WakeId
    receipt_id: ReceiptId | None
    min_local_sequence: int | None
    reason: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PinRelease:
    released: int


@dataclass(frozen=True, slots=True)
class CompactionResult:
    scanned: int
    deleted: int
    retained: int


def pending_signal_targets(database: Path) -> list[dict[str, Any]]:
    """Read pending registration targets, including unpublished records.

    This inspection neither initializes nor migrates an existing journal and
    excludes prompt bodies from its result.
    """
    if not database.exists():
        return []
    connection = None
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro',
                                     uri=True, timeout=1)
        rows = connection.execute(
            "SELECT a.wake_id, a.resume_json, a.state FROM arms a "
            "LEFT JOIN wake_lifecycle l ON a.wake_id=l.wake_id "
            "WHERE a.state!='tombstoned' AND "
            "(l.desired_status IS NULL OR l.desired_status IN ('pending','firing'))"
        ).fetchall()
        return [dict(wake_id=identifier, target=json.loads(resume)['target'],
                     publication_state=state) for identifier, resume, state in rows]
    except (sqlite3.Error, ValueError, KeyError, TypeError):
        raise SignalStoreError('pending signal target inventory unavailable') from None
    finally:
        _close_quietly(connection)


class SQLiteSignalModule(SignalEngine):
    """SQLite adapter at the accepted WakeSignalModule seam."""

    def __init__(
        self,
        database: Path,
        *,
        busy_timeout_ms: int = 5_000,
        source_lease_seconds: int = 30,
        lease_clock: Callable[[], datetime] | None = None,
        record_publisher: WakeRecordPublisher | None = None,
        checkpoint: Callable[[str], None] | None = None,
        create: bool = True,
    ) -> None:
        self._database = Path(database)
        self._busy_timeout_ms = busy_timeout_ms
        self._source_lease_seconds = source_lease_seconds
        self._lease_clock = lease_clock
        self._record_publisher = record_publisher
        self._checkpoint = checkpoint or (lambda _name: None)
        if not create and not self._database.is_file():
            raise SignalStoreError("signal journal does not exist")
        try:
            if create:
                self._database.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise SignalStoreError("signal journal initialization failed") from None
        self._initialize()

    def _clock_bounds(self) -> tuple[datetime, datetime]:
        if self._lease_clock is not None:
            point = self._lease_clock()
            return point, point
        from .measurements import utc_bounds
        lower, upper = utc_bounds()
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        # Datetime stores microseconds; round outward so quantization cannot
        # extend a lease or establish an early reclaim/continuation decision.
        return (
            epoch + timedelta(microseconds=math.floor(Fraction(lower) * 1_000_000)),
            epoch + timedelta(microseconds=math.ceil(Fraction(upper) * 1_000_000)),
        )

    def _clock_upper(self) -> datetime:
        return self._clock_bounds()[1]

    @classmethod
    def open_existing(
        cls,
        database: Path,
        **kwargs: Any,
    ) -> SQLiteSignalModule | None:
        path = Path(database)
        if not path.is_file():
            return None
        return cls(path, create=False, **kwargs)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database,
            timeout=self._busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                self._database,
                timeout=self._busy_timeout_ms / 1000,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
            application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
            user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if application_id not in (0, JOURNAL_APPLICATION_ID):
                raise SignalStoreError("signal journal has an unexpected application id")
            existing_objects = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type IN ('table', 'index', 'view', 'trigger')
                  AND name NOT LIKE 'sqlite_%'
                LIMIT 1
                """
            ).fetchone()
            if application_id == 0 and existing_objects is not None:
                raise SignalStoreError("refusing to adopt a nonempty unowned SQLite database")
            if user_version > JOURNAL_SCHEMA_VERSION:
                raise SignalStoreError("signal journal schema is newer than this runtime")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA foreign_keys = ON")
            if user_version == 1:
                self._migrate_v1_to_v2(connection)
            elif user_version == 0:
                now = _format_time(self._clock_upper())
                connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA + "\nCOMMIT;")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO journal_meta(
                        singleton, schema_version, next_sequence, created_at,
                        migrated_at, journal_uuid
                    ) VALUES (1, ?, 1, ?, ?, ?)
                    ON CONFLICT(singleton) DO NOTHING
                    """,
                    (JOURNAL_SCHEMA_VERSION, now, now, uuid.uuid4().hex),
                )
                connection.execute(f"PRAGMA application_id = {JOURNAL_APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version = {JOURNAL_SCHEMA_VERSION}")
                connection.commit()
            stored_version = int(
                connection.execute(
                    "SELECT schema_version FROM journal_meta WHERE singleton = 1"
                ).fetchone()[0]
            )
            if stored_version != JOURNAL_SCHEMA_VERSION:
                raise SignalStoreError("unsupported signal journal schema version")
            foreign_key_error = connection.execute("PRAGMA foreign_key_check").fetchone()
            if foreign_key_error is not None:
                raise SignalStoreError("signal journal migration failed foreign-key validation")
        except SignalStoreError:
            _rollback_quietly(connection)
            raise
        except Exception:
            _rollback_quietly(connection)
            raise SignalStoreError("signal journal initialization failed") from None
        finally:
            _close_quietly(connection)

    def _migrate_v1_to_v2(self, connection: sqlite3.Connection) -> None:
        migrated_at = _format_time(self._clock_upper())
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("ALTER TABLE journal_meta ADD COLUMN journal_uuid TEXT")
            journal_uuid = uuid.uuid4().hex
            connection.execute(
                "UPDATE journal_meta SET journal_uuid = ?, schema_version = ?, migrated_at = ? WHERE singleton = 1",
                (journal_uuid, JOURNAL_SCHEMA_VERSION, migrated_at),
            )
            _execute_sql_script(connection, _MIGRATION_V2_TABLES)
            rows = connection.execute("SELECT * FROM arms").fetchall()
            connection.execute("DROP TABLE arms")
            connection.execute("ALTER TABLE arms_v2 RENAME TO arms")
            for row in rows:
                state = "prepared" if row["state"] == "published" else "preparing"
                connection.execute(
                    """
                    INSERT INTO arms(
                        arm_id, wake_id, idempotency_key, intent_fingerprint, state,
                        contract_version, source, source_instance, kind, subject,
                        spec_json, resume_json, registered_at, expires_at,
                        local_after_sequence, source_anchor, baseline_json, recovery,
                        preparer_token, preparation_expires_at, prepared_at, published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["arm_id"], row["wake_id"], row["idempotency_key"],
                        row["intent_fingerprint"], state, row["contract_version"],
                        row["source"], row["source_instance"], row["kind"], row["subject"],
                        row["spec_json"], row["resume_json"], row["registered_at"],
                        row["expires_at"], row["local_after_sequence"], row["source_anchor"],
                        row["baseline_json"], row["recovery"],
                        row["preparer_token"] if state == "preparing" else None,
                        row["preparation_expires_at"] if state == "preparing" else None,
                        row["published_at"] if state == "prepared" else None,
                        None,
                    ),
                )
                if state == "prepared":
                    armed = _armed_from_row(connection.execute(
                        "SELECT * FROM arms WHERE wake_id = ?", (row["wake_id"],)
                    ).fetchone())
                    payload_json, payload_sha256 = build_signal_record(
                        armed,
                        _resume_from_json(row["resume_json"]),
                        journal_uuid=journal_uuid,
                        revision=1,
                    )
                    connection.execute(
                        "INSERT INTO wake_lifecycle(wake_id, desired_status, desired_revision, updated_at) VALUES (?, 'pending', 1, ?)",
                        (row["wake_id"], row["published_at"]),
                    )
                    connection.execute(
                        """
                        INSERT INTO record_outbox(
                            wake_id, revision, operation, target_status, payload_json,
                            payload_sha256, state, created_at
                        ) VALUES (?, 1, 'put', 'pending', ?, ?, 'pending', ?)
                        """,
                        (row["wake_id"], payload_json, payload_sha256, row["published_at"]),
                    )
            connection.execute(f"PRAGMA user_version = {JOURNAL_SCHEMA_VERSION}")
            self._checkpoint("before_migration_commit")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    def journal_status(self) -> JournalStatus | Degraded:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            journal_uuid = connection.execute(
                "SELECT journal_uuid FROM journal_meta WHERE singleton = 1"
            ).fetchone()[0]
            return JournalStatus(
                schema_version=int(connection.execute("PRAGMA user_version").fetchone()[0]),
                journal_uuid=str(journal_uuid),
                journal_mode=str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
                synchronous=int(connection.execute("PRAGMA synchronous").fetchone()[0]),
                foreign_keys=bool(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
            )
        except Exception:
            return Degraded(None, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def retention_pins(
        self,
        wake_id: WakeId | None = None,
    ) -> tuple[RetentionPin, ...] | Degraded:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            if wake_id is None:
                rows = connection.execute(
                    """
                    SELECT * FROM retention_pins
                    WHERE released_at IS NULL
                    ORDER BY created_at, pin_id
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM retention_pins
                    WHERE wake_id = ? AND released_at IS NULL
                    ORDER BY created_at, pin_id
                    """,
                    (str(wake_id),),
                ).fetchall()
            return tuple(
                RetentionPin(
                    pin_id=row["pin_id"],
                    wake_id=WakeId(row["wake_id"]),
                    receipt_id=ReceiptId(row["receipt_id"]) if row["receipt_id"] else None,
                    min_local_sequence=(
                        int(row["min_local_sequence"])
                        if row["min_local_sequence"] is not None
                        else None
                    ),
                    reason=row["reason"],
                    created_at=_parse_time(row["created_at"]),
                )
                for row in rows
            )
        except Exception:
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def release_retention_pins(
        self,
        wake_id: WakeId,
        *,
        reasons: frozenset[str],
        released_at: datetime,
    ) -> PinRelease | Degraded:
        allowed = {"active_anchor", "verification_pending", "match_evidence"}
        if not reasons or not reasons <= allowed:
            return Degraded(wake_id, "INVALID_RETENTION_REQUEST", None)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            placeholders = ",".join("?" for _ in reasons)
            cursor = connection.execute(
                f"""
                UPDATE retention_pins SET released_at = ?
                WHERE wake_id = ? AND released_at IS NULL
                  AND reason IN ({placeholders})
                """,
                (_format_time(released_at), str(wake_id), *sorted(reasons)),
            )
            connection.commit()
            return PinRelease(cursor.rowcount)
        except Exception:
            _rollback_quietly(connection)
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def compact_receipts(
        self,
        *,
        through_sequence: int,
        limit: int,
        now: datetime,
    ) -> CompactionResult | Degraded:
        if through_sequence < 0 or limit <= 0:
            return Degraded(None, "INVALID_RETENTION_REQUEST", None)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT receipt_id, local_sequence FROM receipts
                WHERE local_sequence <= ?
                ORDER BY local_sequence
                LIMIT ?
                """,
                (through_sequence, limit),
            ).fetchall()
            deleted = retained = 0
            for row in rows:
                pinned = connection.execute(
                    """
                    SELECT 1 FROM retention_pins
                    WHERE released_at IS NULL
                      AND (
                        receipt_id = ?
                        OR (
                          min_local_sequence IS NOT NULL
                          AND min_local_sequence <= ?
                        )
                      )
                    LIMIT 1
                    """,
                    (row["receipt_id"], int(row["local_sequence"])),
                ).fetchone()
                if pinned is not None:
                    retained += 1
                    continue
                connection.execute(
                    "DELETE FROM retention_pins WHERE receipt_id = ? AND released_at IS NOT NULL",
                    (row["receipt_id"],),
                )
                connection.execute(
                    "UPDATE match_reservations SET receipt_id = NULL WHERE receipt_id = ?",
                    (row["receipt_id"],),
                )
                connection.execute(
                    "DELETE FROM receipts WHERE receipt_id = ?",
                    (row["receipt_id"],),
                )
                deleted += 1
            self._checkpoint("before_compaction_commit")
            connection.commit()
            self._checkpoint("after_compaction_commit")
            return CompactionResult(len(rows), deleted, retained)
        except Exception:
            _rollback_quietly(connection)
            return Degraded(None, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def arm(
        self,
        wake_id: WakeId,
        spec: SignalRequest,
        context: ArmContext,
    ) -> ArmedSignal | Degraded | Invalid:
        try:
            contract = context.adapter.contract()
        except Exception:
            return Degraded(wake_id, "SOURCE_UNAVAILABLE", None)
        try:
            invalid = _validate_signal(spec, contract)
        except Exception:
            return Degraded(wake_id, "SOURCE_UNAVAILABLE", None)
        if invalid is not None:
            return invalid
        try:
            spec_json = _canonical_json(_spec_payload(spec))
            resume_json = _canonical_json(_resume_payload(context))
            contract_json = _canonical_json(_contract_payload(contract))
        except (KeyError, TypeError, ValueError):
            return Invalid(wake_id, "INVALID_SIGNAL", ("signal specification is invalid",))
        contract_fingerprint = _fingerprint(contract_json)
        owner = uuid.uuid4().hex
        try:
            lease_now, lease_upper = self._clock_bounds()
            lease_expires = lease_now + timedelta(seconds=self._source_lease_seconds)
        except Exception:
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        arm_id = f"arm_{wake_id}"
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM arms WHERE idempotency_key = ?",
                (context.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["intent_fingerprint"] != context.intent_fingerprint:
                    connection.rollback()
                    return Invalid(
                        WakeId(existing["wake_id"]),
                        "IDEMPOTENCY_CONFLICT",
                        ("idempotency key already used",),
                    )
                if existing["state"] in {"prepared", "published"}:
                    connection.rollback()
                    return self._complete_registration_publication(WakeId(existing["wake_id"]))
                if existing["state"] == "tombstoned":
                    connection.rollback()
                    return Invalid(
                        WakeId(existing["wake_id"]),
                        "REGISTRATION_RETIRED",
                        ("registration is no longer active",),
                    )
                preparation_expires = (
                    _parse_time(existing["preparation_expires_at"])
                    if existing["preparation_expires_at"]
                    else None
                )
                if (
                    existing["preparer_token"]
                    and preparation_expires is not None
                    and preparation_expires > lease_now
                ):
                    connection.rollback()
                    return Degraded(
                        WakeId(existing["wake_id"]),
                        "REGISTRATION_IN_PROGRESS",
                        preparation_expires,
                    )
                wake_id = WakeId(existing["wake_id"])
                arm_id = existing["arm_id"]

            stored_contract = connection.execute(
                """
                SELECT contract_fingerprint FROM source_instances
                WHERE source = ? AND source_instance = ?
                """,
                (contract.source, contract.source_instance),
            ).fetchone()
            if stored_contract is not None and stored_contract["contract_fingerprint"] != contract_fingerprint:
                connection.rollback()
                return Invalid(
                    wake_id,
                    "SOURCE_CONTRACT_CONFLICT",
                    ("source instance contract conflicts with durable state",),
                )
            connection.execute(
                """
                INSERT INTO source_instances(
                    source, source_instance, contract_json, contract_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source, source_instance) DO NOTHING
                """,
                (
                    contract.source,
                    contract.source_instance,
                    contract_json,
                    contract_fingerprint,
                    _format_time(context.registered_at),
                ),
            )
            connection.execute(
                """
                INSERT INTO source_state(source, source_instance)
                VALUES (?, ?)
                ON CONFLICT(source, source_instance) DO NOTHING
                """,
                (contract.source, contract.source_instance),
            )
            state = connection.execute(
                """
                SELECT * FROM source_state
                WHERE source = ? AND source_instance = ?
                """,
                (contract.source, contract.source_instance),
            ).fetchone()
            if state["lease_owner"] is not None and _parse_time(state["lease_expires_at"]) > lease_now:
                connection.rollback()
                return Degraded(wake_id, "SOURCE_BUSY", _parse_time(state["lease_expires_at"]))
            if lease_upper >= lease_expires:
                connection.rollback()
                return Degraded(wake_id, "SOURCE_LEASE_LOST", None)
            generation = int(state["lease_generation"]) + 1
            connection.execute(
                """
                UPDATE source_state
                SET lease_owner = ?, lease_generation = ?, lease_expires_at = ?
                WHERE source = ? AND source_instance = ?
                """,
                (
                    owner,
                    generation,
                    _format_time(lease_expires),
                    contract.source,
                    contract.source_instance,
                ),
            )
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO arms(
                        arm_id, wake_id, idempotency_key, intent_fingerprint, state,
                        contract_version, source, source_instance, kind, subject,
                        spec_json, resume_json, registered_at, expires_at,
                        preparer_token, preparation_expires_at
                    ) VALUES (?, ?, ?, ?, 'preparing', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        arm_id,
                        str(wake_id),
                        context.idempotency_key,
                        context.intent_fingerprint,
                        spec.contract_version,
                        spec.source,
                        spec.source_instance,
                        spec.kind,
                        spec.subject,
                        spec_json,
                        resume_json,
                        _format_time(context.registered_at),
                        _format_time(context.expires_at) if context.expires_at else None,
                        owner,
                        _format_time(lease_expires),
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE arms
                    SET preparer_token = ?, preparation_expires_at = ?
                    WHERE arm_id = ?
                    """,
                    (owner, _format_time(lease_expires), arm_id),
                )
            connection.commit()
        except Exception:
            _rollback_quietly(connection)
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

        try:
            if self._clock_upper() >= lease_expires:
                self._best_effort_release_preparation(
                    arm_id, contract.source, contract.source_instance, owner, generation
                )
                return Degraded(wake_id, "SOURCE_LEASE_LOST", None)
            anchor = context.adapter.establish_anchor(spec, context.registered_at)
        except Exception:
            self._best_effort_release_preparation(
                arm_id,
                contract.source,
                contract.source_instance,
                owner,
                generation,
            )
            return Degraded(wake_id, "SOURCE_UNAVAILABLE", None)
        if isinstance(anchor, (Degraded, Invalid)):
            self._best_effort_release_preparation(
                arm_id,
                contract.source,
                contract.source_instance,
                owner,
                generation,
            )
            if isinstance(anchor, Degraded):
                return Degraded(wake_id, anchor.code, anchor.retry_at, anchor.evidence_ref)
            return anchor

        invalid = _validate_occurrence_anchor(contract, spec, anchor)
        if invalid is not None:
            self._best_effort_release_preparation(arm_id, contract.source, contract.source_instance, owner, generation)
            return invalid

        connection = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            state = connection.execute(
                """
                SELECT * FROM source_state
                WHERE source = ? AND source_instance = ?
                """,
                (contract.source, contract.source_instance),
            ).fetchone()
            prepared = connection.execute(
                "SELECT * FROM arms WHERE arm_id = ?",
                (arm_id,),
            ).fetchone()
            if (
                state is None
                or prepared is None
                or state["lease_owner"] != owner
                or int(state["lease_generation"]) != generation
                or prepared["preparer_token"] != owner
            ):
                connection.rollback()
                return Degraded(wake_id, "SOURCE_LEASE_LOST", None)
            if self._clock_upper() >= lease_expires:
                connection.rollback()
                return Degraded(wake_id, "SOURCE_LEASE_LOST", None)
            effective_anchor = replace(
                anchor,
                local_after_sequence=max(
                    anchor.local_after_sequence,
                    int(state["last_local_sequence"]),
                ),
                baseline=MappingProxyType(dict(anchor.baseline)),
            )
            prepared_at = _format_time(context.registered_at)
            journal_uuid = str(
                connection.execute(
                    "SELECT journal_uuid FROM journal_meta WHERE singleton = 1"
                ).fetchone()[0]
            )
            prepared_arm = ArmedSignal(
                wake_id=wake_id,
                arm_id=ArmId(arm_id),
                spec=spec,
                anchor=effective_anchor,
                registered_at=context.registered_at,
                expires_at=context.expires_at,
                publication="prepared",
            )
            payload_json, payload_sha256 = build_signal_record(
                prepared_arm,
                context.resume,
                journal_uuid=journal_uuid,
                revision=1,
                max_attempts=context.max_attempts,
            )
            connection.execute(
                """
                UPDATE arms
                SET state = 'prepared', local_after_sequence = ?, source_anchor = ?,
                    baseline_json = ?, recovery = ?, prepared_at = ?, published_at = NULL,
                    preparer_token = NULL, preparation_expires_at = NULL
                WHERE arm_id = ?
                """,
                (
                    effective_anchor.local_after_sequence,
                    effective_anchor.source_anchor,
                    _canonical_json(dict(effective_anchor.baseline)),
                    effective_anchor.recovery,
                    prepared_at,
                    arm_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO evaluation_progress(wake_id, scanned_through_sequence, revision, updated_at)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(wake_id) DO NOTHING
                """,
                (str(wake_id), effective_anchor.local_after_sequence, prepared_at),
            )
            connection.execute(
                """
                INSERT INTO retention_pins(
                    pin_id, wake_id, min_local_sequence, reason, created_at
                ) VALUES (?, ?, ?, 'active_anchor', ?)
                ON CONFLICT(pin_id) DO NOTHING
                """,
                (
                    f"anchor:{wake_id}",
                    str(wake_id),
                    effective_anchor.local_after_sequence + 1,
                    prepared_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO wake_lifecycle(
                    wake_id, desired_status, desired_revision, updated_at
                ) VALUES (?, 'pending', 1, ?)
                ON CONFLICT(wake_id) DO NOTHING
                """,
                (str(wake_id), prepared_at),
            )
            connection.execute(
                """
                INSERT INTO record_outbox(
                    wake_id, revision, operation, target_status, payload_json,
                    payload_sha256, state, created_at
                ) VALUES (?, 1, 'put', 'pending', ?, ?, 'pending', ?)
                ON CONFLICT(wake_id, revision) DO NOTHING
                """,
                (str(wake_id), payload_json, payload_sha256, prepared_at),
            )
            connection.execute(
                """
                UPDATE source_state
                SET lease_owner = NULL, lease_expires_at = NULL
                WHERE source = ? AND source_instance = ?
                  AND lease_owner = ? AND lease_generation = ?
                """,
                (contract.source, contract.source_instance, owner, generation),
            )
            self._checkpoint("before_prepared_commit")
            if self._clock_upper() >= lease_expires:
                connection.rollback()
                return Degraded(wake_id, "SOURCE_LEASE_LOST", None)
            connection.commit()
            self._checkpoint("after_prepared_commit")
            return self._complete_registration_publication(wake_id)
        except Exception:
            _rollback_quietly(connection)
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def reconcile_publications(
        self,
        *,
        limit: int = 100,
        include_matches: bool = True,
    ) -> int | Degraded:
        if limit <= 0:
            return Degraded(None, "INVALID_PUBLICATION_LIMIT", None)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            rows = connection.execute(
                """
                SELECT wake_id FROM arms
                WHERE state IN ('prepared', 'published')
                ORDER BY registered_at, wake_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except Exception:
            return Degraded(None, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)
        applied = 0
        for row in rows:
            outcome = self._complete_registration_publication(WakeId(row["wake_id"]))
            if isinstance(outcome, ArmedSignal):
                applied += 1
        if not include_matches:
            return applied
        connection = None
        try:
            connection = self._connect()
            matches = connection.execute(
                """
                SELECT wake_id, revision FROM record_outbox
                WHERE revision > 1
                ORDER BY created_at, wake_id, revision
                LIMIT ?
                """,
                (max(0, limit - applied),),
            ).fetchall()
        except Exception:
            return Degraded(None, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)
        for row in matches:
            outcome = self._complete_match_publication(
                WakeId(row["wake_id"]), int(row["revision"])
            )
            if outcome is True:
                applied += 1
        return applied

    def reconcile_match_publication(self, wake_id: WakeId) -> bool | Degraded:
        """Apply only the reserved match projection for one lifecycle-locked wake."""

        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            row = connection.execute(
                """
                SELECT revision FROM record_outbox
                WHERE wake_id = ? AND revision > 1
                ORDER BY revision DESC LIMIT 1
                """,
                (str(wake_id),),
            ).fetchone()
            if row is None:
                return Degraded(wake_id, "FIRING_AUTHORITY_UNAVAILABLE", None)
            revision = int(row["revision"])
        except Exception:
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)
        return self._complete_match_publication(wake_id, revision)

    def _complete_match_publication(
        self,
        wake_id: WakeId,
        revision: int,
    ) -> bool | Degraded:
        publisher = self._record_publisher
        if publisher is None or publisher.capability_code() is not None:
            return Degraded(wake_id, "READER_CAPABILITY_UNAVAILABLE", None)
        connection: sqlite3.Connection | None = None
        try:
            self._clock_upper()
            connection = self._connect()
            row = connection.execute(
                """
                SELECT a.state AS arm_state, l.desired_status, l.desired_revision,
                       l.applied_status,
                       o.payload_json, o.payload_sha256, o.state AS outbox_state,
                       r.match_token,
                       EXISTS(
                           SELECT 1 FROM registration_tombstones AS t
                           WHERE t.wake_id = a.wake_id
                       ) AS terminal_fence
                FROM arms AS a
                JOIN wake_lifecycle AS l USING(wake_id)
                JOIN record_outbox AS o USING(wake_id)
                JOIN match_reservations AS r USING(wake_id)
                WHERE a.wake_id = ? AND o.revision = ?
                """,
                (str(wake_id), revision),
            ).fetchone()
            if (
                row is None
                or row["arm_state"] != "published"
                or row["desired_status"] != "firing"
                or int(row["desired_revision"]) != revision
                or row["applied_status"] in {"submitted", "failed", "cancelled", "expired", "archived"}
                or bool(row["terminal_fence"])
            ):
                return Degraded(wake_id, "FIRING_AUTHORITY_UNAVAILABLE", None)
            payload_json = str(row["payload_json"])
            payload_sha256 = str(row["payload_sha256"])
        except Exception:
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

        inspected = publisher.inspect(payload_json, payload_sha256)
        if inspected.outcome == "missing":
            inspected = publisher.apply(payload_json, payload_sha256)
            if inspected.outcome == "applied":
                inspected = publisher.inspect(payload_json, payload_sha256)
        elif inspected.outcome == "applied":
            inspected = publisher.apply(payload_json, payload_sha256)
        if inspected.outcome != "applied" or publisher.capability_code() is not None:
            return Degraded(wake_id, "WAKE_RECORD_PUBLICATION_FAILED", None)

        connection = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT a.state AS arm_state, l.desired_status, l.desired_revision,
                       l.applied_status,
                       o.payload_sha256, o.state AS outbox_state,
                       r.match_token,
                       EXISTS(
                           SELECT 1 FROM registration_tombstones AS t
                           WHERE t.wake_id = a.wake_id
                       ) AS terminal_fence
                FROM arms AS a
                JOIN wake_lifecycle AS l USING(wake_id)
                JOIN record_outbox AS o USING(wake_id)
                JOIN match_reservations AS r USING(wake_id)
                WHERE a.wake_id = ? AND o.revision = ?
                """,
                (str(wake_id), revision),
            ).fetchone()
            if (
                current is None
                or current["arm_state"] != "published"
                or current["desired_status"] != "firing"
                or int(current["desired_revision"]) != revision
                or current["applied_status"] in {"submitted", "failed", "cancelled", "expired", "archived"}
                or bool(current["terminal_fence"])
                or str(current["payload_sha256"]) != payload_sha256
                or publisher.capability_code() is not None
            ):
                connection.rollback()
                return Degraded(wake_id, "FIRING_AUTHORITY_UNAVAILABLE", None)
            applied_at = _format_time(self._clock_upper())
            connection.execute(
                """
                UPDATE record_outbox
                SET state = 'applied', applied_at = ?, blocked_code = NULL,
                    attempt_count = attempt_count + CASE WHEN state = 'applied' THEN 0 ELSE 1 END,
                    last_attempt_at = ?
                WHERE wake_id = ? AND revision = ?
                """,
                (applied_at, applied_at, str(wake_id), revision),
            )
            connection.execute(
                """
                UPDATE wake_lifecycle
                SET applied_status = 'firing', applied_revision = ?, updated_at = ?
                WHERE wake_id = ? AND desired_status = 'firing' AND desired_revision = ?
                """,
                (revision, applied_at, str(wake_id), revision),
            )
            connection.commit()
            return True
        except Exception:
            _rollback_quietly(connection)
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def _complete_registration_publication(
        self,
        wake_id: WakeId,
    ) -> ArmedSignal | Degraded | Invalid:
        publisher = self._record_publisher
        if publisher is None:
            return Degraded(wake_id, "WAKE_RECORD_PUBLISHER_UNAVAILABLE", None)
        capability_code = publisher.capability_code()
        if capability_code is not None:
            return Degraded(wake_id, capability_code, None)
        connection: sqlite3.Connection | None = None
        try:
            self._clock_upper()
            connection = self._connect()
            arm = connection.execute(
                "SELECT * FROM arms WHERE wake_id = ?", (str(wake_id),)
            ).fetchone()
            outbox = connection.execute(
                "SELECT * FROM record_outbox WHERE wake_id = ? AND revision = 1",
                (str(wake_id),),
            ).fetchone()
            lifecycle = connection.execute(
                "SELECT desired_status, desired_revision FROM wake_lifecycle WHERE wake_id = ?",
                (str(wake_id),),
            ).fetchone()
            if arm is None or outbox is None or lifecycle is None:
                return Invalid(wake_id, "ARM_STATE_UNAVAILABLE", ("arm publication state is unavailable",))
            if arm["state"] not in {"prepared", "published"}:
                return Degraded(wake_id, "ARM_NOT_PUBLISHED", None)
            if (
                lifecycle["desired_status"] != "pending"
                or int(lifecycle["desired_revision"]) != 1
            ):
                if arm["state"] == "published" and outbox["state"] == "applied":
                    return _armed_from_row(arm)
                return Degraded(wake_id, "ARM_NOT_PUBLISHED", None)
            payload_json = str(outbox["payload_json"])
            payload_sha256 = str(outbox["payload_sha256"])
        except Exception:
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

        inspected = publisher.inspect(payload_json, payload_sha256)
        if inspected.outcome == "missing":
            inspected = publisher.apply(payload_json, payload_sha256)
            if inspected.outcome == "applied":
                inspected = publisher.inspect(payload_json, payload_sha256)
        if inspected.outcome != "applied":
            code = (
                "WAKE_RECORD_CONFLICT"
                if inspected.outcome == "conflict"
                else "WAKE_RECORD_PUBLICATION_FAILED"
            )
            self._mark_publication_blocked(wake_id, code)
            return Degraded(wake_id, code, None)

        connection = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT state FROM arms WHERE wake_id = ?", (str(wake_id),)
            ).fetchone()
            if (
                current is None
                or current["state"] not in {"prepared", "published"}
                or publisher.capability_code() is not None
            ):
                connection.rollback()
                return Degraded(wake_id, "READER_CAPABILITY_UNAVAILABLE", None)
            applied_at = _format_time(self._clock_upper())
            connection.execute(
                """
                UPDATE record_outbox
                SET state = 'applied', applied_at = ?, blocked_code = NULL,
                    attempt_count = attempt_count + 1, last_attempt_at = ?
                WHERE wake_id = ? AND revision = 1
                """,
                (applied_at, applied_at, str(wake_id)),
            )
            connection.execute(
                """
                UPDATE wake_lifecycle
                SET applied_status = 'pending', applied_revision = 1, updated_at = ?
                WHERE wake_id = ? AND desired_status = 'pending' AND desired_revision = 1
                """,
                (applied_at, str(wake_id)),
            )
            connection.execute(
                "UPDATE arms SET state = 'published', published_at = COALESCE(published_at, ?) WHERE wake_id = ?",
                (applied_at, str(wake_id)),
            )
            row = connection.execute(
                "SELECT * FROM arms WHERE wake_id = ?", (str(wake_id),)
            ).fetchone()
            self._checkpoint("before_published_commit")
            connection.commit()
            self._checkpoint("after_published_commit")
            return _armed_from_row(row)
        except Exception:
            _rollback_quietly(connection)
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def _mark_publication_blocked(self, wake_id: WakeId, code: str) -> None:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            now = _format_time(self._clock_upper())
            connection.execute(
                """
                UPDATE record_outbox
                SET state = 'blocked', blocked_code = ?,
                    attempt_count = attempt_count + 1, last_attempt_at = ?
                WHERE wake_id = ? AND revision = 1
                """,
                (code, now, str(wake_id)),
            )
            connection.commit()
        except Exception:
            _rollback_quietly(connection)
        finally:
            _close_quietly(connection)

    def _release_preparation(
        self,
        arm_id: str,
        source: str,
        source_instance: str,
        owner: str,
        generation: int,
    ) -> bool:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE arms SET preparer_token = NULL, preparation_expires_at = NULL
                WHERE arm_id = ? AND preparer_token = ?
                """,
                (arm_id, owner),
            )
            connection.execute(
                """
                UPDATE source_state SET lease_owner = NULL, lease_expires_at = NULL
                WHERE source = ? AND source_instance = ?
                  AND lease_owner = ? AND lease_generation = ?
                """,
                (source, source_instance, owner, generation),
            )
            connection.commit()
            return True
        except Exception:
            _rollback_quietly(connection)
            return False
        finally:
            _close_quietly(connection)

    def _best_effort_release_preparation(
        self,
        arm_id: str,
        source: str,
        source_instance: str,
        owner: str,
        generation: int,
    ) -> None:
        try:
            self._release_preparation(
                arm_id,
                source,
                source_instance,
                owner,
                generation,
            )
        except Exception:
            return

    def load_armed_signal(self, wake_id: WakeId) -> ArmedSignal | None:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            row = connection.execute(
                "SELECT * FROM arms WHERE wake_id = ? AND state = 'published'",
                (str(wake_id),),
            ).fetchone()
            return _armed_from_row(row) if row is not None else None
        except Exception:
            return None
        finally:
            _close_quietly(connection)

    def authorize_firing_record(self, record: object) -> bool:
        decoded = decode_signal_record(record)
        if decoded is None or decoded.get("status") != "firing":
            return False
        connection: sqlite3.Connection | None = None
        try:
            wake_id = str(decoded["id"])
            revision = int(decoded["record_revision"])
            connection = self._connect()
            row = connection.execute(
                """
                SELECT a.arm_id, a.state AS arm_state, m.match_token,
                       l.desired_status, l.desired_revision,
                       l.applied_status, l.applied_revision,
                       o.state AS outbox_state, o.payload_json, j.journal_uuid
                FROM arms AS a
                JOIN match_reservations AS m USING(wake_id)
                JOIN wake_lifecycle AS l USING(wake_id)
                JOIN record_outbox AS o USING(wake_id)
                JOIN journal_meta AS j ON j.singleton = 1
                WHERE a.wake_id = ? AND o.revision = ?
                """,
                (wake_id, revision),
            ).fetchone()
            if row is None:
                return False
            expected = json.loads(str(row["payload_json"]))
            trigger = decoded.get("trigger_match")
            return bool(
                row["arm_state"] == "published"
                and decoded == expected
                and decoded.get("arm_id") == row["arm_id"]
                and decoded.get("journal_uuid") == row["journal_uuid"]
                and row["desired_status"] == "firing"
                and int(row["desired_revision"]) == revision
                and row["applied_status"] == "firing"
                and int(row["applied_revision"]) == revision
                and row["outbox_state"] == "applied"
                and isinstance(trigger, dict)
                and trigger == expected.get("trigger_match")
                and trigger.get("match_token") == row["match_token"]
            )
        except Exception:
            return False
        finally:
            _close_quietly(connection)

    def inspect_signal_state(
        self,
        wake_id: WakeId,
        *,
        record: object | None = None,
    ) -> dict[str, Any] | Degraded:
        """Return bounded authority metadata without evaluating or mutating."""

        decoded = decode_signal_record(record) if record is not None else None
        if record is not None and decoded is None:
            return Degraded(wake_id, "WAKE_RECORD_INVALID", None)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            journal = connection.execute(
                "SELECT journal_uuid FROM journal_meta WHERE singleton = 1"
            ).fetchone()
            arm = connection.execute(
                "SELECT wake_id, arm_id, state, source, source_instance, expires_at, baseline_json FROM arms WHERE wake_id = ?",
                (str(wake_id),),
            ).fetchone()
            source_state = None
            if arm is not None:
                source_state = connection.execute(
                    "SELECT checkpoint FROM source_state WHERE source = ? AND source_instance = ?",
                    (arm["source"], arm["source_instance"]),
                ).fetchone()
            lifecycle = connection.execute(
                "SELECT desired_status, desired_revision, applied_status, applied_revision FROM wake_lifecycle WHERE wake_id = ?",
                (str(wake_id),),
            ).fetchone()
            reservation = connection.execute(
                "SELECT receipt_id, match_token, matched_at, evidence_json FROM match_reservations WHERE wake_id = ?",
                (str(wake_id),),
            ).fetchone()
            outbox = connection.execute(
                "SELECT revision, operation, target_status, state, blocked_code FROM record_outbox WHERE wake_id = ? ORDER BY revision",
                (str(wake_id),),
            ).fetchall()
            pins = connection.execute(
                "SELECT pin_id, receipt_id, min_local_sequence, reason FROM retention_pins WHERE wake_id = ? AND released_at IS NULL ORDER BY pin_id",
                (str(wake_id),),
            ).fetchall()
            if arm is None or journal is None:
                return Degraded(wake_id, "ARM_STATE_UNAVAILABLE", None)
            journal_uuid = str(journal["journal_uuid"])
            degradation = None
            if decoded is not None and (
                decoded.get("id") != str(wake_id)
                or decoded.get("arm_id") != arm["arm_id"]
                or decoded.get("journal_uuid") != journal_uuid
            ):
                degradation = "WAKE_RECORD_AUTHORITY_MISMATCH"
            evidence = json.loads(str(reservation["evidence_json"])) if reservation else None
            source_evidence = None
            if arm["source"] == "filesystem":
                allowed = {
                    "matched", "exists", "file_kind", "fingerprint",
                    "baseline_fingerprint", "coalesced",
                    "observation_reason", "hint_count",
                }
                attributes = evidence.get("attributes") if evidence else None
                if not isinstance(attributes, dict) and source_state and source_state["checkpoint"]:
                    parsed_checkpoint = json.loads(str(source_state["checkpoint"]))
                    attributes = parsed_checkpoint if isinstance(parsed_checkpoint, dict) else None
                source_evidence = {
                    "baseline": json.loads(str(arm["baseline_json"])),
                    "observed": (
                        {name: attributes[name] for name in sorted(allowed) if name in attributes}
                        if isinstance(attributes, dict)
                        else None
                    ),
                }
            return {
                "wake_id": str(wake_id),
                "journal": {"schema_version": JOURNAL_SCHEMA_VERSION, "journal_uuid": journal_uuid},
                "record": {
                    "schema_version": decoded.get("schema_version") if decoded else None,
                    "record_revision": decoded.get("record_revision") if decoded else None,
                    "status": decoded.get("status") if decoded else None,
                },
                "arm": dict(arm),
                "lifecycle": dict(lifecycle) if lifecycle else None,
                "reservation": (
                    {
                        "receipt_id": reservation["receipt_id"],
                        "match_token": reservation["match_token"],
                        "matched_at": reservation["matched_at"],
                        "verification_state": evidence.get("verification_state"),
                        "verification_method": evidence.get("verification_method"),
                    }
                    if reservation
                    else None
                ),
                "outbox": [dict(row) for row in outbox[:16]],
                "pins": [dict(row) for row in pins[:32]],
                "source_evidence": source_evidence,
                "degradation": degradation,
            }
        except Exception:
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def retire_terminal_record(
        self,
        record: object,
        *,
        now: datetime | None,
    ) -> bool | Degraded:
        decoded = decode_signal_record(record)
        terminal_status = decoded.get("status") if decoded else None
        if decoded is None or terminal_status not in {
            "submitted", "failed", "cancelled", "expired", "archived"
        }:
            return Degraded(None, "TERMINAL_RECORD_INVALID", None)
        wake_id = WakeId(str(decoded["id"]))
        if now is None and terminal_status != 'cancelled':
            return Degraded(wake_id, 'TERMINAL_TIME_UNQUALIFIED', None)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            arm = connection.execute(
                "SELECT * FROM arms WHERE wake_id = ?", (str(wake_id),)
            ).fetchone()
            journal_uuid = connection.execute(
                "SELECT journal_uuid FROM journal_meta WHERE singleton = 1"
            ).fetchone()[0]
            if (
                arm is None
                or decoded.get("arm_id") != arm["arm_id"]
                or decoded.get("journal_uuid") != journal_uuid
            ):
                connection.rollback()
                return Degraded(wake_id, "TERMINAL_AUTHORITY_MISMATCH", None)
            if terminal_status == "expired":
                reservation = connection.execute(
                    "SELECT 1 FROM match_reservations WHERE wake_id = ?",
                    (str(wake_id),),
                ).fetchone()
                if reservation is not None:
                    connection.rollback()
                    return Degraded(wake_id, "MATCH_RESERVED", None)
            # This fence is an untimed stop, not a lease or retention deadline.
            # Empty text means unobserved time; NULL on released_at still means
            # an unreleased pin. Existing schema and presence checks stay valid.
            retired_at = '' if now is None else _format_time(now)
            connection.execute(
                "UPDATE arms SET state = 'tombstoned' WHERE wake_id = ?",
                (str(wake_id),),
            )
            connection.execute(
                """
                INSERT INTO registration_tombstones(
                    idempotency_key, intent_fingerprint, wake_id, terminal_status, retired_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    terminal_status = excluded.terminal_status,
                    retired_at = excluded.retired_at
                """,
                (
                    arm["idempotency_key"], arm["intent_fingerprint"], str(wake_id),
                    terminal_status, retired_at,
                ),
            )
            revision = int(decoded["record_revision"])
            connection.execute(
                """
                UPDATE wake_lifecycle
                SET desired_status = ?, desired_revision = MAX(desired_revision, ?),
                    applied_status = ?, applied_revision = MAX(COALESCE(applied_revision, 0), ?),
                    updated_at = ?
                WHERE wake_id = ?
                """,
                (terminal_status, revision, terminal_status, revision, retired_at, str(wake_id)),
            )
            connection.execute(
                "UPDATE retention_pins SET released_at = ? WHERE wake_id = ? AND released_at IS NULL",
                (retired_at, str(wake_id)),
            )
            self._checkpoint("before_terminal_commit")
            connection.commit()
            self._checkpoint("after_terminal_commit")
            if self._record_publisher is not None:
                self._record_publisher.remove_superseded_pending(decoded)
            return True
        except Exception:
            _rollback_quietly(connection)
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def expire_unreserved(self, wake_id: WakeId, *, now: datetime) -> bool | Degraded:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            arm = connection.execute(
                "SELECT * FROM arms WHERE wake_id = ?", (str(wake_id),)
            ).fetchone()
            reservation = connection.execute(
                "SELECT 1 FROM match_reservations WHERE wake_id = ?", (str(wake_id),)
            ).fetchone()
            if (
                arm is None
                or arm["state"] != "published"
                or arm["expires_at"] is None
                or _parse_time(arm["expires_at"]) > now
                or reservation is not None
            ):
                connection.rollback()
                return False
            retired_at = _format_time(now)
            connection.execute(
                "UPDATE arms SET state = 'tombstoned' WHERE wake_id = ?", (str(wake_id),)
            )
            connection.execute(
                """
                INSERT INTO registration_tombstones(
                    idempotency_key, intent_fingerprint, wake_id, terminal_status, retired_at
                ) VALUES (?, ?, ?, 'expired', ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (arm["idempotency_key"], arm["intent_fingerprint"], str(wake_id), retired_at),
            )
            connection.execute(
                """
                UPDATE wake_lifecycle SET desired_status = 'expired', applied_status = 'expired',
                    updated_at = ? WHERE wake_id = ?
                """,
                (retired_at, str(wake_id)),
            )
            connection.execute(
                "UPDATE retention_pins SET released_at = ? WHERE wake_id = ? AND released_at IS NULL",
                (retired_at, str(wake_id)),
            )
            self._checkpoint("before_expiry_commit")
            connection.commit()
            self._checkpoint("after_expiry_commit")
            return True
        except Exception:
            _rollback_quietly(connection)
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def terminal_status(self, wake_id: WakeId) -> str | None:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            row = connection.execute(
                "SELECT terminal_status FROM registration_tombstones WHERE wake_id = ?",
                (str(wake_id),),
            ).fetchone()
            return str(row["terminal_status"]) if row else None
        except Exception:
            return None
        finally:
            _close_quietly(connection)

    def cleanup_allowed(self, record: object) -> bool:
        decoded = decode_signal_record(record)
        if decoded is None or decoded.get("status") != "archived":
            return False
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            wake_id = str(decoded["id"])
            arm = connection.execute(
                "SELECT state FROM arms WHERE wake_id = ?", (wake_id,)
            ).fetchone()
            tombstone = connection.execute(
                "SELECT 1 FROM registration_tombstones WHERE wake_id = ?", (wake_id,)
            ).fetchone()
            pin = connection.execute(
                "SELECT 1 FROM retention_pins WHERE wake_id = ? AND released_at IS NULL LIMIT 1",
                (wake_id,),
            ).fetchone()
            return bool(arm and arm["state"] == "tombstoned" and tombstone and pin is None)
        except Exception:
            return False
        finally:
            _close_quietly(connection)

    def cleanup_diagnostic(self, record: object) -> dict[str, Any]:
        """Explain why an archived signal record is protected from cleanup."""

        decoded = decode_signal_record(record)
        if decoded is None or decoded.get("status") != "archived":
            return {
                "allowed": False,
                "reasons": ["record_not_archived_signal"],
                "repair": "archive a valid terminal signal record before cleanup",
            }
        wake_id = str(decoded["id"])
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            arm = connection.execute(
                "SELECT state FROM arms WHERE wake_id = ?", (wake_id,)
            ).fetchone()
            tombstone = connection.execute(
                "SELECT 1 FROM registration_tombstones WHERE wake_id = ?", (wake_id,)
            ).fetchone()
            pins = connection.execute(
                "SELECT reason FROM retention_pins WHERE wake_id = ? AND released_at IS NULL ORDER BY reason",
                (wake_id,),
            ).fetchall()
        except Exception:
            return {
                "allowed": False,
                "reasons": ["journal_unavailable"],
                "repair": "preserve the record and repair or restore the signal journal before cleanup",
            }
        finally:
            _close_quietly(connection)
        reasons = [str(row["reason"]) for row in pins]
        if arm is None or arm["state"] != "tombstoned" or tombstone is None:
            reasons.append("registration_not_retired")
        reasons = sorted(set(reasons))
        return {
            "allowed": not reasons,
            "reasons": reasons,
            "repair": (
                ""
                if not reasons
                else f"run `codex-wake --wake-root <path> archive {wake_id}` again after verifying the signal journal is writable"
            ),
        }

    @classmethod
    def read_committed_occurrences(cls, database, source, source_instance, namespace, occurrence_ids):
        """Bounded immutable occurrence proof, without initialization or migration."""
        import os
        import stat
        connection = None
        try:
            if (type(occurrence_ids) not in (list, tuple) or len(occurrence_ids) > 100
                    or any(type(value) is not str or not value or len(value.encode()) > 256
                           for value in occurrence_ids)):
                raise ValueError()
            path = Path(database).absolute()
            info = path.lstat()
            if (path != path.resolve() or not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid() or info.st_mode & 0o022):
                raise ValueError()
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            if (connection.execute("PRAGMA application_id").fetchone()[0] != JOURNAL_APPLICATION_ID
                    or connection.execute("PRAGMA user_version").fetchone()[0] != JOURNAL_SCHEMA_VERSION):
                raise ValueError()
            meta = connection.execute("SELECT journal_uuid FROM journal_meta WHERE singleton=1").fetchone()
            if meta is None or not isinstance(meta[0], str) or not meta[0]:
                raise ValueError()
            source_row = connection.execute(
                'SELECT contract_json FROM source_instances WHERE source=? AND source_instance=?',
                (source, source_instance)).fetchone()
            if source_row is None:
                raise ValueError()
            contract = _contract_from_json(source_row[0])
            values = {}
            if occurrence_ids:
                placeholders = ','.join('?' for _ in occurrence_ids)
                rows = connection.execute(
                    'SELECT * FROM receipts WHERE source=? AND source_instance=? AND occurrence_namespace=? '
                    'AND occurrence_value IN (' + placeholders + ')',
                    (source, source_instance, namespace, *occurrence_ids)).fetchall()
                for row in rows:
                    observation = _observation_from_json(row['observation_json'])
                    if (_validate_observation(observation, contract) is not None
                            or _fingerprint(row['observation_json']) != row['content_fingerprint']
                            or _canonical_json(_observation_payload(observation)) != row['observation_json']
                            or _identity(observation) != (source, source_instance, namespace, row['occurrence_value'])):
                        raise ValueError()
                    values[row['occurrence_value']] = observation
            return meta[0], values
        except Exception:
            return Degraded(None, "COMMITTED_PROOF_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def source_checkpoint(self, source: str, source_instance: str) -> SourceCommit | Degraded | None:
        """Read the atomic source cursor without creating or changing a journal."""
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                self._database.resolve().as_uri() + "?mode=ro", uri=True,
                timeout=self._busy_timeout_ms / 1000,
            )
            row = connection.execute(
                "SELECT checkpoint, checkpoint_order, observed_through FROM source_state WHERE source = ? AND source_instance = ?",
                (source, source_instance),
            ).fetchone()
            if row is None or all(value is None for value in row):
                return None
            checkpoint, order, through = row
            if not isinstance(checkpoint, str) or type(order) is not int or not isinstance(through, str):
                return Degraded(None, "SOURCE_CHECKPOINT_INVALID", None)
            observed_through = _parse_time(through)
            if observed_through.tzinfo is None or observed_through.utcoffset() is None:
                return Degraded(None, "SOURCE_CHECKPOINT_INVALID", None)
            return SourceCommit(source, source_instance, checkpoint, order, observed_through)
        except Exception:
            return Degraded(None, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def ingest(
        self,
        observations: Sequence[NormalizedObservation],
        source_commit: SourceCommit,
    ) -> Ingested | Degraded | Invalid:
        source_key = (source_commit.source, source_commit.source_instance)
        if any((item.source, item.source_instance) != source_key for item in observations):
            return Invalid(None, "SOURCE_COMMIT_MISMATCH", ("source commit does not match observation batch",))
        connection: sqlite3.Connection | None = None
        try:
            lease_now, _ = self._clock_bounds()
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            source_row = connection.execute(
                """
                SELECT si.contract_json, ss.*
                FROM source_instances AS si
                JOIN source_state AS ss USING(source, source_instance)
                WHERE si.source = ? AND si.source_instance = ?
                """,
                source_key,
            ).fetchone()
            if source_row is None:
                connection.rollback()
                return Invalid(None, "SOURCE_NOT_CONFIGURED", ("source instance is not configured",))
            if source_row["lease_owner"] is not None:
                lease_expiry = _parse_time(source_row["lease_expires_at"])
                if lease_expiry > lease_now:
                    connection.rollback()
                    return Degraded(None, "SOURCE_BUSY", lease_expiry)
            previous_order = source_row["checkpoint_order"]
            previous_checkpoint = source_row["checkpoint"]
            if previous_order is not None:
                if source_commit.checkpoint_order < int(previous_order):
                    connection.rollback()
                    return Invalid(None, "CHECKPOINT_REGRESSION", ("source checkpoint order regressed",))
                if source_commit.checkpoint_order == int(previous_order) and source_commit.checkpoint != previous_checkpoint:
                    connection.rollback()
                    return Invalid(None, "CHECKPOINT_CONFLICT", ("source checkpoint content conflicts at the same order",))
            contract = _contract_from_json(source_row["contract_json"])
            staged: dict[tuple[str, str, str, str], tuple[NormalizedObservation, str, str]] = {}
            for observation in observations:
                invalid = _validate_observation(observation, contract)
                if invalid is not None:
                    connection.rollback()
                    return invalid
                identity = _identity(observation)
                payload_json = _canonical_json(_observation_payload(observation))
                fingerprint = _fingerprint(payload_json)
                prior = staged.get(identity)
                if prior is not None and prior[2] != fingerprint:
                    connection.rollback()
                    return Invalid(None, "OCCURRENCE_IDENTITY_CONFLICT", ("occurrence identity has different content",))
                stored = connection.execute(
                    """
                    SELECT content_fingerprint FROM receipts
                    WHERE source = ? AND source_instance = ?
                      AND occurrence_namespace = ? AND occurrence_value = ?
                    """,
                    identity,
                ).fetchone()
                if stored is not None and stored["content_fingerprint"] != fingerprint:
                    connection.rollback()
                    return Invalid(None, "OCCURRENCE_IDENTITY_CONFLICT", ("occurrence identity has different content",))
                staged[identity] = (observation, payload_json, fingerprint)

            next_sequence = int(
                connection.execute(
                    "SELECT next_sequence FROM journal_meta WHERE singleton = 1"
                ).fetchone()[0]
            )
            inserted: dict[tuple[str, str, str, str], ReceiptRef] = {}
            for identity, (observation, payload_json, fingerprint) in staged.items():
                stored = connection.execute(
                    """
                    SELECT receipt_id, local_sequence FROM receipts
                    WHERE source = ? AND source_instance = ?
                      AND occurrence_namespace = ? AND occurrence_value = ?
                    """,
                    identity,
                ).fetchone()
                if stored is not None:
                    continue
                receipt_id = f"event_{next_sequence:012d}"
                connection.execute(
                    """
                    INSERT INTO receipts(
                        local_sequence, receipt_id, source, source_instance,
                        occurrence_namespace, occurrence_value, content_fingerprint,
                        kind, subject, occurred_at, observed_at, attributes_json,
                        verification_state, verification_method, evidence_ref,
                        observation_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        next_sequence,
                        receipt_id,
                        observation.source,
                        observation.source_instance,
                        observation.occurrence_namespace,
                        observation.occurrence_value,
                        fingerprint,
                        observation.kind,
                        observation.subject,
                        _format_time(observation.occurred_at),
                        _format_time(observation.observed_at),
                        _canonical_json(dict(observation.attributes)),
                        observation.verification.state,
                        observation.verification.method,
                        observation.evidence_ref,
                        payload_json,
                    ),
                )
                inserted[identity] = ReceiptRef(ReceiptId(receipt_id), next_sequence, False)
                next_sequence += 1
            connection.execute(
                "UPDATE journal_meta SET next_sequence = ?, migrated_at = ? WHERE singleton = 1",
                (next_sequence, _format_time(source_commit.observed_through)),
            )
            connection.execute(
                """
                UPDATE source_state
                SET checkpoint = ?, checkpoint_order = ?, observed_through = ?,
                    last_local_sequence = MAX(last_local_sequence, ?),
                    lease_owner = NULL, lease_expires_at = NULL
                WHERE source = ? AND source_instance = ?
                """,
                (
                    source_commit.checkpoint,
                    source_commit.checkpoint_order,
                    _format_time(source_commit.observed_through),
                    next_sequence - 1,
                    source_commit.source,
                    source_commit.source_instance,
                ),
            )
            preexisting: set[tuple[str, str, str, str]] = set()
            returned: set[tuple[str, str, str, str]] = set()
            results: list[ReceiptRef] = []
            for observation in observations:
                identity = _identity(observation)
                if identity in inserted and identity not in returned:
                    receipt = inserted[identity]
                else:
                    stored = connection.execute(
                        """
                        SELECT receipt_id, local_sequence FROM receipts
                        WHERE source = ? AND source_instance = ?
                          AND occurrence_namespace = ? AND occurrence_value = ?
                        """,
                        identity,
                    ).fetchone()
                    receipt = ReceiptRef(ReceiptId(stored["receipt_id"]), int(stored["local_sequence"]), True)
                    preexisting.add(identity)
                duplicate = identity in preexisting or identity in returned
                results.append(ReceiptRef(receipt.receipt_id, receipt.local_sequence, duplicate))
                returned.add(identity)
            self._checkpoint("before_ingest_commit")
            self._clock_upper()
            connection.commit()
            self._checkpoint("after_ingest_commit")
            return Ingested(tuple(results), source_commit.checkpoint)
        except Exception:
            _rollback_quietly(connection)
            return Degraded(None, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def evaluate(
        self,
        wake_id: WakeId,
        armed_signal: ArmedSignal,
        now: datetime,
        limits: EvaluationLimits,
    ) -> Matched | NotReady | Degraded | Invalid | Expired:
        if wake_id != armed_signal.wake_id:
            return Invalid(wake_id, "INVALID_ARM", ("armed signal identity does not match",))
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            arm = connection.execute("SELECT * FROM arms WHERE wake_id = ?", (str(wake_id),)).fetchone()
            if arm is None:
                connection.rollback()
                return Invalid(wake_id, "INVALID_ARM", ("armed signal is unavailable",))
            durable = _armed_from_row(arm)
            if durable.publication != "published" or durable.arm_id != armed_signal.arm_id:
                connection.rollback()
                return Degraded(wake_id, "ARM_NOT_PUBLISHED", None)
            source = connection.execute(
                "SELECT contract_json, contract_fingerprint FROM source_instances WHERE source = ? AND source_instance = ?",
                (durable.spec.source, durable.spec.source_instance),
            ).fetchone()
            if source is None or _fingerprint(source["contract_json"]) != source["contract_fingerprint"]:
                connection.rollback()
                return Degraded(wake_id, "SOURCE_STATE_UNAVAILABLE", None)
            contract = _contract_from_json(source["contract_json"])
            invalid = _validate_occurrence_anchor(contract, durable.spec, durable.anchor)
            if invalid is not None:
                connection.rollback()
                return invalid
            reservation = connection.execute(
                "SELECT * FROM match_reservations WHERE wake_id = ?",
                (str(wake_id),),
            ).fetchone()
            if reservation is not None:
                result = _matched_from_row(reservation)
                self._ensure_match_outbox(connection, durable, result)
                connection.commit()
                return result
            lifecycle = connection.execute(
                "SELECT * FROM wake_lifecycle WHERE wake_id = ?", (str(wake_id),)
            ).fetchone()
            if (
                lifecycle is None
                or lifecycle["desired_status"] != "pending"
                or lifecycle["applied_status"] != "pending"
                or lifecycle["desired_revision"] != lifecycle["applied_revision"]
            ):
                connection.rollback()
                return Degraded(wake_id, "ARM_NOT_PUBLISHED", None)
            if durable.expires_at is not None and now >= durable.expires_at:
                connection.rollback()
                return Expired(wake_id, durable.expires_at)
            if limits.max_candidates <= 0:
                connection.rollback()
                return Degraded(wake_id, "EVALUATION_BUDGET_EXHAUSTED", None)
            progress = connection.execute(
                "SELECT * FROM evaluation_progress WHERE wake_id = ?",
                (str(wake_id),),
            ).fetchone()
            scanned = max(
                durable.anchor.local_after_sequence,
                int(progress["scanned_through_sequence"]),
            )
            rows = connection.execute(
                """
                SELECT * FROM receipts
                WHERE source = ? AND source_instance = ?
                  AND kind = ? AND subject = ? AND local_sequence > ?
                ORDER BY local_sequence
                LIMIT ?
                """,
                (
                    durable.spec.source,
                    durable.spec.source_instance,
                    durable.spec.kind,
                    durable.spec.subject,
                    scanned,
                    limits.max_candidates + 1,
                ),
            ).fetchall()
            page = rows[: limits.max_candidates]
            has_more = len(rows) > limits.max_candidates
            safe_progress = scanned
            for row in page:
                observation = _observation_from_json(row["observation_json"])
                sequence = int(row["local_sequence"])
                after = _occurrence_is_after_anchor(observation, contract, durable.anchor)
                if isinstance(after, Invalid):
                    connection.rollback()
                    return after
                baseline_matches = True
                # Filesystem reconciliation emits one receipt per eligible
                # registration-baseline cohort. Keep this source convention
                # out of unrelated state adapters.
                if (
                    durable.spec.source == "filesystem"
                    and durable.spec.semantics == "state"
                    and durable.spec.condition == "becomes"
                ):
                    observed_baseline = observation.attributes.get("baseline_fingerprint")
                    armed_baseline = durable.anchor.baseline.get("fingerprint")
                    if isinstance(observed_baseline, str) and isinstance(armed_baseline, str):
                        baseline_matches = observed_baseline == armed_baseline
                if (
                    not after
                    or not baseline_matches
                    or not _matches(observation, durable.spec.where)
                ):
                    safe_progress = sequence
                    continue
                if durable.spec.verification == "required" and observation.verification.state != "verified":
                    if observation.verification.state == "pending":
                        self._pin_pending(connection, wake_id, row["receipt_id"], now)
                        self._advance_progress(connection, wake_id, safe_progress, now)
                        connection.commit()
                        return Degraded(wake_id, "VERIFICATION_PENDING", None)
                    safe_progress = sequence
                    continue
                attribute_bytes = len(_canonical_json(dict(observation.attributes)).encode("utf-8"))
                evidence_bytes = len((observation.evidence_ref or "").encode("utf-8"))
                if attribute_bytes > limits.max_attribute_bytes or evidence_bytes > limits.max_evidence_ref_bytes:
                    self._advance_progress(connection, wake_id, safe_progress, now)
                    connection.commit()
                    return Degraded(wake_id, "EVALUATION_BUDGET_EXHAUSTED", None)
                evidence = EvidenceSummary(
                    ReceiptId(row["receipt_id"]),
                    sequence,
                    observation.evidence_ref,
                    MappingProxyType(dict(observation.attributes)),
                    observation.verification.state,
                    observation.verification.method,
                )
                matched = Matched(
                    wake_id,
                    MatchToken(f"match:{wake_id}:{row['receipt_id']}"),
                    evidence,
                    now,
                )
                evidence_json = _canonical_json(_matched_payload(matched))
                connection.execute(
                    """
                    INSERT INTO match_reservations(
                        wake_id, receipt_id, match_token, matched_at, evidence_json
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(wake_id) DO NOTHING
                    """,
                    (
                        str(wake_id),
                        row["receipt_id"],
                        str(matched.match_token),
                        _format_time(now),
                        evidence_json,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO retention_pins(pin_id, wake_id, receipt_id, reason, created_at)
                    VALUES (?, ?, ?, 'match_evidence', ?)
                    ON CONFLICT(pin_id) DO NOTHING
                    """,
                    (f"match:{wake_id}", str(wake_id), row["receipt_id"], _format_time(now)),
                )
                winner = connection.execute(
                    "SELECT * FROM match_reservations WHERE wake_id = ?",
                    (str(wake_id),),
                ).fetchone()
                matched_winner = _matched_from_row(winner)
                self._ensure_match_outbox(connection, durable, matched_winner)
                self._checkpoint("after_match_reservation_before_commit")
                connection.commit()
                self._checkpoint("after_match_reservation_commit")
                return matched_winner
            if page:
                safe_progress = int(page[-1]["local_sequence"])
            else:
                safe_progress = int(
                    connection.execute(
                        "SELECT next_sequence - 1 FROM journal_meta WHERE singleton = 1"
                    ).fetchone()[0]
                )
            self._advance_progress(connection, wake_id, safe_progress, now)
            connection.commit()
            if has_more:
                return Degraded(wake_id, "EVALUATION_BUDGET_EXHAUSTED", None)
            return NotReady(wake_id, safe_progress)
        except Exception:
            _rollback_quietly(connection)
            return Degraded(wake_id, "STORE_UNAVAILABLE", None)
        finally:
            _close_quietly(connection)

    def _ensure_match_outbox(
        self,
        connection: sqlite3.Connection,
        armed: ArmedSignal,
        matched: Matched,
    ) -> None:
        existing = connection.execute(
            "SELECT 1 FROM record_outbox WHERE wake_id = ? AND revision = 2",
            (str(matched.wake_id),),
        ).fetchone()
        if existing is not None:
            return
        pending = connection.execute(
            "SELECT payload_json FROM record_outbox WHERE wake_id = ? AND revision = 1",
            (str(matched.wake_id),),
        ).fetchone()
        if pending is None:
            raise SignalStoreError("pending record intent is unavailable")
        payload = json.loads(str(pending["payload_json"]))
        evidence = {
            "match_token": str(matched.match_token),
            "receipt_id": str(matched.receipt.receipt_id),
            "local_sequence": matched.receipt.local_sequence,
            "evidence_ref": matched.receipt.evidence_ref,
            "attributes": dict(matched.receipt.attributes),
            "verification": {
                "state": matched.receipt.verification_state,
                "method": matched.receipt.verification_method,
            },
            "matched_at": _format_time(matched.matched_at),
        }
        evidence_digest = _fingerprint(_canonical_json(evidence))
        evidence["evidence_digest"] = evidence_digest
        payload["trigger_match"] = evidence
        payload["status"] = "firing"
        payload["record_revision"] = 2
        payload["updated_at"] = _format_time(matched.matched_at)
        events = list(payload.get("events") or [])
        events.append(
            {
                "at": _format_time(matched.matched_at),
                "type": "predicate_matched",
                "message": "Signal observation reserved for firing",
            }
        )
        payload["events"] = events
        payload_json = _canonical_json(payload)
        payload_sha256 = hashlib.sha256((payload_json + "\n").encode("utf-8")).hexdigest()
        connection.execute(
            """
            INSERT INTO record_outbox(
                wake_id, revision, operation, target_status, source_status,
                payload_json, payload_sha256, state, created_at
            ) VALUES (?, 2, 'put', 'firing', 'pending', ?, ?, 'pending', ?)
            """,
            (
                str(matched.wake_id),
                payload_json,
                payload_sha256,
                _format_time(matched.matched_at),
            ),
        )
        connection.execute(
            """
            UPDATE wake_lifecycle
            SET desired_status = 'firing', desired_revision = 2, updated_at = ?
            WHERE wake_id = ? AND desired_status = 'pending'
            """,
            (_format_time(matched.matched_at), str(matched.wake_id)),
        )

    @staticmethod
    def _advance_progress(
        connection: sqlite3.Connection,
        wake_id: WakeId,
        sequence: int,
        now: datetime,
    ) -> None:
        connection.execute(
            """
            UPDATE evaluation_progress
            SET scanned_through_sequence = MAX(scanned_through_sequence, ?),
                revision = revision + 1, updated_at = ?
            WHERE wake_id = ?
            """,
            (sequence, _format_time(now), str(wake_id)),
        )

    @staticmethod
    def _pin_pending(
        connection: sqlite3.Connection,
        wake_id: WakeId,
        receipt_id: str,
        now: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO retention_pins(pin_id, wake_id, receipt_id, reason, created_at)
            VALUES (?, ?, ?, 'verification_pending', ?)
            ON CONFLICT(pin_id) DO NOTHING
            """,
            (f"pending:{wake_id}:{receipt_id}", str(wake_id), receipt_id, _format_time(now)),
        )


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _close_quietly(connection: sqlite3.Connection | None) -> None:
    if connection is None:
        return
    try:
        connection.close()
    except sqlite3.Error:
        return


def _rollback_quietly(connection: sqlite3.Connection | None) -> None:
    if connection is None:
        return
    try:
        if connection.in_transaction:
            connection.rollback()
    except sqlite3.Error:
        return


def _execute_sql_script(connection: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        sql = statement.strip()
        if sql:
            connection.execute(sql)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _spec_payload(spec: SignalRequest) -> dict[str, Any]:
    return {
        "contract_version": spec.contract_version,
        "source": spec.source,
        "source_instance": spec.source_instance,
        "semantics": spec.semantics,
        "kind": spec.kind,
        "subject": spec.subject,
        "condition": spec.condition,
        "where": [
            {"op": "eq", **asdict(clause)}
            if isinstance(clause, Eq)
            else {"op": "in", **asdict(clause)}
            for clause in spec.where
        ],
        "verification": spec.verification,
    }


def _spec_from_json(value: str) -> SignalRequest:
    payload = json.loads(value)
    clauses = tuple(
        Eq(item["field"], item["value"])
        if item["op"] == "eq"
        else In(item["field"], tuple(item["values"]))
        for item in payload["where"]
    )
    return SignalRequest(
        payload["contract_version"],
        payload["source"],
        payload["source_instance"],
        payload["semantics"],
        payload["kind"],
        payload["subject"],
        payload["condition"],
        clauses,
        payload["verification"],
    )


def _resume_payload(context: ArmContext) -> dict[str, Any]:
    return {
        "prompt": context.resume.prompt,
        "cwd": str(context.resume.cwd),
        "target": dict(context.resume.target),
    }


def _resume_from_json(value: str) -> Resume:
    payload = json.loads(value)
    return Resume(
        prompt=payload["prompt"],
        cwd=Path(payload["cwd"]),
        target=MappingProxyType(dict(payload["target"])),
    )


_TYPE_NAMES = {str: "str", int: "int", bool: "bool"}
_TYPES = {value: key for key, value in _TYPE_NAMES.items()}


def _contract_payload(contract: SourceContract) -> dict[str, Any]:
    payload = {
        "source": contract.source,
        "source_instance": contract.source_instance,
        "kinds": sorted(contract.kinds),
        "subjects": sorted(contract.subjects),
        "allowed_attributes": {
            name: _TYPE_NAMES[value]
            for name, value in sorted(contract.allowed_attributes.items())
        },
        "max_clauses": contract.max_clauses,
        "max_in_values": contract.max_in_values,
        "max_attribute_bytes": contract.max_attribute_bytes,
        "max_evidence_ref_bytes": contract.max_evidence_ref_bytes,
    }
    # Omit the unset default to preserve fingerprints of pre-extension rows.
    if contract.occurrence_order_attribute is not None:
        payload["occurrence_order_attribute"] = contract.occurrence_order_attribute
    return payload


def _contract_from_json(value: str) -> SourceContract:
    payload = json.loads(value)
    return SourceContract(
        source=payload["source"],
        source_instance=payload["source_instance"],
        kinds=frozenset(payload["kinds"]),
        subjects=frozenset(payload["subjects"]),
        allowed_attributes=MappingProxyType(
            {name: _TYPES[type_name] for name, type_name in payload["allowed_attributes"].items()}
        ),
        max_clauses=payload["max_clauses"],
        max_in_values=payload["max_in_values"],
        max_attribute_bytes=payload["max_attribute_bytes"],
        max_evidence_ref_bytes=payload["max_evidence_ref_bytes"],
        occurrence_order_attribute=payload.get("occurrence_order_attribute"),
    )


def _identity(observation: NormalizedObservation) -> tuple[str, str, str, str]:
    return (
        observation.source,
        observation.source_instance,
        observation.occurrence_namespace,
        observation.occurrence_value,
    )


def _observation_payload(observation: NormalizedObservation) -> dict[str, Any]:
    return {
        "source": observation.source,
        "source_instance": observation.source_instance,
        "kind": observation.kind,
        "subject": observation.subject,
        "occurrence_namespace": observation.occurrence_namespace,
        "occurrence_value": observation.occurrence_value,
        "occurred_at": _format_time(observation.occurred_at),
        "observed_at": _format_time(observation.observed_at),
        "attributes": dict(observation.attributes),
        "verification": asdict(observation.verification),
        "evidence_ref": observation.evidence_ref,
    }


def _observation_from_json(value: str) -> NormalizedObservation:
    payload = json.loads(value)
    return NormalizedObservation(
        source=payload["source"],
        source_instance=payload["source_instance"],
        kind=payload["kind"],
        subject=payload["subject"],
        occurrence_namespace=payload["occurrence_namespace"],
        occurrence_value=payload["occurrence_value"],
        occurred_at=_parse_time(payload["occurred_at"]),
        observed_at=_parse_time(payload["observed_at"]),
        attributes=MappingProxyType(dict(payload["attributes"])),
        verification=Verification(**payload["verification"]),
        evidence_ref=payload["evidence_ref"],
    )


def _armed_from_row(row: sqlite3.Row) -> ArmedSignal:
    anchor = SourceAnchor(
        int(row["local_after_sequence"]),
        row["source_anchor"],
        MappingProxyType(dict(json.loads(row["baseline_json"]))),
        row["recovery"],
    )
    return ArmedSignal(
        WakeId(row["wake_id"]),
        row["arm_id"],
        _spec_from_json(row["spec_json"]),
        anchor,
        _parse_time(row["registered_at"]),
        _parse_time(row["expires_at"]) if row["expires_at"] else None,
        row["state"],
    )


def _matched_payload(matched: Matched) -> dict[str, Any]:
    return {
        "wake_id": str(matched.wake_id),
        "match_token": str(matched.match_token),
        "receipt_id": str(matched.receipt.receipt_id),
        "local_sequence": matched.receipt.local_sequence,
        "evidence_ref": matched.receipt.evidence_ref,
        "attributes": dict(matched.receipt.attributes),
        "verification_state": matched.receipt.verification_state,
        "verification_method": matched.receipt.verification_method,
        "matched_at": _format_time(matched.matched_at),
    }


def _matched_from_row(row: sqlite3.Row) -> Matched:
    payload = json.loads(row["evidence_json"])
    return Matched(
        WakeId(payload["wake_id"]),
        MatchToken(payload["match_token"]),
        EvidenceSummary(
            ReceiptId(payload["receipt_id"]),
            int(payload["local_sequence"]),
            payload["evidence_ref"],
            MappingProxyType(dict(payload["attributes"])),
            payload.get("verification_state", "verified"),
            payload.get("verification_method", ""),
        ),
        _parse_time(payload["matched_at"]),
    )


def _validate_observation(
    observation: NormalizedObservation,
    contract: SourceContract,
) -> Invalid | None:
    if (
        observation.source != contract.source
        or observation.source_instance != contract.source_instance
        or observation.kind not in contract.kinds
        or observation.subject not in contract.subjects
        or not observation.occurrence_namespace
        or not observation.occurrence_value
        or observation.verification.state not in {"verified", "pending", "rejected"}
        or not observation.verification.method
    ):
        return Invalid(None, "OBSERVATION_OUTSIDE_CONTRACT", ("observation is outside the configured source contract",))
    if observation.evidence_ref is not None and len(observation.evidence_ref.encode("utf-8")) > contract.max_evidence_ref_bytes:
        return Invalid(None, "EVIDENCE_LIMIT_EXCEEDED", ("observation evidence reference exceeds the source limit",))
    for name, value in observation.attributes.items():
        normalized = name.casefold()
        if any(part in normalized for part in ("authorization", "cookie", "password", "secret", "signature", "token")):
            return Invalid(None, "ATTRIBUTE_NOT_ALLOWED", ("observation contains a forbidden attribute",))
        expected = contract.allowed_attributes.get(name)
        if expected is None or type(value) is not expected:
            return Invalid(None, "ATTRIBUTE_NOT_ALLOWED", ("observation contains an unsupported attribute",))
    if len(_canonical_json(dict(observation.attributes)).encode("utf-8")) > contract.max_attribute_bytes:
        return Invalid(None, "ATTRIBUTE_LIMIT_EXCEEDED", ("observation attributes exceed the source limit",))
    return None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    schema_version INTEGER NOT NULL,
    next_sequence INTEGER NOT NULL CHECK(next_sequence >= 1),
    created_at TEXT NOT NULL,
    migrated_at TEXT NOT NULL,
    journal_uuid TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS source_instances (
    source TEXT NOT NULL,
    source_instance TEXT NOT NULL,
    contract_json TEXT NOT NULL,
    contract_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(source, source_instance)
);
CREATE TABLE IF NOT EXISTS source_state (
    source TEXT NOT NULL,
    source_instance TEXT NOT NULL,
    checkpoint TEXT,
    checkpoint_order INTEGER,
    observed_through TEXT,
    last_local_sequence INTEGER NOT NULL DEFAULT 0 CHECK(last_local_sequence >= 0),
    lease_owner TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0),
    lease_expires_at TEXT,
    PRIMARY KEY(source, source_instance),
    FOREIGN KEY(source, source_instance) REFERENCES source_instances(source, source_instance)
);
CREATE TABLE IF NOT EXISTS arms (
    arm_id TEXT PRIMARY KEY,
    wake_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    intent_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('preparing', 'prepared', 'published', 'tombstoned')),
    contract_version INTEGER NOT NULL CHECK(contract_version = 1),
    source TEXT NOT NULL,
    source_instance TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    resume_json TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    expires_at TEXT,
    local_after_sequence INTEGER,
    source_anchor TEXT,
    baseline_json TEXT,
    recovery TEXT,
    preparer_token TEXT,
    preparation_expires_at TEXT,
    prepared_at TEXT,
    published_at TEXT,
    FOREIGN KEY(source, source_instance) REFERENCES source_instances(source, source_instance)
);
CREATE TABLE IF NOT EXISTS receipts (
    local_sequence INTEGER PRIMARY KEY,
    receipt_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_instance TEXT NOT NULL,
    occurrence_namespace TEXT NOT NULL,
    occurrence_value TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    verification_state TEXT NOT NULL CHECK(verification_state IN ('verified', 'pending', 'rejected')),
    verification_method TEXT NOT NULL,
    evidence_ref TEXT,
    observation_json TEXT NOT NULL,
    UNIQUE(source, source_instance, occurrence_namespace, occurrence_value),
    FOREIGN KEY(source, source_instance) REFERENCES source_instances(source, source_instance)
);
CREATE INDEX IF NOT EXISTS receipts_match_scan
ON receipts(source, source_instance, kind, subject, local_sequence);
CREATE TABLE IF NOT EXISTS evaluation_progress (
    wake_id TEXT PRIMARY KEY,
    scanned_through_sequence INTEGER NOT NULL DEFAULT 0 CHECK(scanned_through_sequence >= 0),
    revision INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(wake_id) REFERENCES arms(wake_id)
);
CREATE TABLE IF NOT EXISTS match_reservations (
    wake_id TEXT PRIMARY KEY,
    receipt_id TEXT,
    match_token TEXT NOT NULL UNIQUE,
    matched_at TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    FOREIGN KEY(wake_id) REFERENCES arms(wake_id),
    FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS retention_pins (
    pin_id TEXT PRIMARY KEY,
    wake_id TEXT NOT NULL,
    receipt_id TEXT,
    min_local_sequence INTEGER,
    reason TEXT NOT NULL CHECK(reason IN ('active_anchor', 'match_evidence', 'verification_pending')),
    created_at TEXT NOT NULL,
    released_at TEXT,
    FOREIGN KEY(wake_id) REFERENCES arms(wake_id),
    FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id),
    CHECK(
      (receipt_id IS NOT NULL AND min_local_sequence IS NULL)
      OR (receipt_id IS NULL AND min_local_sequence IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS retention_pins_live_receipt
ON retention_pins(receipt_id) WHERE released_at IS NULL;
CREATE INDEX IF NOT EXISTS retention_pins_live_sequence
ON retention_pins(min_local_sequence) WHERE released_at IS NULL;
CREATE TABLE IF NOT EXISTS wake_lifecycle (
    wake_id TEXT PRIMARY KEY,
    desired_status TEXT NOT NULL,
    desired_revision INTEGER NOT NULL CHECK(desired_revision >= 1),
    applied_status TEXT,
    applied_revision INTEGER,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(wake_id) REFERENCES arms(wake_id)
);
CREATE TABLE IF NOT EXISTS record_outbox (
    wake_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    operation TEXT NOT NULL CHECK(operation IN ('put', 'delete')),
    target_status TEXT,
    source_status TEXT,
    payload_json TEXT,
    payload_sha256 TEXT,
    state TEXT NOT NULL CHECK(state IN ('pending', 'applied', 'blocked')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    last_attempt_at TEXT,
    created_at TEXT NOT NULL,
    applied_at TEXT,
    blocked_code TEXT,
    PRIMARY KEY(wake_id, revision),
    FOREIGN KEY(wake_id) REFERENCES arms(wake_id),
    CHECK(
      (operation = 'put' AND target_status IS NOT NULL AND payload_json IS NOT NULL AND payload_sha256 IS NOT NULL)
      OR (operation = 'delete' AND payload_json IS NULL AND payload_sha256 IS NULL)
    )
);
CREATE TABLE IF NOT EXISTS registration_tombstones (
    idempotency_key TEXT PRIMARY KEY,
    intent_fingerprint TEXT NOT NULL,
    wake_id TEXT NOT NULL UNIQUE,
    terminal_status TEXT NOT NULL,
    retired_at TEXT NOT NULL
);
"""


_MIGRATION_V2_TABLES = """
CREATE TABLE arms_v2 (
    arm_id TEXT PRIMARY KEY,
    wake_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    intent_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('preparing', 'prepared', 'published', 'tombstoned')),
    contract_version INTEGER NOT NULL CHECK(contract_version = 1),
    source TEXT NOT NULL,
    source_instance TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    resume_json TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    expires_at TEXT,
    local_after_sequence INTEGER,
    source_anchor TEXT,
    baseline_json TEXT,
    recovery TEXT,
    preparer_token TEXT,
    preparation_expires_at TEXT,
    prepared_at TEXT,
    published_at TEXT,
    FOREIGN KEY(source, source_instance) REFERENCES source_instances(source, source_instance)
);
CREATE TABLE wake_lifecycle (
    wake_id TEXT PRIMARY KEY,
    desired_status TEXT NOT NULL,
    desired_revision INTEGER NOT NULL CHECK(desired_revision >= 1),
    applied_status TEXT,
    applied_revision INTEGER,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(wake_id) REFERENCES arms(wake_id)
);
CREATE TABLE record_outbox (
    wake_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    operation TEXT NOT NULL CHECK(operation IN ('put', 'delete')),
    target_status TEXT,
    source_status TEXT,
    payload_json TEXT,
    payload_sha256 TEXT,
    state TEXT NOT NULL CHECK(state IN ('pending', 'applied', 'blocked')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    last_attempt_at TEXT,
    created_at TEXT NOT NULL,
    applied_at TEXT,
    blocked_code TEXT,
    PRIMARY KEY(wake_id, revision),
    FOREIGN KEY(wake_id) REFERENCES arms(wake_id),
    CHECK(
      (operation = 'put' AND target_status IS NOT NULL AND payload_json IS NOT NULL AND payload_sha256 IS NOT NULL)
      OR (operation = 'delete' AND payload_json IS NULL AND payload_sha256 IS NULL)
    )
);
CREATE TABLE registration_tombstones (
    idempotency_key TEXT PRIMARY KEY,
    intent_fingerprint TEXT NOT NULL,
    wake_id TEXT NOT NULL UNIQUE,
    terminal_status TEXT NOT NULL,
    retired_at TEXT NOT NULL
);
"""
