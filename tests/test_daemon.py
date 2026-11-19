from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from codex_wake.daemon import PollResult, default_signal_runners, format_poll_result, poll_once, poll_result_has_activity, run
from codex_wake.event_wake import EventWake
from codex_wake.records import (
    WakeLifecycleLock,
    build_record,
    cancel_record,
    find_record,
    move_record,
    write_record,
)
from codex_wake.signal_records import ManagedReaderCapability, WakeRecordPublisher, signal_journal_path
from codex_wake.signal_store import SQLiteSignalModule
from codex_wake.signals import Registration, SourceCommit
from tests.test_signal_store import make_observation
from tests.test_signals import make_adapter, make_intent


class DaemonTests(unittest.TestCase):
    def test_injected_family_restores_durable_fixture_without_construction_effects(self) -> None:
        from dataclasses import replace
        from codex_wake.filesystem_signals import FilesystemSignalAdapter, FilesystemSignalRunner
        from codex_wake.source_registry import BuiltinSourceRegistration, BuiltinSourceRegistry
        from codex_wake.signals import SourceReconcileResult

        class FixtureRunner:
            def __init__(self, candidates):
                self.candidates = candidates
                self.reconcile_calls = 0

            def reconcile(self, module, now, limits):
                self.reconcile_calls += 1
                return SourceReconcileResult("memory", 0, 0, 0)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            runtime = SQLiteSignalModule(
                signal_journal_path(root),
                record_publisher=WakeRecordPublisher(
                    root, ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
                ),
            )
            adapter = make_adapter()
            for wake_id in ("wake_z", "wake_a"):
                registration = EventWake(
                    runtime, adapters=(adapter,),
                    clock=lambda: datetime(2026, 9, 15, tzinfo=UTC),
                    id_factory=lambda wake_id=wake_id: wake_id,
                ).register(make_intent(), idempotency_key=wake_id)
                self.assertIsInstance(registration, Registration)
            filesystem = FilesystemSignalAdapter(Path(tmp), "result.txt")
            registration = EventWake(
                runtime, adapters=(filesystem,),
                clock=lambda: datetime(2026, 9, 15, tzinfo=UTC),
                id_factory=lambda: "wake_filesystem",
            ).register(replace(
                make_intent(), when=filesystem.request("created"),
                resume=replace(make_intent().resume, cwd=Path(tmp)),
            ), idempotency_key="filesystem")
            self.assertIsInstance(registration, Registration)
            # Reconstruction uses a fresh journal object, not registration memory.
            runtime = SQLiteSignalModule(signal_journal_path(root))
            runtime.load_armed_signal("wake_a")
            before = {path.relative_to(root): path.read_bytes()
                      for path in root.rglob("*") if path.is_file()}
            calls = []

            def construct(context, candidates):
                self.assertEqual(context.root, root)
                self.assertEqual(context.initial_reason, "periodic")
                calls.append(candidates)
                return (FixtureRunner(candidates),)

            registry = BuiltinSourceRegistry((
                BuiltinSourceRegistration("fixture", {("memory", "job.completed")}, construct),
            ))
            with patch("codex_wake.daemon.dispatch_firing_record") as dispatch, patch(
                "codex_wake.github_client.GitHubRestClient"
            ) as provider, patch.object(runtime, "ingest") as ingest, patch.object(
                runtime, "evaluate"
            ) as evaluate:
                existing = default_signal_runners(root, runtime)
                self.assertEqual(tuple(type(runner) for runner in existing), (FilesystemSignalRunner,))
                with patch.object(runtime, "load_armed_signal", wraps=runtime.load_armed_signal) as loader:
                    runners = default_signal_runners(
                        root, runtime, initial_reason="periodic", source_registry=registry,
                    )
                    loaded = [call.args[0] for call in loader.call_args_list]
                    self.assertEqual(sorted(loaded), ["wake_a", "wake_filesystem", "wake_z"])
                dispatch.assert_not_called()
                provider.assert_not_called()
                ingest.assert_not_called()
                evaluate.assert_not_called()

            self.assertEqual(len(calls), 1)
            self.assertEqual([item.armed.wake_id for item in calls[0]], ["wake_a", "wake_z"])
            self.assertEqual(tuple(type(runner) for runner in runners),
                             (FilesystemSignalRunner, FixtureRunner))
            self.assertEqual(runners[1].reconcile_calls, 0)
            self.assertEqual(before, {path.relative_to(root): path.read_bytes()
                                     for path in root.rglob("*") if path.is_file()})

    def test_empty_registry_preserves_empty_default_reconstruction(self) -> None:
        from unittest.mock import Mock
        from codex_wake.source_registry import BuiltinSourceRegistry

        registry = Mock(spec=BuiltinSourceRegistry)
        extra = Mock()
        registry.reconstruct.return_value = (extra,)
        root = Path("/unused")
        runtime = Mock()
        # An empty injection must not change the compatibility result.
        with patch("codex_wake.daemon.pending_records", return_value=[]):
            self.assertEqual(default_signal_runners(root, runtime), ())
            self.assertEqual(default_signal_runners(
                root, runtime, source_registry=BuiltinSourceRegistry(()),
            ), ())
            self.assertEqual(default_signal_runners(root, runtime, source_registry=registry), (extra,))
        registry.reconstruct.assert_called_once()
        runtime.load_armed_signal.assert_not_called()

    def test_default_runner_uses_the_shared_builtin_catalogue(self) -> None:
        from codex_wake.daemon import GitHubSignalRunner
        from codex_wake.source_registry import builtin_source_registry

        runtime = Mock()
        captured = []

        def construct_catalogue(**kwargs):
            catalogue = builtin_source_registry(**kwargs)
            captured.append(catalogue)
            return catalogue

        with patch("codex_wake.daemon.pending_records", return_value=[]), patch(
            "codex_wake.daemon.builtin_source_registry", side_effect=construct_catalogue,
        ) as constructor:
            self.assertEqual(default_signal_runners(Path("/unused"), runtime), ())

        constructor.assert_called_once()
        self.assertIs(constructor.call_args.kwargs["github_runner_factory"], GitHubSignalRunner)
        self.assertEqual(captured[0].inventory, builtin_source_registry().inventory)
        runtime.load_armed_signal.assert_not_called()

    def test_default_runner_restores_configured_systemd_transition_and_publishes(self) -> None:
        from codex_wake.runtime_signals import RuntimeSourceRegistry
        from codex_wake.signals import Resume, WakeIntent
        from codex_wake.systemd_signals import (
            SystemdReadCapability, SystemdSignalAdapter, SystemdUnitState,
        )
        from codex_wake.systemd_source_config import SystemdSourceConfig, SystemdSourceStore

        class FixtureManager:
            state = "inactive"

            def resolve_unit(self, unit: str, *, timeout_seconds: int) -> str:
                return unit

            def read_unit(self, unit: str, *, timeout_seconds: int) -> SystemdUnitState:
                return SystemdUnitState(unit, self.state, "manager-a")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            source = SystemdSourceConfig(
                "build-state", "build.service", os.geteuid(),
                frozenset({"active", "failed"}),
            )
            SystemdSourceStore(root).configure(source)
            allowed = tuple(source.descriptor(state) for state in source.target_states)
            manager = FixtureManager()
            registration_adapter = SystemdSignalAdapter(
                source,
                manager,
                RuntimeSourceRegistry({"systemd.unit": lambda descriptor: descriptor in allowed}),
                SystemdReadCapability("user", os.geteuid()),
            )
            runtime = SQLiteSignalModule(
                signal_journal_path(root),
                record_publisher=WakeRecordPublisher(
                    root, ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
                ),
            )
            registration = EventWake(
                runtime, adapters=(registration_adapter,),
                clock=lambda: datetime(2026, 9, 15, tzinfo=UTC),
                id_factory=lambda: "wake_systemd_v2",
            ).register(
                WakeIntent(
                    registration_adapter.request("active"),
                    Resume("continue", Path(tmp), {
                        "transport": "tmux", "tmux_socket": "/tmp/fixture", "pane": "%1",
                    }),
                ),
                idempotency_key="systemd-v2",
            )
            self.assertIsInstance(registration, Registration)
            runners = default_signal_runners(
                root, runtime, systemd_backend_factory=lambda _source: manager
            )
            manager.state = "active"

            result = poll_once(
                root,
                now=datetime(2026, 9, 15, 0, 0, 1, tzinfo=UTC),
                dispatch=False,
                signal_runtime=runtime,
                signal_runners=runners,
            )

            self.assertEqual((result.fired, result.pending), (1, 0))
            self.assertEqual(result.signal_sources[0]["source"], "systemd")
            self.assertEqual(result.signal_sources[0]["code"], "SYSTEMD_READY")
            self.assertEqual(result.signal_sources[0]["observed_at"], "2026-09-15T00:00:01+00:00")
            self.assertTrue((root / "firing" / "wake_systemd_v2.json").is_file())

    def test_systemd_revocation_blocks_generic_evaluation_and_publication(self) -> None:
        from codex_wake.runtime_signals import RuntimeSourceRegistry
        from codex_wake.signals import EvaluationLimits, Resume, WakeIntent
        from codex_wake.systemd_signals import (
            SystemdReadCapability, SystemdSignalAdapter, SystemdUnitState,
        )
        from codex_wake.systemd_source_config import SystemdSourceConfig, SystemdSourceStore

        class FixtureManager:
            state = "inactive"

            def resolve_unit(self, unit: str, *, timeout_seconds: int) -> str:
                return unit

            def read_unit(self, unit: str, *, timeout_seconds: int) -> SystemdUnitState:
                return SystemdUnitState(unit, self.state, "manager-a")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            source = SystemdSourceConfig(
                "build-state", "build.service", os.geteuid(), frozenset({"active"})
            )
            store = SystemdSourceStore(root)
            store.configure(source)
            manager = FixtureManager()
            adapter = SystemdSignalAdapter(
                source,
                manager,
                RuntimeSourceRegistry({"systemd.unit": lambda _descriptor: True}),
                SystemdReadCapability("user", os.geteuid()),
            )
            runtime = SQLiteSignalModule(
                signal_journal_path(root),
                record_publisher=WakeRecordPublisher(
                    root, ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
                ),
            )
            registration = EventWake(
                runtime, adapters=(adapter,),
                clock=lambda: datetime(2026, 9, 15, tzinfo=UTC),
                id_factory=lambda: "wake_revoked_systemd",
            ).register(
                WakeIntent(
                    adapter.request("active"),
                    Resume("continue", Path(tmp), {
                        "transport": "tmux", "tmux_socket": "/tmp/fixture", "pane": "%1",
                    }),
                ),
                idempotency_key="revoked-systemd-v2",
            )
            armed = runtime.load_armed_signal(registration.wake_id)
            runner = default_signal_runners(
                root, runtime, systemd_backend_factory=lambda _source: manager
            )[0]
            runner.reconcile(runtime, datetime(2026, 9, 15, 0, 0, 1, tzinfo=UTC), EvaluationLimits(8))
            manager.state = "active"
            runner.reconcile(runtime, datetime(2026, 9, 15, 0, 0, 2, tzinfo=UTC), EvaluationLimits(8))
            store.configure(SystemdSourceConfig(
                "build-state", "build.service", os.geteuid(),
                frozenset({"active"}), enabled=False,
            ))

            result = poll_once(
                root,
                now=datetime(2026, 9, 15, 0, 0, 3, tzinfo=UTC),
                dispatch=False,
                signal_runtime=runtime,
                signal_runners=(runner,),
            )

            self.assertEqual((result.fired, result.pending), (0, 1))
            self.assertTrue((root / "pending" / "wake_revoked_systemd.json").is_file())
            self.assertFalse((root / "firing" / "wake_revoked_systemd.json").exists())

    def test_default_runner_restores_process_exit_and_publishes_one_transition(self) -> None:
        from codex_wake.process_signals import ProcessExitAdapter, ProcessExitSample
        from codex_wake.runtime_signals import RuntimeSourceDescriptor, RuntimeSourceRegistry
        from codex_wake.signals import Resume, WakeIntent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            identity = {
                "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
                "pid": 123,
                "start_time_ticks": 456,
                "owner_uid": 1000,
            }
            descriptor = RuntimeSourceDescriptor.parse({
                "version": 1, "kind": "process.exit",
                "resource": identity, "target_state": "terminated",
            })
            sample = {"value": ProcessExitSample.alive(**identity)}
            adapter = ProcessExitAdapter(
                descriptor,
                RuntimeSourceRegistry({"process.exit": lambda candidate: candidate == descriptor}),
                lambda: sample["value"],
                lambda: 1000,
            )
            runtime = SQLiteSignalModule(
                signal_journal_path(root),
                record_publisher=WakeRecordPublisher(
                    root, ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
                ),
            )
            registration = EventWake(
                runtime, adapters=(adapter,),
                clock=lambda: datetime(2026, 9, 15, tzinfo=UTC),
                id_factory=lambda: "wake_process_v2",
            ).register(
                WakeIntent(
                    adapter.request(),
                    Resume("continue", Path(tmp), {
                        "transport": "tmux", "tmux_socket": "/tmp/fixture", "pane": "%1",
                    }),
                ),
                idempotency_key="process-v2",
            )
            self.assertIsInstance(registration, Registration)
            with patch(
                "codex_wake.process_signals.restore_production_process_exit_adapter",
                return_value=adapter,
            ):
                runners = default_signal_runners(root, runtime)
            self.assertEqual(len(runners), 1)
            sample["value"] = ProcessExitSample.zombie(**identity)

            result = poll_once(
                root,
                now=datetime(2026, 9, 15, 0, 0, 1, tzinfo=UTC),
                dispatch=False,
                signal_runtime=runtime,
                signal_runners=runners,
            )

            self.assertEqual((result.fired, result.pending), (1, 0))
            self.assertEqual(result.signal_sources[0]["source"], "runtime")
            self.assertEqual(result.signal_sources[0]["code"], "RUNTIME_READY")
            self.assertEqual(result.signal_sources[0]["observed_at"], "2026-09-15T00:00:01+00:00")
            self.assertTrue((root / "firing" / "wake_process_v2.json").is_file())

    def test_process_runtime_revocation_blocks_generic_evaluation_and_publication(self) -> None:
        from codex_wake.process_signals import ProcessExitAdapter, ProcessExitSample
        from codex_wake.runtime_signals import RuntimeSourceDescriptor, RuntimeSourceRegistry
        from codex_wake.signals import EvaluationLimits, Resume, WakeIntent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            identity = {
                "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
                "pid": 123,
                "start_time_ticks": 456,
                "owner_uid": 1000,
            }
            descriptor = RuntimeSourceDescriptor.parse({
                "version": 1, "kind": "process.exit",
                "resource": identity, "target_state": "terminated",
            })
            allowed = {"value": True}
            sample = {"value": ProcessExitSample.alive(**identity)}
            adapter = ProcessExitAdapter(
                descriptor,
                RuntimeSourceRegistry({
                    "process.exit": lambda candidate: allowed["value"] and candidate == descriptor
                }),
                lambda: sample["value"],
                lambda: 1000,
            )
            runtime = SQLiteSignalModule(
                signal_journal_path(root),
                record_publisher=WakeRecordPublisher(
                    root, ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
                ),
            )
            registration = EventWake(
                runtime, adapters=(adapter,),
                clock=lambda: datetime(2026, 9, 15, tzinfo=UTC),
                id_factory=lambda: "wake_revoked_process",
            ).register(
                WakeIntent(
                    adapter.request(),
                    Resume("continue", Path(tmp), {
                        "transport": "tmux", "tmux_socket": "/tmp/fixture", "pane": "%1",
                    }),
                ),
                idempotency_key="revoked-process-v2",
            )
            armed = runtime.load_armed_signal(registration.wake_id)
            sample["value"] = ProcessExitSample.zombie(**identity)
            adapter.reconcile(
                runtime, (armed,), datetime(2026, 9, 15, 0, 0, 1, tzinfo=UTC),
                EvaluationLimits(8),
            )
            allowed["value"] = False

            result = poll_once(
                root,
                now=datetime(2026, 9, 15, 0, 0, 2, tzinfo=UTC),
                dispatch=False,
                signal_runtime=runtime,
                signal_runners=(adapter.runner((armed,)),),
            )

            self.assertEqual((result.fired, result.pending), (0, 1))
            self.assertTrue((root / "pending" / "wake_revoked_process.json").is_file())
            self.assertFalse((root / "firing" / "wake_revoked_process.json").exists())

    def test_github_candidate_budget_is_applied_after_grouping_arms_by_source(self) -> None:
        from dataclasses import replace
        from datetime import timedelta

        from codex_wake.github_polling import GitHubPollingAdapter
        from codex_wake.github_source_config import GitHubSourceStore
        from codex_wake.signals import EvaluationLimits
        from tests.test_github_polling import FixtureClient, NOW, config

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            sources = (
                replace(config(evidence_mode="positive_only"), source_instance="github-a"),
                replace(config(evidence_mode="positive_only"), source_instance="github-b"),
            )
            store = GitHubSourceStore(root)
            for source in sources:
                store.configure(source)
            publisher = WakeRecordPublisher(
                root,
                ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
            )
            runtime = SQLiteSignalModule(signal_journal_path(root), record_publisher=publisher)
            for source, count in ((sources[0], 3), (sources[1], 1)):
                adapter = GitHubPollingAdapter(source, object())
                request = adapter.request(
                    ref="refs/heads/main", conclusions=("success",)
                )
                for index in range(count):
                    wake_id = f"wake_{source.source_instance}_{index}"
                    registration = EventWake(
                        runtime,
                        adapters=(adapter,),
                        clock=lambda: NOW,
                        id_factory=lambda wake_id=wake_id: wake_id,
                    ).register(
                        replace(make_intent(), when=request, max_attempts=1),
                        idempotency_key=wake_id,
                    )
                    self.assertIsInstance(registration, Registration)
            clients = {source.source_instance: FixtureClient() for source in sources}
            runners = default_signal_runners(
                root,
                runtime,
                github_client_factory=lambda source: clients[source.source_instance],
            )

            report = runners[0].reconcile(
                runtime,
                NOW + timedelta(seconds=1),
                EvaluationLimits(max_candidates=2),
            )

            self.assertEqual(
                [item.source_instance for item in report.instances],
                ["github-a", "github-b"],
            )
            self.assertEqual(
                {name: len(client.requests) for name, client in clients.items()},
                {"github-a": 1, "github-b": 1},
            )

    def test_default_runners_poll_only_referenced_enabled_github_source_with_fixture_client(self) -> None:
        from dataclasses import replace
        from datetime import timedelta

        from codex_wake.github_polling import GitHubPollingAdapter
        from codex_wake.github_source_config import GitHubSourceStore
        from tests.test_github_polling import FixtureClient, NOW, config, run as github_run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            source = config(evidence_mode="positive_only")
            store = GitHubSourceStore(root)
            store.configure(source)
            store.configure(replace(source, source_instance="unreferenced"))
            publisher = WakeRecordPublisher(
                root,
                ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
            )
            runtime = SQLiteSignalModule(
                signal_journal_path(root), record_publisher=publisher
            )
            registration_adapter = GitHubPollingAdapter(source, object())
            request = registration_adapter.request(
                ref="refs/heads/main", conclusions=("success",)
            )
            registration = EventWake(
                runtime,
                adapters=(registration_adapter,),
                clock=lambda: NOW,
                id_factory=lambda: "wake_github",
            ).register(
                replace(make_intent(), when=request, max_attempts=1),
                idempotency_key="github-main-success",
            )
            self.assertIsInstance(registration, Registration)
            disabled_source = replace(source, source_instance="aaa-disabled")
            store.configure(disabled_source)
            disabled_adapter = GitHubPollingAdapter(disabled_source, object())
            disabled_registration = EventWake(
                runtime,
                adapters=(disabled_adapter,),
                clock=lambda: NOW,
                id_factory=lambda: "wake_disabled_github",
            ).register(
                replace(
                    make_intent(),
                    when=disabled_adapter.request(
                        ref="refs/heads/main", conclusions=("success",)
                    ),
                    max_attempts=1,
                ),
                idempotency_key="github-disabled",
            )
            self.assertIsInstance(disabled_registration, Registration)
            store.configure(replace(disabled_source, enabled=False))
            constructed = []

            def client_factory(selected):
                constructed.append(selected.source_instance)
                return FixtureClient(
                    [
                        github_run(
                            completed_at=None,
                            terminal_proof_at=NOW + timedelta(seconds=1),
                            time_provenance="github_attempt_started_or_job_completed_lower_bound",
                        )
                    ]
                )

            runners = default_signal_runners(
                root, runtime, github_client_factory=client_factory
            )
            result = poll_once(
                root,
                now=NOW + timedelta(seconds=2),
                dispatch=False,
                signal_runtime=runtime,
                signal_runners=runners,
            )

            self.assertEqual(constructed, ["github-ci"])
            self.assertEqual((result.fired, result.pending), (1, 1))
            self.assertEqual(result.signal_sources[0]["source"], "github")
            self.assertEqual(result.signal_sources[0]["observed"], 1)
            self.assertEqual(result.signal_sources[0]["degraded"], 1)
            self.assertEqual(
                result.signal_sources[0]["code"], "GITHUB_COVERAGE_UNPROVEN",
            )
            self.assertEqual(
                result.signal_sources[0]["observed_at"],
                (NOW + timedelta(seconds=2)).isoformat(),
            )
            self.assertEqual(
                GitHubSourceStore(root).source_health("github-ci").code,
                "GITHUB_COVERAGE_UNPROVEN",
            )
            self.assertTrue((root / "firing" / "wake_github.json").is_file())

    def test_managed_github_poll_records_fresh_owner_bound_health_evidence(self) -> None:
        from dataclasses import replace
        from datetime import timedelta

        from codex_wake.daemon import GitHubSignalRunner
        from codex_wake.github_polling import GitHubPollingAdapter
        from codex_wake.github_source_config import GitHubSourceStore
        from codex_wake.managed_webhook_health import (
            PollingFallbackHealth, ProviderDeliveryHealth,
        )
        from codex_wake.managed_webhook_health_evidence import ManagedWebhookHealthEvidenceStore
        from codex_wake.managed_webhooks import ManagedWebhookBinding, ManagedWebhookStore
        from codex_wake.signals import ArmContext, EvaluationLimits, WakeId
        from tests.test_github_polling import FixtureClient, NOW, config, run as github_run
        from tests.test_signal_store import make_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            source = config(evidence_mode="positive_only")
            GitHubSourceStore(root).configure(source)
            binding = ManagedWebhookStore(root).save(ManagedWebhookBinding(
                owner_id="managed-owner", installation_id="managed-install",
                canonical_root=str(root.resolve()), owner_uid=os.getuid(),
                provider_host="api.github.com", source_instance=source.source_instance,
                repository=source.repository, repository_id=source.repository_id,
                callback_url="https://hooks.example.test/github/webhook", events=("workflow_run",),
                service_id="codex-wake-github-webhook-github-ci.service",
                executable_id="codex-wake-github-webhook",
                provider_credential_ref="GITHUB_ADMIN_TOKEN", secret_generation=1,
            ))
            module = make_module(signal_journal_path(root))
            adapter = GitHubPollingAdapter(source, FixtureClient([
                github_run(
                    completed_at=None, terminal_proof_at=NOW + timedelta(seconds=1),
                    time_provenance="github_attempt_started_or_job_completed_lower_bound",
                ),
            ]))
            request = adapter.request(ref="refs/heads/main", conclusions=("success",))
            armed = module.arm(
                WakeId("managed-poll-health"), request,
                ArmContext("managed-poll-health", "managed-poll-health", NOW, None,
                           make_intent().resume, adapter),
            )
            self.assertEqual(type(armed).__name__, "ArmedSignal")
            runner = GitHubSignalRunner(
                {source.source_instance: adapter}, armed_signals=(armed,),
                health_store=GitHubSourceStore(root),
            )
            runner.reconcile(module, NOW + timedelta(seconds=2), EvaluationLimits(1))

            delivery, polling = ManagedWebhookHealthEvidenceStore(root).project(
                binding, now=int((NOW + timedelta(seconds=2)).timestamp()),
            )
            self.assertEqual(delivery, ProviderDeliveryHealth.UNPROVEN)
            self.assertEqual(polling, PollingFallbackHealth.READY)

    def test_github_retry_deadline_survives_runner_restart_and_degradation_cannot_match(self) -> None:
        from dataclasses import replace
        from datetime import timedelta

        from codex_wake.github_polling import GitHubPollingAdapter, GitHubReadError
        from codex_wake.github_source_config import GitHubSourceStore
        from tests.test_github_polling import FixtureClient, NOW, config

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            source = config(evidence_mode="positive_only")
            GitHubSourceStore(root).configure(source)
            publisher = WakeRecordPublisher(
                root,
                ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
            )
            runtime = SQLiteSignalModule(signal_journal_path(root), record_publisher=publisher)
            registration_adapter = GitHubPollingAdapter(source, object())
            registration = EventWake(
                runtime,
                adapters=(registration_adapter,),
                clock=lambda: NOW,
                id_factory=lambda: "wake_github_retry",
            ).register(
                replace(
                    make_intent(),
                    when=registration_adapter.request(
                        ref="refs/heads/main", conclusions=("failure",)
                    ),
                    max_attempts=1,
                ),
                idempotency_key="github-main-failure",
            )
            self.assertIsInstance(registration, Registration)
            retry_at = NOW + timedelta(minutes=10)
            failed_client = FixtureClient(pages=[GitHubReadError("rate_limit", retry_at=retry_at)])

            first = poll_once(
                root,
                now=NOW + timedelta(seconds=1),
                dispatch=False,
                signal_runtime=runtime,
                signal_runners=default_signal_runners(
                    root, runtime, github_client_factory=lambda _source: failed_client
                ),
            )
            script = r'''
import json, sys
from pathlib import Path
from datetime import timedelta
from codex_wake.daemon import default_signal_runners, poll_once
from codex_wake.github_source_config import GitHubSourceStore
from codex_wake.signal_records import ManagedReaderCapability, WakeRecordPublisher, signal_journal_path
from codex_wake.signal_store import SQLiteSignalModule
from tests.test_github_polling import FixtureClient, NOW
root = Path(sys.argv[1])
runtime = SQLiteSignalModule.open_existing(
    signal_journal_path(root),
    record_publisher=WakeRecordPublisher(
        root, ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True)
    ),
)
client = FixtureClient(pages=[AssertionError("provider read before retry deadline")])
result = poll_once(
    root,
    now=NOW + timedelta(seconds=2),
    dispatch=False,
    signal_runtime=runtime,
    signal_runners=default_signal_runners(
        root, runtime, github_client_factory=lambda _source: client
    ),
)
print(json.dumps({
    "fired": result.fired,
    "pending": result.pending,
    "request_count": len(client.requests),
    "retry_at": GitHubSourceStore(root).retry_failure("github-ci").retry_at.isoformat(),
}))
'''
            restarted_process = subprocess.run(
                [sys.executable, "-c", script, str(root)],
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )
            restarted = json.loads(restarted_process.stdout)

            self.assertEqual((first.fired, first.pending), (0, 1))
            self.assertEqual((restarted["fired"], restarted["pending"]), (0, 1))
            self.assertEqual(restarted["request_count"], 0)
            self.assertEqual(
                GitHubSourceStore(root).retry_failure("github-ci").retry_at,
                retry_at,
            )
            self.assertEqual(restarted["retry_at"], retry_at.isoformat())
            self.assertTrue((root / "pending" / "wake_github_retry.json").is_file())
            self.assertFalse((root / "firing" / "wake_github_retry.json").exists())

    def test_loop_marks_only_its_first_default_source_pass_as_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            with (
                patch(
                    "codex_wake.daemon.poll_once",
                    side_effect=(PollResult(), KeyboardInterrupt()),
                ) as polling,
                patch("codex_wake.daemon.write_monitor_health"),
                patch("codex_wake.daemon.time.sleep"),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    run(["--wake-root", str(root), "--no-dispatch", "--interval", "0.1"])

            self.assertEqual(
                [call.kwargs["signal_reconcile_reason"] for call in polling.call_args_list],
                ["startup", "periodic"],
            )

    def test_v1_not_ready_record_bytes_survive_repeated_restart_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            record = self.make_record(
                tmp,
                {"type": "not_before", "due_at": "2026-05-18T21:15:00Z"},
            )
            record["id"] = "wake_v1_restart"
            pending_path = write_record(root, record)
            original = pending_path.read_bytes()

            first = poll_once(
                root,
                now=datetime(2026, 5, 18, 21, 13, tzinfo=UTC),
                dispatch=False,
            )
            restarted = poll_once(
                root,
                now=datetime(2026, 5, 18, 21, 14, tzinfo=UTC),
                dispatch=False,
            )

            self.assertEqual((first.pending, restarted.pending), (1, 1))
            self.assertEqual(pending_path.read_bytes(), original)

    def test_mixed_root_keeps_v1_healthy_and_holds_unreadable_signal_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            ready = self.make_record(
                tmp,
                {"type": "not_before", "due_at": "2026-05-18T21:15:00Z"},
            )
            ready["id"] = "wake_v1"
            v1_signal = self.make_record(tmp, {"type": "signal"})
            v1_signal["id"] = "wake_v1_signal"
            malformed_v2 = self.make_record(tmp, {"type": "signal"})
            malformed_v2.update({"id": "wake_bad_v2", "schema_version": 2})
            for record in (ready, v1_signal, malformed_v2):
                write_record(root, record)

            result = poll_once(
                root,
                now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC),
                dispatch=False,
            )

            self.assertEqual((result.fired, result.failed, result.pending), (1, 0, 2))
            self.assertTrue((root / "firing" / "wake_v1.json").exists())
            self.assertTrue((root / "pending" / "wake_v1_signal.json").exists())
            self.assertTrue((root / "pending" / "wake_bad_v2.json").exists())

    def test_upgrade_mixed_root_evaluates_v1_and_v2_without_cross_schema_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            runtime = SQLiteSignalModule(
                signal_journal_path(root),
                record_publisher=WakeRecordPublisher(
                    root,
                    ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
                ),
            )
            EventWake(
                runtime,
                adapters=[make_adapter()],
                clock=lambda: datetime(2026, 9, 14, 14, 0, tzinfo=UTC),
                id_factory=lambda: "wake_signal",
            ).register(make_intent(), idempotency_key="job-42")
            runtime.ingest(
                [make_observation()],
                SourceCommit(
                    "memory",
                    "contract-test",
                    "checkpoint-1",
                    1,
                    datetime(2026, 9, 14, 14, 1, tzinfo=UTC),
                ),
            )
            legacy = self.make_record(
                tmp,
                {"type": "not_before", "due_at": "2026-09-14T14:01:00Z"},
            )
            legacy["id"] = "wake_v1"
            write_record(root, legacy)

            result = poll_once(
                root,
                now=datetime(2026, 9, 14, 14, 2, tzinfo=UTC),
                dispatch=False,
                signal_runtime=runtime,
            )

            self.assertEqual((result.fired, result.failed, result.pending), (2, 0, 0))
            v1 = json.loads((root / "firing" / "wake_v1.json").read_text())
            v2 = json.loads((root / "firing" / "wake_signal.json").read_text())
            self.assertEqual((v1["schema_version"], v2["schema_version"]), (1, 2))
            self.assertEqual(v1["events"][-1]["type"], "predicate_matched")
            self.assertIn("trigger_match", v2)

    def test_signal_registration_ingest_and_poll_publishes_one_firing_record_without_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            capability = ManagedReaderCapability(
                root, "reader-1", 1, frozenset({1, 2}), True
            )
            signal_runtime = SQLiteSignalModule(
                signal_journal_path(root),
                record_publisher=WakeRecordPublisher(root, capability),
            )
            registration = EventWake(
                signal_runtime,
                adapters=[make_adapter()],
                clock=lambda: datetime(2026, 9, 14, 14, 0, tzinfo=UTC),
                id_factory=lambda: "wake_signal",
            ).register(make_intent(), idempotency_key="job-42")
            self.assertIsInstance(registration, Registration)
            signal_runtime.ingest(
                [make_observation()],
                SourceCommit(
                    "memory", "contract-test", "checkpoint-1", 1,
                    datetime(2026, 9, 14, 14, 1, tzinfo=UTC),
                ),
            )

            result = poll_once(
                root,
                now=datetime(2026, 9, 14, 14, 2, tzinfo=UTC),
                dispatch=False,
            )

            self.assertEqual((result.fired, result.dispatched), (1, 0))
            self.assertFalse((root / "pending" / "wake_signal.json").exists())
            firing = json.loads((root / "firing" / "wake_signal.json").read_text())
            self.assertEqual(firing["record_revision"], 2)
            self.assertEqual(firing["status"], "firing")
            self.assertEqual(firing["trigger_match"]["verification"]["state"], "verified")
            self.assertEqual(firing["trigger_match"]["verification"]["method"], "scripted")
            self.assertEqual(len(firing["trigger_match"]["evidence_digest"]), 64)

    def test_terminal_signal_is_not_republished_as_stale_pending_on_next_poll(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            runtime = SQLiteSignalModule(
                signal_journal_path(root),
                record_publisher=WakeRecordPublisher(
                    root,
                    ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
                ),
            )
            EventWake(
                runtime,
                adapters=[make_adapter()],
                clock=lambda: datetime(2026, 9, 14, 14, 0, tzinfo=UTC),
                id_factory=lambda: "wake_signal",
            ).register(make_intent(), idempotency_key="job-42")
            stale_pending = (root / "pending" / "wake_signal.json").read_bytes()
            runtime.ingest(
                [make_observation()],
                SourceCommit(
                    "memory", "contract-test", "checkpoint-1", 1,
                    datetime(2026, 9, 14, 14, 1, tzinfo=UTC),
                ),
            )
            poll_once(
                root,
                now=datetime(2026, 9, 14, 14, 2, tzinfo=UTC),
                dispatch=False,
                signal_runtime=runtime,
            )
            move_record(
                root,
                find_record(root, "wake_signal"),
                "submitted",
                event_type="ack_observed",
                message="Wake prompt submission ack observed",
                now=datetime(2026, 9, 14, 14, 3, tzinfo=UTC),
            )
            (root / "pending" / "wake_signal.json").write_bytes(stale_pending)

            poll_once(
                root,
                now=datetime(2026, 9, 14, 14, 4, tzinfo=UTC),
                dispatch=False,
                signal_runtime=runtime,
            )

            self.assertTrue((root / "submitted" / "wake_signal.json").is_file())
            self.assertFalse((root / "pending" / "wake_signal.json").exists())

    def test_signal_cancellation_wins_before_evaluation_and_cannot_be_republished(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            runtime = SQLiteSignalModule(
                signal_journal_path(root),
                record_publisher=WakeRecordPublisher(
                    root,
                    ManagedReaderCapability(root, "reader", 1, frozenset({1, 2}), True),
                ),
            )
            EventWake(
                runtime,
                adapters=[make_adapter()],
                clock=lambda: datetime(2026, 9, 14, 14, 0, tzinfo=UTC),
                id_factory=lambda: "wake_signal",
            ).register(make_intent(), idempotency_key="job-42")
            runtime.ingest(
                [make_observation()],
                SourceCommit(
                    "memory", "contract-test", "checkpoint-1", 1,
                    datetime(2026, 9, 14, 14, 1, tzinfo=UTC),
                ),
            )
            cancellation_holds_lock = threading.Event()
            release_cancellation = threading.Event()
            evaluation_attempted_lock = threading.Event()

            def cancellation_checkpoint(name: str) -> None:
                if name == "after_cancel_lock":
                    cancellation_holds_lock.set()
                    self.assertTrue(release_cancellation.wait(timeout=5))

            class ProbedLifecycleLock:
                def __init__(self, lock_root: Path, wake_id: str) -> None:
                    self._lock = WakeLifecycleLock(lock_root, wake_id)

                def __enter__(self):
                    evaluation_attempted_lock.set()
                    return self._lock.__enter__()

                def __exit__(self, exc_type, exc, tb) -> None:
                    self._lock.__exit__(exc_type, exc, tb)

            with ThreadPoolExecutor(max_workers=2) as pool:
                cancellation = pool.submit(
                    cancel_record,
                    root,
                    "wake_signal",
                    datetime(2026, 9, 14, 14, 2, tzinfo=UTC),
                    checkpoint=cancellation_checkpoint,
                )
                self.assertTrue(cancellation_holds_lock.wait(timeout=5))
                with patch("codex_wake.daemon.WakeLifecycleLock", ProbedLifecycleLock, create=True):
                    evaluation = pool.submit(
                        poll_once,
                        root,
                        datetime(2026, 9, 14, 14, 3, tzinfo=UTC),
                        dispatch=False,
                        signal_runtime=runtime,
                    )
                    attempted = evaluation_attempted_lock.wait(timeout=1)
                    if attempted:
                        self.assertFalse(evaluation.done())
                    release_cancellation.set()
                    cancellation.result(timeout=5)
                    result = evaluation.result(timeout=5)
            self.assertTrue(attempted)
            self.assertEqual(result.fired, 0)
            self.assertTrue((root / "cancelled" / "wake_signal.json").is_file())
            self.assertFalse((root / "pending" / "wake_signal.json").exists())
            self.assertFalse((root / "firing" / "wake_signal.json").exists())
            runtime.reconcile_publications(limit=100)
            self.assertFalse((root / "firing" / "wake_signal.json").exists())

    def make_record(self, tmp: str, predicate: dict) -> dict:
        now = datetime(2026, 5, 18, 20, 30, tzinfo=UTC)
        record = build_record(
            predicate=predicate,
            prompt="continue",
            cwd=Path(tmp),
            target={"transport": "tmux", "tmux_socket": "/tmp/tmux/default", "pane": "%1"},
            now=now,
        )
        record["id"] = f"wake_{len(predicate)}"
        return record

    def test_default_poll_uses_qualified_lower_for_legacy_not_before(self):
        from test_measurements import observation
        clock=observation(1000)
        lower=datetime(2026,5,18,21,14,59,tzinfo=UTC).timestamp()+.25
        clock['utc'].update(lower=lower,upper=lower+2)
        with tempfile.TemporaryDirectory() as tmp,patch('codex_wake.measurements.snapshot',return_value=clock), \
                patch('codex_wake.daemon.utc_now',return_value=datetime(2026,5,18,21,15,1,tzinfo=UTC)):
            root=Path(tmp)/'wake'
            record=self.make_record(tmp,dict(type='not_before',due_at='2026-05-18T21:15:00Z'))
            write_record(root,record)
            result=poll_once(root,dispatch=False)
            self.assertEqual(result.fired,0)
            self.assertEqual(result.pending,1)
            self.assertEqual(find_record(root,record['id']).record['predicate'],record['predicate'])

    def test_missing_utc_holds_legacy_pending_and_firing_without_dispatch(self):
        from codex_wake.measurements import TimeUnavailable
        from tests.test_injector import FakeTmuxRunner
        from codex_wake.daemon import poll_result_dict
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';runner=FakeTmuxRunner()
            for status in ('pending','firing'):
                record=self.make_record(tmp,dict(type='not_before',due_at='2026-05-18T21:15:00Z'))
                record.update(id='legacy-'+status,status=status)
                write_record(root,record)
            with patch('codex_wake.measurements.utc_bounds',side_effect=TimeUnavailable('UTC absent')), \
                    patch('codex_wake.daemon.utc_now',side_effect=AssertionError('guest clock forbidden')):
                result=poll_once(root,runner=runner)
            self.assertEqual(result.time_held,2)
            self.assertEqual(result.dispatched,0)
            self.assertEqual(find_record(root,'legacy-pending').record['status'],'pending')
            self.assertEqual(find_record(root,'legacy-firing').record['status'],'firing')
            self.assertEqual(runner.pastes,[])
            self.assertEqual(poll_result_dict(result)['time_held'],2)

    def test_signal_expiry_uncertainty_holds_match_without_retiring_original_arm(self):
        from dataclasses import replace
        lower=datetime(2026,9,14,14,1,59,tzinfo=UTC).timestamp()+.25
        for already_reserved in (False,True):
            with self.subTest(already_reserved=already_reserved),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/'wake'
                registered=datetime(2026,9,14,14,0,tzinfo=UTC)
                runtime=SQLiteSignalModule(signal_journal_path(root),lease_clock=lambda:registered,
                    record_publisher=WakeRecordPublisher(root,ManagedReaderCapability(root,'reader',1,frozenset({1,2}),True)))
                registration=EventWake(runtime,adapters=[make_adapter()],clock=lambda:registered,
                    id_factory=lambda:'wake_uncertain_expiry').register(
                        replace(make_intent(),expires_at=datetime(2026,9,14,14,2,tzinfo=UTC)),idempotency_key='uncertain-expiry')
                self.assertIsInstance(registration,Registration)
                runtime.ingest([make_observation()],SourceCommit('memory','contract-test','checkpoint-1',1,
                    datetime(2026,9,14,14,1,tzinfo=UTC)))
                if already_reserved:
                    armed=runtime.load_armed_signal('wake_uncertain_expiry')
                    from codex_wake.signals import EvaluationLimits,Matched
                    self.assertIsInstance(runtime.evaluate('wake_uncertain_expiry',armed,datetime(2026,9,14,14,1,tzinfo=UTC),EvaluationLimits(100)),Matched)
                with patch('codex_wake.measurements.utc_bounds',return_value=(lower,lower+2)):
                    result=poll_once(root,dispatch=False,signal_runtime=runtime)
                self.assertEqual(result.fired,int(already_reserved))
                self.assertEqual(result.pending,int(not already_reserved))
                self.assertEqual(result.time_held,int(not already_reserved))
                self.assertIsNotNone(runtime.load_armed_signal('wake_uncertain_expiry'))
                self.assertEqual(find_record(root,'wake_uncertain_expiry').record['status'],'firing' if already_reserved else 'pending')

    def test_legacy_firing_rechecks_retry_anchor_before_dispatch(self):
        from tests.test_injector import FakeTmuxRunner
        instant=datetime(2026,5,18,21,14,59,tzinfo=UTC).timestamp()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'wake';runner=FakeTmuxRunner()
            record=self.make_record(tmp,dict(type='not_before',due_at='2026-05-18T21:15:00Z'))
            record.update(id='legacy-retained-firing',status='firing')
            write_record(root,record)
            with patch('codex_wake.measurements.utc_bounds',return_value=(instant,instant)):
                result=poll_once(root,runner=runner)
            self.assertEqual(result.time_held,1)
            self.assertEqual(result.dispatched,0)
            self.assertEqual(find_record(root,record['id']).record['status'],'firing')
            self.assertEqual(runner.pastes,[])
            self.assertTrue(poll_result_has_activity(result))

    def test_not_before_moves_ready_record_to_firing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            record = self.make_record(tmp, {"type": "not_before", "due_at": "2026-05-18T21:15:00Z"})
            write_record(root, record)

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.fired, 1)
            self.assertFalse((root / "pending" / f"{record['id']}.json").exists())
            firing = root / "firing" / f"{record['id']}.json"
            self.assertTrue(firing.exists())
            data = json.loads(firing.read_text())
            self.assertEqual(data["status"], "firing")
            self.assertEqual(data["events"][-1]["type"], "predicate_matched")

    def test_not_before_leaves_future_record_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            record = self.make_record(tmp, {"type": "not_before", "due_at": "2026-05-18T21:15:00Z"})
            write_record(root, record)

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 14, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.pending, 1)
            self.assertTrue((root / "pending" / f"{record['id']}.json").exists())

    def test_pending_record_respects_future_next_attempt_backoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            record = self.make_record(tmp, {"type": "not_before", "due_at": "2026-05-18T21:15:00Z"})
            record["next_attempt_at"] = "2026-05-18T21:30:00Z"
            write_record(root, record)

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 16, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.pending, 1)
            self.assertEqual(result.fired, 0)
            self.assertTrue((root / "pending" / f"{record['id']}.json").exists())

    def test_file_exists_relative_to_record_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            event_path = Path(tmp) / ".codex" / "events" / "pytest.done"
            event_path.parent.mkdir(parents=True)
            event_path.write_text("", encoding="utf-8")
            record = self.make_record(tmp, {"type": "file_exists", "path": ".codex/events/pytest.done"})
            record["id"] = "wake_file"
            write_record(root, record)

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.fired, 1)
            self.assertTrue((root / "firing" / "wake_file.json").exists())

    def test_file_changed_waits_for_mtime_or_size_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            watched = Path(tmp) / "watched.log"
            watched.write_text("before", encoding="utf-8")
            stat = watched.stat()
            record = self.make_record(
                tmp,
                {
                    "type": "file_changed",
                    "path": "watched.log",
                    "registered_exists": True,
                    "registered_mtime_ns": stat.st_mtime_ns,
                    "registered_size": stat.st_size,
                },
            )
            record["id"] = "wake_changed"
            write_record(root, record)

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.pending, 1)
            watched.write_text("after value", encoding="utf-8")

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 16, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.fired, 1)
            self.assertTrue((root / "firing" / "wake_changed.json").exists())

    def test_file_changed_fires_when_missing_file_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            watched = Path(tmp) / "created.log"
            record = self.make_record(
                tmp,
                {
                    "type": "file_changed",
                    "path": "created.log",
                    "registered_exists": False,
                    "registered_mtime_ns": None,
                    "registered_size": None,
                },
            )
            record["id"] = "wake_created"
            write_record(root, record)

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.pending, 1)
            watched.write_text("created", encoding="utf-8")

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 16, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.fired, 1)
            self.assertTrue((root / "firing" / "wake_created.json").exists())

    def test_process_done_waits_for_pid_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            proc = subprocess.Popen(["sleep", "0.2"])
            self.addCleanup(lambda: proc.poll() is None and proc.kill())
            record = self.make_record(tmp, {"type": "process_done", "pid": proc.pid})
            record["id"] = "wake_pid"
            write_record(root, record)

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.pending, 1)
            proc.wait(timeout=2)

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 16, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.fired, 1)
            self.assertTrue((root / "firing" / "wake_pid.json").exists())

    def test_process_done_waits_for_matching_process_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            record = self.make_record(
                tmp,
                {
                    "type": "process_done",
                    "pid": 123,
                    "registered_start_time_ticks": 456,
                    "registered_boot_id": "boot-abc",
                },
            )
            record["id"] = "wake_pid_identity"
            write_record(root, record)

            with patch("codex_wake.builtin_signals.process_exists", return_value=True):
                with patch("codex_wake.builtin_signals.boot_id_value", return_value="boot-abc"):
                    with patch(
                        "codex_wake.builtin_signals.process_identity",
                        return_value={"start_time_ticks": 456, "boot_id": "boot-abc"},
                    ):
                        result = poll_once(root, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.pending, 1)
            self.assertTrue((root / "pending" / "wake_pid_identity.json").exists())

    def test_process_done_fires_when_pid_identity_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            record = self.make_record(
                tmp,
                {
                    "type": "process_done",
                    "pid": 123,
                    "registered_start_time_ticks": 456,
                    "registered_boot_id": "boot-abc",
                },
            )
            record["id"] = "wake_pid_reused"
            write_record(root, record)

            with patch("codex_wake.builtin_signals.process_exists", return_value=True):
                with patch("codex_wake.builtin_signals.boot_id_value", return_value="boot-abc"):
                    with patch(
                        "codex_wake.builtin_signals.process_identity",
                        return_value={"start_time_ticks": 789, "boot_id": "boot-abc"},
                    ):
                        result = poll_once(root, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.fired, 1)
            data = json.loads((root / "firing" / "wake_pid_reused.json").read_text())
            self.assertIn("no longer matches", data["events"][-1]["message"])

    def test_process_done_fires_when_boot_id_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            record = self.make_record(
                tmp,
                {
                    "type": "process_done",
                    "pid": 123,
                    "registered_start_time_ticks": 456,
                    "registered_boot_id": "boot-abc",
                },
            )
            record["id"] = "wake_pid_boot"
            write_record(root, record)

            with patch("codex_wake.builtin_signals.process_exists", return_value=True):
                with patch("codex_wake.builtin_signals.boot_id_value", return_value="boot-def"):
                    result = poll_once(root, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.fired, 1)
            data = json.loads((root / "firing" / "wake_pid_boot.json").read_text())
            self.assertIn("previous boot", data["events"][-1]["message"])

    def test_process_done_rejects_invalid_registered_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            record = self.make_record(tmp, {"type": "process_done", "pid": 123, "registered_start_time_ticks": "bad"})
            record["id"] = "wake_bad_pid_identity"
            write_record(root, record)

            with patch("codex_wake.builtin_signals.process_exists", return_value=True):
                result = poll_once(root, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.failed, 1)
            data = json.loads((root / "failed" / "wake_bad_pid_identity.json").read_text())
            self.assertIn("registered_start_time_ticks", data["last_error"])

    def test_process_done_rejects_invalid_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            record = self.make_record(tmp, {"type": "process_done", "pid": "nope"})
            record["id"] = "wake_bad_pid"
            write_record(root, record)

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.failed, 1)
            data = json.loads((root / "failed" / "wake_bad_pid.json").read_text())
            self.assertIn("process_done predicate requires", data["last_error"])

    def test_invalid_predicate_moves_to_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wake"
            record = self.make_record(tmp, {"type": "command", "cmd": "pytest"})
            record["id"] = "wake_bad"
            write_record(root, record)

            result = poll_once(root, now=datetime(2026, 5, 18, 21, 15, tzinfo=UTC), dispatch=False)

            self.assertEqual(result.failed, 1)
            failed = root / "failed" / "wake_bad.json"
            self.assertTrue(failed.exists())
            data = json.loads(failed.read_text())
            self.assertEqual(data["status"], "failed")
            self.assertIn("unsupported predicate type", data["last_error"])

    def test_poll_result_format_and_activity(self) -> None:
        empty = PollResult()
        active = PollResult(checked=1, fired=1, dispatched=1, submitted=1)

        self.assertFalse(poll_result_has_activity(empty))
        self.assertTrue(poll_result_has_activity(active))
        self.assertEqual(
            format_poll_result(active),
            "checked=1 fired=1 failed=0 pending=0 dispatched=1 submitted=1 requeued=0",
        )


if __name__ == "__main__":
    unittest.main()
