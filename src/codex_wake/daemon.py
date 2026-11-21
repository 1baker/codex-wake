from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from functools import cache, wraps
from pathlib import Path
from typing import Callable, Literal, Mapping

from .records import (
    WakeError,
    WakeLifecycleLock,
    WakePath,
    classify_record,
    default_wake_root,
    find_record,
    iter_records,
    move_record,
    parse_utc_timestamp,
    utc_now,
)
from .builtin_signals import BuiltinPredicateSignals
from .injector import TmuxRunner, dispatch_firing_record
from .signal_store import SQLiteSignalModule
from .signal_records import WakeRecordPublisher, current_reader_capability, signal_journal_path
from .github_polling import (
    GitHubPollingAdapter,
    GitHubPollingConfig,
    GitHubReadClient,
    PollBatch,
)
from .github_source_config import GitHubSourceStore
from .signals import (
    ArmedSignal, Degraded, EvaluationLimits, Expired, Ingested,
    Matched, SignalSourceRunner, SourceInstanceReconcileResult,
    SourceReconcileResult, UnavailableSourceRunner,
)
from .monitor import write_monitor_health
from .monitor_ownership import MonitorOwnership, ownership_held, reconciliation_required
from .source_registry import BuiltinSourceRegistry, ReconstructionContext, builtin_source_registry


@dataclass(frozen=True)
class PollResult:
    checked: int = 0
    fired: int = 0
    failed: int = 0
    pending: int = 0
    dispatched: int = 0
    requeued: int = 0
    submitted: int = 0
    signal_sources: tuple[dict[str, object], ...] = ()
    skip_reason: str | None = None
    time_held: int = 0


def format_poll_result(result: PollResult) -> str:
    if getattr(result, "skip_reason", None):
        return f"skipped={result.skip_reason}"
    text = (
        f"checked={result.checked} fired={result.fired} "
        f"failed={result.failed} pending={result.pending} "
        f"dispatched={result.dispatched} submitted={result.submitted} requeued={result.requeued}"
    )
    return text + (f" time_held={result.time_held}" if result.time_held else "")


def poll_result_has_activity(result: PollResult) -> bool:
    return any(
        (
            result.checked,
            result.fired,
            result.failed,
            result.dispatched,
            result.submitted,
            result.requeued,
            result.time_held,
            getattr(result, "skip_reason", None),
        )
    )


def poll_result_dict(result: PollResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "checked": result.checked,
        "fired": result.fired,
        "failed": result.failed,
        "pending": result.pending,
        "dispatched": result.dispatched,
        "submitted": result.submitted,
        "requeued": result.requeued,
        "signal_sources": list(getattr(result, "signal_sources", ())),
    }
    if getattr(result, "skip_reason", None):
        payload["skip_reason"] = result.skip_reason
    if result.time_held:
        payload["time_held"] = result.time_held
    return payload


def _legacy_time_bounds(now):
    if now is not None:
        return now, now
    from . import measurements
    try:
        lower, upper = measurements.utc_bounds()
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        # Round outward into datetime's coordinate precision, never toward a
        # deadline across an uncertain sub-microsecond boundary.
        return (epoch + timedelta(microseconds=math.floor(Fraction(lower) * 1000000)),
                epoch + timedelta(microseconds=math.ceil(Fraction(upper) * 1000000)))
    except (measurements.TimeUnavailable, OverflowError, ValueError):
        return None, None


def default_signal_runners(
    root: Path,
    runtime: SQLiteSignalModule,
    *,
    initial_reason: Literal["startup", "periodic"] = "startup",
    github_client_factory: Callable[[GitHubPollingConfig], GitHubReadClient] | None = None,
    http_json_client_factory: Callable[[object], object] | None = None,
    systemd_backend_factory: Callable[[object], object] | None = None,
    source_registry: BuiltinSourceRegistry | None = None,
    receipt_authority_path: Path | None = None,
) -> tuple[SignalSourceRunner, ...]:
    """Reconstruct referenced sources, then append an optional closed catalogue."""

    # All registered families share one authoritative arm read per wake.
    load_armed_signal = cache(runtime.load_armed_signal)
    context = ReconstructionContext(root, load_armed_signal, initial_reason)
    pending = pending_records(root)
    builtin_registry = builtin_source_registry(
        github_runner_factory=GitHubSignalRunner,
        github_client_factory=github_client_factory,
        http_json_client_factory=http_json_client_factory,
        systemd_backend_factory=systemd_backend_factory,
    )
    builtin_runners = builtin_registry.reconstruct(context, pending)
    runners: list[SignalSourceRunner] = [
        runner for runner in builtin_runners
        if not isinstance(runner, UnavailableSourceRunner)
    ]
    unavailable_runners = [
        runner for runner in builtin_runners
        if isinstance(runner, UnavailableSourceRunner)
    ]
    runners.extend(unavailable_runners)
    if source_registry is not None:
        runners.extend(source_registry.reconstruct(context, pending))
    if receipt_authority_path is not None:
        from .a2a_receipt_authority import ConfiguredReceiptAuthority
        from .a2a_receipt_family import receipt_source_registration
        authority = ConfiguredReceiptAuthority(receipt_authority_path, root)
        receipt_registry = BuiltinSourceRegistry((receipt_source_registration(authority.resolve),))
        runners.extend(receipt_registry.reconstruct(context, pending))
    return tuple(runners)


def _evaluate_signal(
    runtime: SQLiteSignalModule,
    armed: ArmedSignal,
    now: datetime,
    limits: EvaluationLimits,
    runners: tuple[SignalSourceRunner, ...],
):
    """Use a source-owned guard for runtime sources before publication."""

    if armed.spec.source not in {"runtime", "systemd", "a2a.receipt"}:
        return runtime.evaluate(armed.wake_id, armed, now, limits), False
    for runner in runners:
        handles = getattr(runner, "handles", None)
        evaluate = getattr(runner, "evaluate", None)
        if not callable(handles) or not callable(evaluate):
            continue
        try:
            if handles(armed) is True:
                return evaluate(runtime, armed, now, limits), True
        except Exception:
            return Degraded(armed.wake_id, "RUNTIME_OBSERVATION_UNAVAILABLE", None), True
    return Degraded(armed.wake_id, "RUNTIME_SOURCE_UNSUPPORTED", None), True


class GitHubSignalRunner:
    """Poll referenced GitHub sources and commit only verified positive evidence."""

    def __init__(
        self,
        adapters: Mapping[str, GitHubPollingAdapter],
        *,
        armed_signals: tuple[ArmedSignal, ...],
        health_store: GitHubSourceStore,
    ) -> None:
        self._adapters = dict(adapters)
        self._armed_signals = armed_signals
        self._health_store = health_store

    def reconcile(
        self,
        module: SQLiteSignalModule,
        now: datetime,
        limits: EvaluationLimits,
    ) -> SourceReconcileResult:
        if now.tzinfo is None or now.utcoffset() is None or limits.max_candidates <= 0:
            return SourceReconcileResult("github", 0, 0, 1)
        groups: dict[str, list[ArmedSignal]] = {}
        for armed in self._armed_signals:
            adapter = self._adapters.get(armed.spec.source_instance)
            if armed.spec.source != "github" or adapter is None:
                continue
            groups.setdefault(armed.spec.source_instance, []).append(armed)
        scanned = observed = degraded = 0
        instances: list[SourceInstanceReconcileResult] = []
        for source_instance in sorted(groups)[: limits.max_candidates]:
            source_arms = groups[source_instance]
            scanned += 1
            adapter = self._adapters[source_instance]
            earliest = min(source_arms, key=lambda item: item.registered_at)
            checkpoint = module.source_checkpoint("github", source_instance)
            if isinstance(checkpoint, Degraded):
                outcome: object = checkpoint
            else:
                outcome = adapter.observe(earliest.anchor, checkpoint=checkpoint, now=now)
            instance_observed = 0
            instance_degraded = 0
            health = None
            if isinstance(outcome, PollBatch):
                ingested = module.ingest(outcome.observations, outcome.commit)
                if isinstance(ingested, Ingested):
                    instance_observed = len(outcome.observations)
                    health = outcome.health
                    try:
                        _record_managed_polling_evidence(
                            self._health_store, source_instance, now,
                        )
                    except ValueError:
                        instance_degraded = 1
                else:
                    health = ingested if isinstance(ingested, Degraded) else Degraded(None, "STORE_UNAVAILABLE", None)
            else:
                health = outcome if isinstance(outcome, Degraded) else Degraded(None, "GITHUB_SOURCE_UNAVAILABLE", None)
            if health is not None:
                instance_degraded = 1
                try:
                    self._health_store.record_health(source_instance, health, observed_at=now)
                except (OSError, TypeError, ValueError):
                    instance_degraded = 1
            observed += instance_observed
            degraded += instance_degraded
            instances.append(
                SourceInstanceReconcileResult(
                    "github", source_instance, 1, instance_observed,
                    instance_degraded,
                    health.code if isinstance(health, Degraded) else "",
                    now,
                )
            )
        return SourceReconcileResult(
            "github", scanned, observed, degraded, tuple(instances)
        )


def _record_managed_polling_evidence(
    health_store: GitHubSourceStore, source_instance: str, now: datetime,
) -> None:
    """Persist only a completed poll for one exact managed source binding."""
    from .managed_webhook_health_evidence import ManagedWebhookHealthEvidenceStore
    from .managed_webhooks import ManagedWebhookStore

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("managed webhook polling evidence is invalid")
    source = health_store.registry().select(source_instance)
    bindings = tuple(
        binding for binding in ManagedWebhookStore(health_store.wake_root).bindings()
        if binding.source_instance == source_instance
    )
    if not bindings:
        return
    if len(bindings) != 1:
        raise ValueError("managed webhook polling evidence is ambiguous")
    binding = bindings[0]
    if (
        binding.repository != source.repository
        or binding.repository_id != source.repository_id
        or binding.provider_host != "api.github.com"
        or source.hostname != "github.com"
    ):
        raise ValueError("managed webhook polling evidence is invalid")
    ManagedWebhookHealthEvidenceStore(health_store.wake_root).record_polling(
        binding, observed_at=int(now.timestamp()),
    )


def pending_records(root: Path) -> list[WakePath]:
    return [item for item in iter_records(root) if item.record.get("status") == "pending"]


def firing_records(root: Path) -> list[WakePath]:
    return [item for item in iter_records(root) if item.record.get("status") == "firing"]


def next_attempt_is_due(record: dict, now: datetime) -> tuple[bool, str]:
    next_attempt = record.get("next_attempt_at")
    if not isinstance(next_attempt, str) or not next_attempt:
        return True, ""
    try:
        due_at = parse_utc_timestamp(next_attempt)
    except WakeError:
        return True, ""
    if due_at > now:
        return False, next_attempt
    return True, next_attempt


def predicate_is_ready(record: dict, now: datetime) -> tuple[bool, str]:
    result = BuiltinPredicateSignals().evaluate(record, now)
    return result.ready, result.message


def _exclusive_poll(function):
    @wraps(function)
    def owned(root: Path, *args, **kwargs):
        # Use the same resolved path for custody and every operation in the pass.
        root = Path(root).resolve()
        if ownership_held(root):
            if reconciliation_required(root):
                return PollResult(skip_reason="reconciliation_required")
            return function(root, *args, **kwargs)
        with MonitorOwnership(root) as owner:
            if not owner.acquired:
                return PollResult(skip_reason="monitor_owned")
            if reconciliation_required(root):
                return PollResult(skip_reason="reconciliation_required")
            return function(root, *args, **kwargs)
    return owned


@_exclusive_poll
def poll_once(
    root: Path,
    now: datetime | None = None,
    *,
    dispatch: bool = True,
    runner: TmuxRunner | None = None,
    ack_timeout_override: float | None = None,
    app_server_codex_cmd: str | None = None,
    signal_runtime: SQLiteSignalModule | None = None,
    signal_runners: tuple[SignalSourceRunner, ...] = (),
    signal_reconcile_reason: Literal["startup", "periodic"] = "startup",
    receipt_authority_path: Path | None = None,
    time_provider=None,
    lifecycle_supervision=None,
) -> PollResult:
    from .wake_cancellation import reconcile_cancellations
    reconcile_cancellations(root)
    from .agent_handoff import poll_handoffs
    from .wake_control import read_control
    emergency = read_control(root)
    current = now
    if not emergency['paused'] and (root / 'schedules').is_dir():
        from .recurring_schedules import poll_schedules
        if time_provider is None:
            from .native_clock import snapshot
            schedule_clock = snapshot()
        else:
            from dataclasses import asdict
            schedule_clock = {'utc': asdict(time_provider()), 'counter': None}
        poll_schedules(root, schedule_clock)
    poll_handoffs(root,supervision=None if emergency['paused'] else lifecycle_supervision,
                  stop_reason='emergency_interrupt' if emergency['interrupt_requested'] else None)
    from .lifecycle_supervision import poll_spawns
    poll_spawns(root)
    checked = fired = failed = pending = dispatched = requeued = submitted = time_held = 0
    if signal_runtime is None:
        journal = signal_journal_path(root)
        if journal.is_file():
            try:
                signal_runtime = SQLiteSignalModule.open_existing(
                    journal,
                    record_publisher=WakeRecordPublisher(
                        root,
                        current_reader_capability(root),
                    ),
                )
            except Exception:
                signal_runtime = None
    if signal_runtime is not None:
        current, _ = _legacy_time_bounds(now)
    if signal_runtime is not None and current is not None:
        if not signal_runners:
            signal_runners = default_signal_runners(
                root, signal_runtime, initial_reason=signal_reconcile_reason,
                receipt_authority_path=receipt_authority_path,
            )
        firing_before = {item.record.get("id") for item in firing_records(root)}
        signal_runtime.reconcile_publications(limit=100, include_matches=False)
        firing_after = {item.record.get("id") for item in firing_records(root)}
        fired += len(firing_after - firing_before)
        signal_source_health: list[dict[str, object]] = []
        for source_runner in signal_runners:
            try:
                source_result = source_runner.reconcile(signal_runtime, current, EvaluationLimits(100))
                if source_result.instances:
                    signal_source_health.extend(
                        {
                            "source": item.source,
                            "source_instance": item.source_instance,
                            "scope": "instance",
                            "scanned": item.scanned,
                            "observed": item.observed,
                            "degraded": item.degraded,
                            "code": item.health_code,
                            "observed_at": item.observed_at.isoformat() if item.observed_at else None,
                        }
                        for item in source_result.instances
                    )
                else:
                    signal_source_health.append(
                        {
                            "source": source_result.source,
                            "source_instance": "",
                            "scope": "aggregate",
                            "scanned": source_result.scanned,
                            "observed": source_result.observed,
                            "degraded": source_result.degraded,
                        }
                    )
            except Exception:
                # Source adapters fail closed. Wake evaluation below remains
                # available for already committed observations and v1 records.
                continue
    else:
        signal_source_health = []
    terminal_signal_ids: set[str] = set()
    if signal_runtime is not None and current is not None:
        for terminal in iter_records(root):
            status = terminal.record.get("status")
            wake_id = terminal.record.get("id")
            if (
                classify_record(terminal.record) == "signal_v2"
                and status in {"submitted", "failed", "cancelled", "expired", "archived"}
                and isinstance(wake_id, str)
            ):
                terminal_signal_ids.add(wake_id)
                signal_runtime.retire_terminal_record(terminal.record, now=current)
    intent_clock = None
    for item in pending_records(root):
        checked += 1
        classification = classify_record(item.record)
        if classification == "hold":
            pending += 1
            continue
        if classification in {'native_intent_v6', 'runtime_intent_v7'}:
            from .native_intents import evaluate
            from .native_clock import snapshot
            if intent_clock is None:
                if time_provider is None:
                    intent_clock = snapshot()
                else:
                    from dataclasses import asdict
                    intent_clock = {'utc': asdict(time_provider()), 'counter': None}
            if classification == 'runtime_intent_v7':
                from .runtime_wakes import valid_record
                state = evaluate(root, item.record['id'], intent_clock, record_validator=valid_record)
            else:
                state = evaluate(root, item.record['id'], intent_clock)
            fired += int(state == 'firing')
            failed += int(state == 'failed')
            pending += int(state == 'pending')
            continue
        if classification == 'native_network_v5':
            from .network_wakes import evaluate_native_pending
            try:
                state = evaluate_native_pending(root, item.record['id'], time_provider)
            except WakeError:
                state = 'pending'
            fired += int(state == 'firing')
            failed += int(state == 'failed')
            pending += int(state == 'pending')
            continue
        if classification == 'network_v3':
            from .network_wakes import evaluate_pending
            try:
                state = evaluate_pending(root,item.record['id'],time_provider)
            except WakeError:
                pending += 1
                continue
            if state == 'firing':
                fired += 1
            elif state == 'pending':
                pending += 1
            continue
        current, upper = _legacy_time_bounds(now)
        if current is None:
            pending += 1
            time_held += 1
            continue
        from .native_delivery import expire_native
        if expire_native(root, item, current):
            failed += 1
            continue
        if (item.record.get('target', {}).get('transport') == 'native'
                and upper >= parse_utc_timestamp(item.record['target']['expires_at'])):
            pending += 1
            time_held += 1
            continue
        if classification == "signal_v2":
            if signal_runtime is None:
                pending += 1
                continue
            wake_id = item.record.get("id")
            if wake_id in terminal_signal_ids:
                pending += 1
                continue
            with WakeLifecycleLock(root, wake_id):
                try:
                    current_item = find_record(root, wake_id)
                except WakeError:
                    continue
                if (
                    classify_record(current_item.record) != "signal_v2"
                    or current_item.record.get("status") != "pending"
                ):
                    continue
                armed = signal_runtime.load_armed_signal(wake_id)
                if armed is None:
                    terminal_status = signal_runtime.terminal_status(wake_id)
                    if terminal_status in {"cancelled", "expired", "failed", "submitted"}:
                        move_record(
                            root,
                            current_item,
                            terminal_status,
                            event_type=terminal_status,
                            message=f"Signal wake reconciled to durable {terminal_status} state",
                            now=current,
                        )
                    else:
                        pending += 1
                    continue
                if armed.expires_at is not None and current < armed.expires_at <= upper:
                    authority = signal_runtime.inspect_signal_state(wake_id, record=current_item.record)
                    if not isinstance(authority, dict) or not authority.get('reservation'):
                        pending += 1
                        time_held += 1
                        continue
                outcome, source_publishes = _evaluate_signal(
                    signal_runtime,
                    armed,
                    current,
                    EvaluationLimits(100),
                    signal_runners,
                )
                if isinstance(outcome, Matched):
                    if not source_publishes:
                        signal_runtime.reconcile_match_publication(wake_id)
                    if (root / "firing" / f"{wake_id}.json").is_file():
                        fired += 1
                    else:
                        pending += 1
                elif isinstance(outcome, Expired):
                    expired = signal_runtime.expire_unreserved(wake_id, now=current)
                    if expired is True:
                        move_record(
                            root,
                            current_item,
                            "expired",
                            event_type="expired",
                            message="Signal wake expired before a match was reserved",
                            now=current,
                        )
                    else:
                        pending += 1
                else:
                    pending += 1
            continue
        item_current = current
        due_for_attempt, _next_attempt = next_attempt_is_due(item.record, item_current)
        if not due_for_attempt:
            pending += 1
            continue
        try:
            ready, message = predicate_is_ready(item.record, item_current)
        except WakeError as exc:
            from .wake_control import transition_pending
            changed = transition_pending(
                root,
                item,
                "failed",
                event_type="failed",
                message=str(exc),
                now=item_current,
                last_error=str(exc),
            )
            failed += int(changed)
            continue
        if ready:
            from .wake_control import transition_pending
            changed = transition_pending(
                root,
                item,
                "firing",
                event_type="predicate_matched",
                message=message,
                now=item_current,
            )
            fired += int(changed)
        else:
            pending += 1
    if dispatch:
        for item in firing_records(root):
            classification = classify_record(item.record)
            if classification == 'hold':
                continue
            dispatch_current = None
            if classification == 'network_v3':
                from .network_wakes import read_time, evaluation_time
                try:
                    dispatch_current = evaluation_time(read_time(time_provider))
                except WakeError:
                    continue
            elif classification not in {'native_network_v5', 'native_intent_v6', 'runtime_intent_v7'}:
                dispatch_current, upper = _legacy_time_bounds(now)
                if dispatch_current is None:
                    time_held += 1
                    continue
                if not next_attempt_is_due(item.record, dispatch_current)[0]:
                    time_held += 1
                    continue
                target = item.record.get('target', {})
                if (target.get('transport') == 'native'
                        and dispatch_current < parse_utc_timestamp(target['expires_at']) <= upper):
                    time_held += 1
                    continue
            result = dispatch_firing_record(
                root,
                item,
                runner=runner,
                now=dispatch_current,
                ack_timeout_override=ack_timeout_override,
                app_server_codex_cmd=app_server_codex_cmd,
                **(dict(time_provider=time_provider) if classify_record(item.record) in {"network_v3", "native_network_v5", "native_intent_v6", "runtime_intent_v7"} else {}),
                signal_authorizer=(
                    signal_runtime.authorize_firing_record
                    if signal_runtime is not None
                    else None
                ),
            )
            if result.status == "skipped":
                continue
            dispatched += 1
            if result.status == "submitted":
                submitted += 1
            elif result.status == "requeued":
                requeued += 1
            elif result.status == "failed":
                failed += 1
    return PollResult(
        checked=checked,
        fired=fired,
        failed=failed,
        pending=pending,
        dispatched=dispatched,
        requeued=requeued,
        submitted=submitted,
        signal_sources=tuple(signal_source_health),
        time_held=time_held,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-waked")
    parser.add_argument(
        "--wake-root",
        type=Path,
        default=None,
        help="wake runtime root; defaults to .codex/wake under the current directory",
    )
    parser.add_argument("--once", action="store_true", help="run one polling pass and exit")
    parser.add_argument("--interval", type=float, default=5.0, help="poll interval in seconds")
    parser.add_argument("--no-dispatch", action="store_true", help="evaluate predicates but do not dispatch firing records")
    parser.add_argument("--a2a-receipt-authority", type=Path, default=None,
                        help="private explicit receipt observer grants; never enrolls actors or roots")
    parser.add_argument(
        "--ack-timeout",
        type=float,
        default=None,
        help="override ack wait timeout in seconds",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = (args.wake_root or default_wake_root()).resolve()
    if args.once:
        result = poll_once(root, dispatch=not args.no_dispatch, ack_timeout_override=args.ack_timeout,
                           receipt_authority_path=args.a2a_receipt_authority)
        if not getattr(result, "skip_reason", None):
            write_monitor_health(
                wake_root=root,
                repo_root=Path.cwd(),
                source="codex-waked",
                mode="once",
                poll_result=poll_result_dict(result),
            )
        print(format_poll_result(result))
        return 0
    if args.interval <= 0:
        raise WakeError("--interval must be greater than zero")
    with MonitorOwnership(root) as owner:
        if not owner.acquired:
            print("skipped=monitor_owned", flush=True)
            return 2
        if reconciliation_required(root):
            print("skipped=reconciliation_required", flush=True)
            return 2
        signal_reconcile_reason: Literal["startup", "periodic"] = "startup"
        try:
            while True:
                if reconciliation_required(root):
                    print("skipped=reconciliation_required", flush=True)
                    return 2
                if args.interval<=5:
                    from .lifecycle_supervision import publish_supervision
                    publish_supervision(root,args.interval)
                result = poll_once(
                    root,
                    dispatch=not args.no_dispatch,
                    ack_timeout_override=args.ack_timeout,
                    signal_reconcile_reason=signal_reconcile_reason,
                    receipt_authority_path=args.a2a_receipt_authority,
                    lifecycle_supervision={'interval':args.interval} if args.no_dispatch else None,
                )
                if getattr(result, "skip_reason", None):
                    print(format_poll_result(result), flush=True)
                    return 2
                signal_reconcile_reason = "periodic"
                write_monitor_health(
                    wake_root=root,
                    repo_root=Path.cwd(),
                    source="codex-waked",
                    mode="loop",
                    poll_result=poll_result_dict(result),
                )
                if poll_result_has_activity(result):
                    print(format_poll_result(result), flush=True)
                time.sleep(args.interval)
        finally:
            if not reconciliation_required(root):
                if args.interval<=5:
                    from .lifecycle_supervision import publish_supervision,poll_spawns
                    publish_supervision(root,args.interval,active=False)
                    poll_spawns(root,stop_reason='monitor_stopped')
                from .agent_handoff import poll_handoffs
                poll_handoffs(root,stop_reason="monitor_stopped")


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except WakeError as exc:
        print(f"codex-waked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
