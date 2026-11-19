"""Renewal through public APIs, real accounting files and owned native endpoint."""

import tempfile
import unittest
from unittest.mock import patch

from codex_wake.goal_supervision import enroll, show
from codex_wake.session_permissions import Principal
import test_goal_supervision as fixture_module

THREAD = fixture_module.THREAD
NOW = fixture_module.NOW


class GoalRenewalTests(unittest.TestCase):
    fixture = fixture_module.GoalSupervisionTests.fixture
    controller = fixture_module.GoalSupervisionTests.controller

    def test_operator_extension_retains_consumed_usage_and_does_not_resume(self):
        from codex_wake.goal_renewal import propose, apply

        with tempfile.TemporaryDirectory() as directory:
            root, policy, _, native, _ = self.fixture(directory)
            native["goal"]["status"] = "paused"
            native["active"] = []
            with (
                self.controller(root),
                patch("codex_wake.lifecycle_budget.trusted_upper", return_value=NOW),
            ):
                enroll(root, policy, THREAD, 40, 120)
                operator = Principal(THREAD, "operator")
                packet = propose(
                    root,
                    policy,
                    THREAD,
                    principal=operator,
                    operation_id="extension-1",
                    mode="extend",
                    token_limit=90,
                    deadline=NOW + 180,
                    expires_at=NOW + 60,
                )
                self.assertEqual(packet["proposal"]["old"]["used_tokens"], 40)
                self.assertEqual(packet["proposal"]["new"]["remaining_tokens"], 50)
                result = apply(
                    root,
                    policy,
                    THREAD,
                    packet["proposal_id"],
                    principal=operator,
                    expected_fingerprint=packet["fingerprint"],
                    explicit=True,
                )
                self.assertEqual(result["status"], "applied")
                campaign = show(root, policy, THREAD)
                self.assertEqual(
                    (campaign["token_limit"], campaign["used_tokens"]), (90, 40)
                )
                self.assertEqual(native["goal"]["status"], "paused")
                again = apply(
                    root,
                    policy,
                    THREAD,
                    packet["proposal_id"],
                    principal=operator,
                    expected_fingerprint=packet["fingerprint"],
                    explicit=True,
                )
                self.assertEqual(again, result)

    def test_reset_opens_new_window_and_retains_lifetime_and_stop_history(self):
        from codex_wake.goal_renewal import propose, apply

        with tempfile.TemporaryDirectory() as directory:
            root, policy, log, native, _ = self.fixture(directory)
            native["goal"]["status"] = "paused"
            native["active"] = []
            with (
                self.controller(root),
                patch("codex_wake.lifecycle_budget.trusted_upper", return_value=NOW),
            ):
                first = enroll(root, policy, THREAD, 40, 120)
                operator = Principal(THREAD, "operator")
                packet = propose(
                    root,
                    policy,
                    THREAD,
                    principal=operator,
                    operation_id="reset-1",
                    mode="reset",
                    token_limit=100,
                    remaining_seconds=180,
                    expires_at=NOW + 60,
                )
                result = apply(
                    root,
                    policy,
                    THREAD,
                    packet["proposal_id"],
                    principal=operator,
                    expected_fingerprint=packet["fingerprint"],
                    explicit=True,
                )
                campaign = show(root, policy, THREAD)
                self.assertEqual(campaign["used_tokens"], 0)
                self.assertEqual(campaign["lifetime_used_tokens"], 40)
                self.assertNotEqual(campaign["generation"], first["generation"])
                self.assertEqual(
                    campaign["budget_history"][0]["previous"]["used_tokens"], 40
                )
                self.assertTrue(
                    campaign["budget_history"][0]["previous"]["stop_latched"]
                )
                self.assertEqual(result["new"]["used_tokens"], 0)
                row = __import__("json").loads(log.read_text().splitlines()[-1])
                row["payload"]["response_id"] = "post-reset"
                with log.open("a") as stream:
                    stream.write(__import__("json").dumps(row) + "\n")
                from codex_wake.goal_supervision import poll

                self.assertEqual(poll(root)[0]["used_tokens"], 40)
                self.assertEqual(native["goal"]["status"], "paused")

    def test_model_cannot_self_approve_and_stale_or_expired_proposal_has_no_effect(
        self,
    ):
        from codex_wake.goal_renewal import propose, apply, RenewalError

        for scenario in ("model", "stale", "expired", "host-ceiling"):
            with (
                self.subTest(scenario=scenario),
                tempfile.TemporaryDirectory() as directory,
            ):
                root, policy, _, native, _ = self.fixture(directory)
                native["goal"]["status"] = "paused"
                native["active"] = []
                with (
                    self.controller(root),
                    patch(
                        "codex_wake.lifecycle_budget.trusted_upper", return_value=NOW
                    ),
                ):
                    enroll(root, policy, THREAD, 40, 120)
                    operator = Principal(THREAD, "operator")
                    if scenario == "host-ceiling":
                        with self.assertRaises(RenewalError):
                            propose(
                                root,
                                policy,
                                THREAD,
                                principal=operator,
                                operation_id="denied",
                                mode="extend",
                                token_limit=1001,
                                deadline=NOW + 180,
                                expires_at=NOW + 60,
                            )
                    else:
                        packet = propose(
                            root,
                            policy,
                            THREAD,
                            principal=operator,
                            operation_id="denied",
                            mode="extend",
                            token_limit=90,
                            deadline=NOW + 180,
                            expires_at=NOW + 60,
                        )
                        if scenario == "stale":
                            enroll(root, policy, THREAD, 39, 120)
                        when = NOW + 61 if scenario == "expired" else NOW
                        actor = Principal(THREAD) if scenario == "model" else operator
                        with patch(
                            "codex_wake.lifecycle_budget.trusted_upper",
                            return_value=when,
                        ):
                            with self.assertRaises(RenewalError):
                                apply(
                                    root,
                                    policy,
                                    THREAD,
                                    packet["proposal_id"],
                                    principal=actor,
                                    expected_fingerprint=packet["fingerprint"],
                                    explicit=True,
                                )
                    self.assertLessEqual(show(root, policy, THREAD)["token_limit"], 40)
                    self.assertEqual(native["goal"]["status"], "paused")

    def test_reset_and_extend_use_common_operator_response_with_no_model_approval(self):
        from codex_wake.goal_renewal_commands import execute
        from codex_wake.attention_queue import AttentionQueue
        from codex_wake.goal_renewal import RenewalError

        with tempfile.TemporaryDirectory() as directory:
            root, policy, _, native, _ = self.fixture(directory)
            native["goal"]["status"] = "paused"
            native["active"] = []
            context = dict(
                threadId=THREAD,
                sessionId=THREAD,
                callId="renewal-proposal",
                **{
                    "x-codex-turn-metadata": dict(
                        thread_id=THREAD, session_id=THREAD, turn_id="operator-request"
                    )
                },
            )
            model = Principal(THREAD)
            with (
                self.controller(root),
                patch("codex_wake.lifecycle_budget.trusted_upper", return_value=NOW),
            ):
                enroll(root, policy, THREAD, 40, 120)
                packet = execute(
                    "extend",
                    dict(
                        caller_thread_id=THREAD,
                        operation_id="native-proposal",
                        token_limit=90,
                        remaining_seconds=180,
                    ),
                    root,
                    policy,
                    principal=model,
                    native_context=context,
                    mcp=True,
                )
                with self.assertRaises(RenewalError):
                    execute(
                        "apply-renewal",
                        dict(
                            caller_thread_id=THREAD,
                            proposal_id=packet["proposal_id"],
                            fingerprint=packet["fingerprint"],
                            approve=True,
                        ),
                        root,
                        policy,
                        principal=model,
                        native_context=context,
                        mcp=True,
                    )
                row = packet["attention"]
                queue = AttentionQueue(root, now=lambda: NOW)
                queue.respond(
                    Principal("local-operator", "operator"),
                    row["request_id"],
                    "accept",
                    expected_revision=row["revision"],
                    expected_fingerprint=row["fingerprint"],
                )
                result = execute(
                    "apply-renewal",
                    dict(
                        caller_thread_id=THREAD,
                        proposal_id=packet["proposal_id"],
                        fingerprint=packet["fingerprint"],
                    ),
                    root,
                    policy,
                    principal=model,
                    native_context=context,
                    mcp=True,
                )
                self.assertEqual(result["status"], "applied")
                self.assertEqual(show(root, policy, THREAD)["used_tokens"], 40)
                self.assertEqual(
                    queue.inspect(model, row["request_id"])["status"], "consumed"
                )

    def test_approved_resume_waits_for_new_revision_first_poll(self):
        import json
        from codex_wake.goal_renewal import propose, apply

        with tempfile.TemporaryDirectory() as directory:
            root, policy, _, native, request = self.fixture(directory)
            native["goal"]["status"] = "paused"
            native["active"] = []
            clock=dict(reason='authenticated_utc',utc=dict(status='network',lower=NOW,upper=NOW),
                valid_for_ns=300000000000,counter=dict(epoch='c357309d-c209-4467-b757-e1488e6b1aaa',
                    counter=1000,frequency=1000,rate_ppm=0))
            controller=dict(fresh=True,generation='controller',interval=1)
            def native_call(endpoint,executable,method,params,timeout):
                if method=='thread/goal/set' and params.get('status')=='active':
                    native['calls'].append((method,params));native['goal']['status']='active';return {}
                return request(endpoint,executable,method,params,timeout)
            with (
                patch('codex_wake.goal_supervision._heartbeat',return_value=controller),
                patch('codex_wake.measurements.snapshot',return_value=clock),
                patch('codex_wake.goal_supervision.native_request',side_effect=native_call),
                patch("codex_wake.lifecycle_budget.trusted_upper", return_value=NOW),
            ):
                enroll(root, policy, THREAD, 40, 120)
                operator = Principal(THREAD, "operator")
                packet = propose(
                    root,
                    policy,
                    THREAD,
                    principal=operator,
                    operation_id="resume-1",
                    mode="extend",
                    token_limit=90,
                    remaining_seconds=180,
                    expires_at=NOW + 60,
                    resume=True,
                )
                result = apply(
                    root,
                    policy,
                    THREAD,
                    packet["proposal_id"],
                    principal=operator,
                    expected_fingerprint=packet["fingerprint"],
                    explicit=True,
                )
                self.assertEqual(result["resume_state"], "awaiting_first_poll")
                self.assertFalse(result["resumed"])
                self.assertEqual(native["goal"]["status"], "paused")
                retry = apply(
                    root,
                    policy,
                    THREAD,
                    packet["proposal_id"],
                    principal=operator,
                    expected_fingerprint=packet["fingerprint"],
                )
                self.assertEqual(retry["resume_state"], "awaiting_first_poll")
                receipt_path=next(path for path in (root/'goal-supervision').glob('*.json')
                    if path.name!='controller.json')
                retained=json.loads(receipt_path.read_text())
                original_deadline=retained['deadline']
                acknowledgement=dict(enrollment_revision=retained['enrollment_revision'],
                    receipt_generation=retained['generation'],controller_generation=controller['generation'],
                    observed_boottime=10)
                retained['poll_ack']=acknowledgement
                receipt_path.write_text(json.dumps(retained))
                legacy=apply(root,policy,THREAD,packet['proposal_id'],principal=operator,
                    expected_fingerprint=packet['fingerprint'])
                self.assertEqual(legacy['resume_state'],'awaiting_first_poll')
                self.assertFalse(any(method=='thread/goal/set' for method,_ in native['calls']))
                acknowledgement.update(observed_boottime=None,clock_observation=clock)
                receipt_path.write_text(json.dumps(retained))
                fresh=apply(root,policy,THREAD,packet['proposal_id'],principal=operator,
                    expected_fingerprint=packet['fingerprint'])
                self.assertTrue(fresh['resumed'])
                again=apply(root,policy,THREAD,packet['proposal_id'],principal=operator,
                    expected_fingerprint=packet['fingerprint'])
                self.assertTrue(again['resumed'])
                self.assertEqual(sum(method=='thread/goal/set' for method,_ in native['calls']),1)
                after=json.loads(receipt_path.read_text())
                self.assertEqual(after['poll_ack'],acknowledgement)
                self.assertEqual(after['deadline'],original_deadline)


    def test_existing_allowance_resume_requires_structured_first_poll_without_refreshing_it(self):
        import json
        from codex_wake.goal_renewal import resume_existing
        clock=dict(reason='authenticated_utc',utc=dict(status='network',lower=NOW,upper=NOW),
            valid_for_ns=300000000000,counter=dict(epoch='c357309d-c209-4467-b757-e1488e6b1aaa',
                counter=1000,frequency=1000,rate_ppm=0))
        controller=dict(fresh=True,generation='controller',interval=1)
        with tempfile.TemporaryDirectory() as directory:
            root,policy,_,native,request=self.fixture(directory)
            native['goal']['status']='paused';native['active']=[]
            def native_call(endpoint,executable,method,params,timeout):
                if method=='thread/goal/set' and params.get('status')=='active':
                    native['calls'].append((method,params));native['goal']['status']='active';return {}
                return request(endpoint,executable,method,params,timeout)
            with patch('codex_wake.goal_supervision._heartbeat',return_value=controller),patch(
                    'codex_wake.lifecycle_budget.trusted_upper',return_value=NOW),patch(
                    'codex_wake.measurements.snapshot',return_value=clock),patch(
                    'codex_wake.goal_supervision.native_request',side_effect=native_call):
                first=enroll(root,policy,THREAD,100,120)
                path=next(path for path in (root/'goal-supervision').glob('*.json') if path.name!='controller.json')
                receipt=json.loads(path.read_text())
                acknowledgement=dict(enrollment_revision=receipt['enrollment_revision'],
                    receipt_generation=receipt['generation'],controller_generation=controller['generation'],
                    observed_boottime=10)
                receipt['poll_ack']=acknowledgement
                path.write_text(json.dumps(receipt))
                principal=Principal(THREAD,'operator')
                held=resume_existing(root,policy,THREAD,principal=principal,operation_id='existing-resume')
                self.assertEqual(held['resume_state'],'awaiting_first_poll')
                self.assertFalse(any(method=='thread/goal/set' for method,_ in native['calls']))
                acknowledgement.update(observed_boottime=None,clock_observation=clock)
                path.write_text(json.dumps(receipt))
                accepted=resume_existing(root,policy,THREAD,principal=principal,operation_id='existing-resume')
                self.assertTrue(accepted['resumed'])
                after=json.loads(path.read_text())
                self.assertEqual(after['poll_ack'],acknowledgement)
                self.assertEqual(after['deadline'],first['deadline'])
                self.assertEqual(sum(method=='thread/goal/set' for method,_ in native['calls']),1)

    def test_interrupted_state_publication_reconciles_same_operation_without_new_authority(
        self,
    ):
        import json
        import os
        from pathlib import Path
        from codex_wake.goal_renewal import propose, apply

        with tempfile.TemporaryDirectory() as directory:
            root, policy, _, native, _ = self.fixture(directory)
            native["goal"]["status"] = "paused"
            native["active"] = []
            with (
                self.controller(root),
                patch("codex_wake.lifecycle_budget.trusted_upper", return_value=NOW),
            ):
                enroll(root, policy, THREAD, 40, 120)
                operator = Principal(THREAD, "operator")
                packet = propose(
                    root,
                    policy,
                    THREAD,
                    principal=operator,
                    operation_id="interrupted",
                    mode="extend",
                    token_limit=90,
                    remaining_seconds=180,
                    expires_at=NOW + 60,
                )
                replace = os.replace
                broken = []

                def lose_publication(source, target):
                    body = json.loads(Path(source).read_text())
                    if (
                        body.get("budget_revision") == 2
                        and body.get("thread_id") == THREAD
                        and not broken
                    ):
                        broken.append(True)
                        raise OSError("owned filesystem publication failed")
                    return replace(source, target)

                with patch("os.replace", side_effect=lose_publication):
                    with self.assertRaises(OSError):
                        apply(
                            root,
                            policy,
                            THREAD,
                            packet["proposal_id"],
                            principal=operator,
                            expected_fingerprint=packet["fingerprint"],
                            explicit=True,
                        )
                result = apply(
                    root,
                    policy,
                    THREAD,
                    packet["proposal_id"],
                    principal=operator,
                    expected_fingerprint=packet["fingerprint"],
                )
                self.assertEqual(result["status"], "applied")
                self.assertEqual(show(root, policy, THREAD)["token_limit"], 90)
                self.assertEqual(show(root, policy, THREAD)["used_tokens"], 40)

    def test_shared_reset_requires_explicit_scope_and_qualifies_every_member(self):
        import json
        from codex_wake.goal_renewal import propose, apply, RenewalError

        peer = "00000000-0000-7000-8000-000000000346"
        with tempfile.TemporaryDirectory() as directory:
            root, policy, log, native, _ = self.fixture(directory)
            template = json.loads(policy.read_text())["callers"][THREAD]
            template.pop("allocation_id")
            policy.write_text(
                json.dumps(
                    dict(
                        version=2,
                        native_caller_binding=True,
                        allocations={},
                        self_enrollment=template,
                    )
                )
            )
            rows = json.loads(
                json.dumps(
                    [json.loads(line) for line in log.read_text().splitlines()]
                ).replace(THREAD, peer)
            )
            (log.parent / "peer.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows)
            )
            native["siblings"] = {
                peer: dict(
                    goal=dict(threadId=peer, createdAt=NOW, status="paused"),
                    active=[],
                    calls=[],
                )
            }
            native["goal"]["status"] = "paused"
            native["active"] = []
            context = lambda thread: dict(
                threadId=thread,
                sessionId=thread,
                callId="shared-" + thread,
                **{
                    "x-codex-turn-metadata": dict(
                        thread_id=thread, session_id=thread, turn_id="operator-request"
                    )
                },
            )
            with (
                self.controller(root),
                patch("codex_wake.lifecycle_budget.trusted_upper", return_value=NOW),
            ):
                first = enroll(
                    root, policy, THREAD, 100, 120, native_context=context(THREAD)
                )
                enroll(
                    root,
                    policy,
                    peer,
                    100,
                    120,
                    allocation_id=first["allocation_id"],
                    native_context=context(peer),
                )
                operator = Principal(THREAD, "operator")
                with self.assertRaises(RenewalError):
                    propose(
                        root,
                        policy,
                        THREAD,
                        principal=operator,
                        operation_id="shared-denied",
                        mode="reset",
                        token_limit=100,
                        remaining_seconds=180,
                        expires_at=NOW + 60,
                    )
                native["siblings"][peer]["active"] = ["unrelated-peer-turn"]
                with self.assertRaises(RenewalError):
                    propose(
                        root,
                        policy,
                        THREAD,
                        principal=operator,
                        operation_id="busy-peer-reset",
                        mode="reset",
                        token_limit=100,
                        remaining_seconds=180,
                        expires_at=NOW + 60,
                        shared=True,
                    )
                self.assertEqual(
                    native["siblings"][peer]["active"], ["unrelated-peer-turn"]
                )
                native["siblings"][peer]["active"] = []
                packet = propose(
                    root,
                    policy,
                    THREAD,
                    principal=operator,
                    operation_id="shared-reset",
                    mode="reset",
                    token_limit=100,
                    remaining_seconds=180,
                    expires_at=NOW + 60,
                    shared=True,
                )
                self.assertEqual(packet["proposal"]["old"]["used_tokens"], 80)
                result = apply(
                    root,
                    policy,
                    THREAD,
                    packet["proposal_id"],
                    principal=operator,
                    expected_fingerprint=packet["fingerprint"],
                    explicit=True,
                )
                self.assertEqual(result["members"], sorted([THREAD, peer]))
                self.assertEqual(result["new"]["used_tokens"], 0)
                self.assertEqual(show(root, policy, peer)["used_tokens"], 0)
                self.assertEqual(show(root, policy, peer)["lifetime_used_tokens"], 80)

    def test_mandatory_policy_denial_unknown_accounting_and_dead_watcher_cannot_be_bypassed(
        self,
    ):
        import json
        from codex_wake.goal_renewal import propose, apply, RenewalError
        from codex_wake.session_permissions import PermissionStore, PermissionDenied

        for scenario in ("deny", "accounting", "watcher"):
            with (
                self.subTest(scenario=scenario),
                tempfile.TemporaryDirectory() as directory,
            ):
                root, policy, log, native, _ = self.fixture(directory)
                native["goal"]["status"] = "paused"
                native["active"] = []
                with (
                    self.controller(root) as watcher,
                    patch(
                        "codex_wake.lifecycle_budget.trusted_upper", return_value=NOW
                    ),
                ):
                    if scenario == "deny":
                        PermissionStore(root, now=lambda: NOW).configure(
                            dict(version=1, mandatory=["enforcement.increase"]),
                            Principal("operator", "operator"),
                            expected_revision=0,
                        )
                    enroll(
                        root,
                        policy,
                        THREAD,
                        40,
                        120,
                        permission_principal=Principal(THREAD, "operator"),
                    )
                    operator = Principal(THREAD, "operator")
                    packet = propose(
                        root,
                        policy,
                        THREAD,
                        principal=operator,
                        operation_id="held-" + scenario,
                        mode="extend",
                        token_limit=90,
                        remaining_seconds=180,
                        expires_at=NOW + 60,
                    )
                    if scenario == "accounting":
                        row = json.loads(log.read_text().splitlines()[-1])
                        row["payload"]["usage"]["total_tokens"] = 999
                        with log.open("a") as stream:
                            stream.write(json.dumps(row) + "\n")
                    if scenario == "watcher":
                        watcher.kill()
                        watcher.wait(timeout=3)
                    with self.assertRaises((RenewalError, PermissionDenied)):
                        apply(
                            root,
                            policy,
                            THREAD,
                            packet["proposal_id"],
                            principal=operator,
                            expected_fingerprint=packet["fingerprint"],
                            explicit=True,
                        )
                    self.assertEqual(
                        show(root, policy, THREAD, permission_principal=operator)[
                            "token_limit"
                        ],
                        40,
                    )

    def test_cli_adapter_uses_authenticated_operator_capability_and_exact_deadline(
        self,
    ):
        import argparse
        import contextlib
        import io
        import json
        from pathlib import Path
        from codex_wake.a2a_bus import BusStore
        from codex_wake.goal_renewal_commands import register_parser, command

        with tempfile.TemporaryDirectory() as directory:
            root, policy, _, native, _ = self.fixture(directory)
            native["goal"]["status"] = "paused"
            native["active"] = []
            bus, capability = BusStore.configure(Path(directory) / "bus")
            parser = argparse.ArgumentParser()
            register_parser(
                parser.add_subparsers(dest="goal_limits_command", required=True)
            )
            words = [
                "extend",
                "--policy",
                str(policy),
                "--caller-thread-id",
                THREAD,
                "--bus-root",
                str(bus.root),
                "--operator-capability",
                str(capability),
                "--operation-id",
                "cli-renewal",
                "--token-limit",
                "90",
                "--deadline",
                str(NOW + 180),
                "--apply",
                "--json",
            ]
            with (
                self.controller(root),
                patch("codex_wake.lifecycle_budget.trusted_upper", return_value=NOW),
            ):
                enroll(root, policy, THREAD, 40, 120)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = command(parser.parse_args(words), root)
                self.assertEqual(code, 0, output.getvalue())
                result = json.loads(output.getvalue())
                self.assertEqual(result["new"]["deadline"], NOW + 180)
                self.assertEqual(result["new"]["remaining_tokens"], 50)
                self.assertFalse(result["resumed"])

    def test_native_mcp_operator_reply_can_propose_and_apply_after_campaign_stops(self):
        from pathlib import Path
        from codex_wake.mcp_server import CommandRunner
        from codex_wake.goal_supervision import poll
        from codex_wake.attention_queue import AttentionQueue

        with tempfile.TemporaryDirectory() as directory:
            root, policy, _, native, _ = self.fixture(directory)
            with (
                self.controller(root),
                patch("codex_wake.lifecycle_budget.trusted_upper", return_value=NOW),
            ):
                enroll(root, policy, THREAD, 40, 120)
                stopped = poll(root)[0]
                self.assertTrue(stopped["stop_proof"])
                self.assertEqual(stopped["stop_turns"], ["work"])
                native["active"] = ["operator-request"]
                context = dict(
                    threadId=THREAD,
                    sessionId=THREAD,
                    callId="real-operator-mcp",
                    **{
                        "x-codex-turn-metadata": dict(
                            thread_id=THREAD,
                            session_id=THREAD,
                            turn_id="operator-request",
                        )
                    },
                )
                runner = CommandRunner(wake_root=Path(root), goal_limits_policy=policy)
                proposal, failed = runner.call(
                    "wake_goal_limits_extend",
                    dict(
                        caller_thread_id=THREAD,
                        operation_id="active-operator-reply",
                        token_limit=90,
                        remaining_seconds=180,
                        expires_at=NOW + 60,
                    ),
                    native_context=context,
                )
                self.assertFalse(failed, proposal)
                row = proposal["attention"]
                AttentionQueue(root, now=lambda: NOW).respond(
                    Principal("operator", "operator"),
                    row["request_id"],
                    "accept",
                    expected_revision=row["revision"],
                    expected_fingerprint=row["fingerprint"],
                )
                result, failed = runner.call(
                    "wake_goal_limits_apply_renewal",
                    dict(
                        caller_thread_id=THREAD,
                        proposal_id=proposal["proposal_id"],
                        fingerprint=proposal["fingerprint"],
                    ),
                    native_context=context,
                )
                self.assertFalse(failed, result)
                self.assertEqual(result["status"], "applied")
                self.assertEqual(native["active"], ["operator-request"])
                self.assertEqual(native["goal"]["status"], "paused")
                self.assertEqual(show(root, policy, THREAD)["used_tokens"], 40)

    def test_active_turn_exception_rejects_campaign_mismatch_missing_or_argument_claims(
        self,
    ):
        from codex_wake.mcp_server import CommandRunner
        from codex_wake.goal_supervision import poll
        from codex_wake.goal_renewal import propose, RenewalError

        for scenario in (
            "captured-campaign",
            "metadata-mismatch",
            "missing-metadata",
            "argument-claim",
            "cli-no-attestation",
            "replacement-native-goal",
        ):
            with (
                self.subTest(scenario=scenario),
                tempfile.TemporaryDirectory() as directory,
            ):
                root, policy, _, native, _ = self.fixture(directory)
                with (
                    self.controller(root),
                    patch(
                        "codex_wake.lifecycle_budget.trusted_upper", return_value=NOW
                    ),
                ):
                    enroll(root, policy, THREAD, 40, 120)
                    self.assertTrue(poll(root)[0]["stop_proof"])
                    active = (
                        "work"
                        if scenario == "captured-campaign"
                        else "operator-request"
                    )
                    native["active"] = [active]
                    if scenario == "replacement-native-goal":
                        native["goal"]["createdAt"] = NOW + 1
                    attested = (
                        "another-turn" if scenario == "metadata-mismatch" else active
                    )
                    context = dict(
                        threadId=THREAD,
                        sessionId=THREAD,
                        callId="untrusted-turn-case",
                        **{
                            "x-codex-turn-metadata": dict(
                                thread_id=THREAD, session_id=THREAD, turn_id=attested
                            )
                        },
                    )
                    arguments = dict(
                        caller_thread_id=THREAD,
                        operation_id="refuse-" + scenario,
                        token_limit=90,
                        remaining_seconds=180,
                        expires_at=NOW + 60,
                    )
                    if scenario == "argument-claim":
                        arguments["operator_turn_id"] = "operator-request"
                    if scenario == "cli-no-attestation":
                        with self.assertRaises(RenewalError):
                            propose(
                                root,
                                policy,
                                THREAD,
                                principal=Principal(THREAD, "operator"),
                                operation_id="cli-reply",
                                mode="extend",
                                token_limit=90,
                                remaining_seconds=180,
                                expires_at=NOW + 60,
                            )
                    else:
                        runner = CommandRunner(
                            wake_root=root, goal_limits_policy=policy
                        )
                        result, failed = runner.call(
                            "wake_goal_limits_extend",
                            arguments,
                            native_context=None
                            if scenario == "missing-metadata"
                            else context,
                        )
                        self.assertTrue(failed, result)
                    self.assertEqual(show(root, policy, THREAD)["token_limit"], 40)
                    self.assertEqual(native["active"], [active])
                    self.assertEqual(native["goal"]["status"], "paused")

    def test_original_exhaustion_can_renew_after_fresh_watcher_replacement(self):
        import time
        from codex_wake.goal_supervision import poll
        from codex_wake.goal_renewal import propose, apply

        with tempfile.TemporaryDirectory() as directory:
            root, policy, _, native, _ = self.fixture(directory)
            with patch("codex_wake.lifecycle_budget.trusted_upper", return_value=NOW):
                with self.controller(root) as old:
                    enroll(root, policy, THREAD, 40, 120)
                    stopped = poll(root)[0]
                    first = stopped["first_stop"]
                    old.terminate()
                    old.wait(timeout=8)
                    self.assertEqual(
                        show(root, policy, THREAD)["reason"], "controller_stopped"
                    )
                with self.controller(root):
                    deadline = time.monotonic() + 3
                    while not show(root, policy, THREAD)["controller"]["fresh"]:
                        if time.monotonic() > deadline:
                            self.fail("replacement watcher did not become fresh")
                        time.sleep(0.01)
                    principal = Principal(THREAD, "operator")
                    proposal = propose(
                        root,
                        policy,
                        THREAD,
                        principal=principal,
                        operation_id="restart-extension",
                        mode="extend",
                        token_limit=90,
                        remaining_seconds=180,
                        expires_at=NOW + 60,
                    )
                    result = apply(
                        root,
                        policy,
                        THREAD,
                        proposal["proposal_id"],
                        principal=principal,
                        expected_fingerprint=proposal["fingerprint"],
                        explicit=True,
                    )
                    self.assertEqual(result["new"]["used_tokens"], 40)
                    self.assertEqual(
                        show(root, policy, THREAD)["budget_history"][-1]["previous"][
                            "first_stop"
                        ],
                        first,
                    )
                    self.assertEqual(native["goal"]["status"], "paused")
