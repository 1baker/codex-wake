# P233 T3 / issue 632: separate CLI-worker retirement

Date: 2026-11-14. Owner: worker-retirement. Frozen integration base:
`8fffdec2a3875331022e71cedaa8b062cb61d0b8`. This packet retires the task-owned
setup from [621](https://github.com/CochranResearchGroup/codex-wake/issues/621)
and [622](https://github.com/CochranResearchGroup/codex-wake/pull/622), preserving
source `ab1a061d6400e02b9d305be1ea835aa1ad7aa4aa` and its remote branch.
The native-provider specification [628](https://github.com/CochranResearchGroup/codex-wake/issues/628)
remains open; native-provider implementation/acceptance is not established here.

## Exact idle custody before mutation

`systemctl --user show codex-grok-worker.service` selected ActiveState,
SubState, MainPID and ControlGroup: inactive/dead, PID0, empty cgroup.
The unit was static, with no automatic login enablement. Its SHA256 was
`840ab90aceceaddd618260480f1c3b75c110d65000e6935a508f5e281bc3e0f7`.
The pinned native process PID705110/start21940516 was absent from `/proc`;
a fresh OS scan found zero Grok-named processes or exact `stdio-host` argv
matches. The old loopback endpoint refused a connection (errno111).

A read-only SQLite projection of lifecycle controller operations matched exact
profile `codex-native` or its pinned Grok namespace, rather than relying on the
partial empty discovery result. Exactly one operation matched:
`local-grok-create-dfd96b448d35741a11ee803c84a90259`, `grok.create`, terminal,
execution `not_started`, reason `native_auth_required`. Public
`wake_local_result` with mode silent/timeout0 independently confirmed the retained
original reply, cursor0, no truncation/gap. No outstanding matching effect existed.
The profile registry contained only this dedicated profile. No authentication or
credential-file read, model prompt, process signal, service start or restart ran.

## Reversible changes

Private preimages and manifest are retained in the operator state directory
`native-grok-workers/retirement-p233`, alongside copied original checkpoint,
cleanup, host-configuration and guidance-installation receipts. No secrets or raw
history were copied to Git. The transport secret file and native home are untouched.
The dedicated unit and profile activation registry were archived, then unlinked;
the controller lock inode and original operation journal remain. A metadata-only
`systemctl --user daemon-reload` reconciled unit absence.

Both installed skill entries and old references matched the prior installation
receipt: entry SHA256 `58f1bf1c06b1610b9ad6d2d949127e3bb759a12134f0c6890d4ef2bba6c27e5e`,
reference SHA256 `7e9c475b6a7006191c0d56d39c8dc1c18cd50bfe16f4711449757f0afd361e50`.
Only the exact CLI delegation sentence/row and dedicated reference were removed.
Both entries now route Grok-in-Codex requests to the same explicit pending-provider
reference added to repository skill source. Other installed entry text was preserved.

The actual files were restored once from private preimages; every original SHA256
matched. They were then retired again. This proves file rollback, not a service
restart or provider-authentication rollback. The exact guarded retirement script
and private manifest/results are retained outside Git. No native binary or source,
other session/service, browser Grok input hold, or current OpenAI default was changed.

## Validation and tracker custody

- Guarded private `retire.py`: PASS, exact hashes/profile/process/service assertions;
  file-only restore and re-retirement PASS.
- Post-retirement `systemctl --user show`: LoadState not-found, inactive/dead,
  MainPID0, empty cgroup.
- Fresh `/proc` census: zero Grok/stdio-host matching processes.
- Read-only exact-profile SQLite projection: still exactly one terminal not-started
  operation; public original result remains available unchanged.
- `wake_local_list(harness="grok")`: complete, sessions empty, holds empty after
  profile activation archival. This is not a statement about independent browser Grok.
- Installed route/reference absence and byte-for-byte new guide consistency across
  both installed skill roots and repository source: PASS.
- `git diff --check`: PASS. Documentation-only source change; no runtime code or
  synthetic fixtures changed. Hosted CI skipped under repository cost policy.
  Runtime evidence uses the working Linux user/systemd and installed Wakedev20,
  not the hosted runner; it establishes retirement only.
- Issue621 closed as not planned with a supersession comment linking628/632;
  draftPR622 closed without merge or branch deletion, with the same custody links.
  T3 remains open until primary reconciliation/integrated acceptance.

Memory disposition: forbidden; explicit task boundary prohibits memory writes.
