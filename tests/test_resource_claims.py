"""Declared cooperative custody prevents a competing mutation before its effect."""
from pathlib import Path
import json
import tempfile
import unittest

from codex_wake.resource_claims import Claimant, ResourceClaims, ResourceClaimError


class ResourceClaimTests(unittest.TestCase):
    def test_stable_counter_freshness_survives_utc_metadata_rollback(self):
        from unittest.mock import patch
        from codex_wake import measurements
        anchor = dict(reason='authenticated_counter_only', counter=dict(
            epoch='c357309d-c209-4467-b757-e1488e6b1aaa', counter=1000,
            frequency=1000, rate_ppm=0))
        current = dict(anchor, counter=dict(anchor['counter'], counter=2000))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root/'work'
            workspace.mkdir()
            owner = Claimant('agent_'+'1'*32, str(root),
                dict(pid=11, start_ticks=1, boot_id='boot'), 1000,
                clock_observation=anchor)
            with patch.object(measurements, 'snapshot', return_value=current), patch.object(measurements, 'utc_time', return_value=991):
                store = ResourceClaims(root/'wake')
                claim = store.claim('worktree', workspace, owner)
                with store.guard(claim['claim_id'], claim['generation'], owner):
                    pass
                self.assertEqual(claim['owner']['managed_agent_id'], owner.managed_agent_id)
                self.assertEqual(claim['history'][0]['at'], 991)
                legacy = Claimant(owner.managed_agent_id, owner.root, owner.process, 991)
                with self.assertRaises(ResourceClaimError):
                    store.claim('worktree', workspace, legacy)
                stale = dict(current, counter=dict(current['counter'], counter=40000))
                with patch.object(measurements, 'snapshot', return_value=stale), self.assertRaises(ResourceClaimError):
                    with store.guard(claim['claim_id'], claim['generation'], owner):
                        self.fail('stale custody reached mutation')

    def test_competing_agent_cannot_claim_owned_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = root / 'worktree'
            worktree.mkdir()
            store = ResourceClaims(root / 'wake', now=lambda: 100)
            first = Claimant('agent_' + '1' * 32, str(root), {'pid': 11, 'start_ticks': 1, 'boot_id': 'boot'}, 100)
            second = Claimant('agent_' + '2' * 32, str(root), {'pid': 22, 'start_ticks': 2, 'boot_id': 'boot'}, 100)
            claim = store.claim('worktree', worktree, first)
            with self.assertRaises(ResourceClaimError) as refused:
                store.claim('worktree', worktree, second)
            self.assertEqual(refused.exception.code, 'resource_conflict')
            self.assertEqual(store.inspect(claim['claim_id'])['owner']['managed_agent_id'], first.managed_agent_id)

    def test_guard_refuses_foreign_or_stale_owner_before_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / 'worktree'; workspace.mkdir()
            store = ResourceClaims(root / 'wake', now=lambda: 100)
            owner = Claimant('agent_' + '1' * 32, str(root), {'pid': 11, 'start_ticks': 1, 'boot_id': 'boot'}, 100)
            claim = store.claim('worktree', workspace, owner)
            marker = workspace / 'effect'
            for claimant, generation in [
                (Claimant('agent_' + '2' * 32, str(root), owner.process, 100), 1),
                (Claimant(owner.managed_agent_id, str(root), dict(owner.process, start_ticks=2), 100), 1),
                (Claimant(owner.managed_agent_id, str(root), owner.process, 60), 1),
                (owner, 0),
            ]:
                with self.subTest(claimant=claimant, generation=generation):
                    with self.assertRaises(ResourceClaimError):
                        with store.guard(claim['claim_id'], generation, claimant):
                            marker.write_text('must not happen')
                    self.assertFalse(marker.exists())
            with store.guard(claim['claim_id'], 1, owner):
                marker.write_text('admitted')
            self.assertEqual(marker.read_text(), 'admitted')

    def test_explicit_transfer_fences_prior_owner_and_release_retains_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_path, other_path = root / 'first', root / 'other'
            first_path.mkdir(); other_path.mkdir()
            store = ResourceClaims(root / 'wake', now=lambda: 100)
            owner = Claimant('agent_' + '1' * 32, str(root), {'pid': 11, 'start_ticks': 1, 'boot_id': 'boot'}, 100)
            successor = Claimant('agent_' + '2' * 32, str(root), {'pid': 22, 'start_ticks': 2, 'boot_id': 'boot'}, 100)
            claim = store.claim('worktree', first_path, owner)
            other = store.claim('install_prefix', other_path, owner)
            with self.assertRaises(ResourceClaimError):
                store.transfer(claim['claim_id'], 1, successor, operator=False, reason='handoff')
            transferred = store.transfer(claim['claim_id'], 1, successor, operator=True, reason='operator-approved handoff')
            self.assertEqual(transferred['generation'], 2)
            self.assertEqual(transferred['history'][-1]['reason'], 'operator-approved handoff')
            with self.assertRaises(ResourceClaimError):
                with store.guard(claim['claim_id'], 1, owner):
                    self.fail('prior token entered mutation')
            with store.guard(claim['claim_id'], 2, successor):
                (first_path / 'effect').write_text('successor')
            released = store.release(claim['claim_id'], 2, successor)
            self.assertEqual(released['status'], 'released')
            self.assertEqual(store.inspect(other['claim_id']), other)
            self.assertEqual(len(store.inspect(claim['claim_id'])['history']), 3)

    def test_missing_or_unknown_authority_never_creates_a_second_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / 'worktree'; workspace.mkdir()
            owner = Claimant('agent_' + '1' * 32, str(root), {'pid': 11, 'start_ticks': 1, 'boot_id': 'boot'}, 100)
            store = ResourceClaims(root / 'wake', now=lambda: 100)
            store.claim('worktree', workspace, owner)
            # Public state format is deliberately corrupted to model unsupported writer data.
            state_file = root / 'wake/resource-claims/claims.json'
            original = state_file.read_bytes()
            unknown = b'{ "version": 99, "claims": [] }\n'
            state_file.write_bytes(unknown)
            with self.assertRaises(ResourceClaimError):
                store.claim('build_prefix', workspace, owner)
            self.assertEqual(state_file.read_bytes(), unknown)
            future = json.loads(original)
            future['claims'][0]['new_authority_field'] = True
            future_bytes = json.dumps(future).encode()
            state_file.write_bytes(future_bytes)
            with self.assertRaises(ResourceClaimError):
                store.inspect()
            self.assertEqual(state_file.read_bytes(), future_bytes)
            state_file.write_bytes(original)
            state_file.unlink()
            with self.assertRaises(ResourceClaimError):
                ResourceClaims(root / 'wake', now=lambda: 100).claim('worktree', workspace, owner)

    def test_overlap_survives_restart_and_guard_serializes_transfer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent, child = root / 'parent', root / 'parent/child'
            child.mkdir(parents=True)
            owner = Claimant('agent_' + '1' * 32, str(root), {'pid': 11, 'start_ticks': 1, 'boot_id': 'boot'}, 100)
            second = Claimant('agent_' + '2' * 32, str(root), {'pid': 22, 'start_ticks': 2, 'boot_id': 'boot'}, 100)
            for number, (owned, attempted) in enumerate(((parent, child), (child, parent))):
                with self.subTest(owned=owned):
                    wake = root / ('wake' + str(number))
                    store = ResourceClaims(wake, now=lambda: 100)
                    claim = store.claim('worktree', owned, owner)
                    restored = ResourceClaims(wake, now=lambda: 100)
                    with self.assertRaises(ResourceClaimError) as conflict:
                        restored.claim('build_prefix', attempted, second)
                    self.assertEqual(conflict.exception.code, 'resource_conflict')
                    with store.guard(claim['claim_id'], 1, owner):
                        with self.assertRaises(ResourceClaimError) as busy:
                            restored.transfer(claim['claim_id'], 1, second, operator=True, reason='reviewed')
                        self.assertEqual(busy.exception.code, 'resource_busy')
                    later = ResourceClaims(wake, now=lambda: 200)
                    with self.assertRaises(ResourceClaimError):
                        with later.guard(claim['claim_id'], 1, owner):
                            self.fail('stale owner cannot mutate')
                    self.assertEqual(later.inspect(claim['claim_id'])['status'], 'active')
                    with self.assertRaises(ResourceClaimError):
                        later.claim('worktree', owned,
                            Claimant(second.managed_agent_id, second.root, second.process, 200))
                    later.release(claim['claim_id'], 1, operator=True, reason='owner disappeared; unknown effects retained')
                    self.assertEqual(later.inspect(claim['claim_id'])['status'], 'released')

    def test_symlink_alias_and_replaced_directory_do_not_qualify_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / 'workspace'; workspace.mkdir()
            alias = root / 'alias'; alias.symlink_to(workspace, target_is_directory=True)
            owner = Claimant('agent_' + '1' * 32, str(root), {'pid': 11, 'start_ticks': 1, 'boot_id': 'boot'}, 100)
            store = ResourceClaims(root / 'wake', now=lambda: 100)
            with self.assertRaises(ResourceClaimError):
                store.claim('worktree', alias, owner)
            claim = store.claim('worktree', workspace, owner)
            workspace.rename(root / 'old-workspace'); workspace.mkdir()
            with self.assertRaises(ResourceClaimError):
                with store.guard(claim['claim_id'], 1, owner):
                    self.fail('directory replacement cannot inherit custody')

    def test_unknown_claim_lookup_does_not_destroy_new_store_availability(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / 'workspace'; workspace.mkdir()
            owner = Claimant('agent_' + '1' * 32, str(root), {'pid': 11, 'start_ticks': 1, 'boot_id': 'boot'}, 100)
            store = ResourceClaims(root / 'wake', now=lambda: 100)
            with self.assertRaises(ResourceClaimError):
                store.inspect('claim_' + '0' * 32)
            self.assertEqual(store.claim('worktree', workspace, owner)['status'], 'active')

    def test_shared_wake_root_cannot_host_resource_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wake = root / 'shared'
            wake.mkdir(mode=0o777)
            wake.chmod(0o777)
            with self.assertRaises(ResourceClaimError):
                ResourceClaims(wake)
            self.assertFalse((wake / 'resource-claims').exists())

    def test_duplicate_authority_fields_hold_original_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / 'workspace'; workspace.mkdir()
            owner = Claimant('agent_' + '1' * 32, str(root), {'pid': 11, 'start_ticks': 1, 'boot_id': 'boot'}, 100)
            store = ResourceClaims(root / 'wake', now=lambda: 100)
            store.claim('worktree', workspace, owner)
            path = root / 'wake/resource-claims/claims.json'
            state = json.loads(path.read_text())
            malformed = ('{"version":1,"claims":' + json.dumps(state['claims']) + ',"claims":[]}').encode()
            path.write_bytes(malformed)
            with self.assertRaises(ResourceClaimError):
                store.claim('worktree', workspace, owner)
            self.assertEqual(path.read_bytes(), malformed)
