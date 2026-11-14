# Generated command reference

Generated from `codex_wake.command_contract`; do not edit by hand.

Scope: stores, accounts, configuration, builds, daemons, migration and history. Other Wake
commands are deferred from this contract migration; their existing interfaces remain.

Local human login and status use native stdio. Structured status is cache evidence,
not proof of current provider access. Native history MCP additionally requires
verified caller identity; local CLI and scoped remote caller admission differ.

Examples use placeholders ROOT, THREAD, TIME, FILE and exact target JSON.
Resolve fresh targets before execution; empty target objects are never valid pins.

## Tab capability boundaries

- `selected_profile_create`: **conditional**. Use --profile with an existing account selector/alias; requires the qualified selected-profile launch owner. Windows profile creation remains unsupported; no shell fallback or account substitution.
- `workspace_recovery`: **conditional**. Exact saved conversation identity is required. With --restore-layout, qualified single local interactive shell slots are preserved in separate tabs before coding views resume in their saved positions; busy, pinned or unknown slots hold.
- `exact_grok_tui_health`: **unsupported**. Grok ACP activity does not prove arbitrary foreground TUI responsiveness.
- `cross_backend`: **conditional**. Exact saved Codex conversation reattachment requires a qualified destination bridge/profile; unsupported continuity preserves the source.
- `result`: **supported**. tabs result --request-id reads local UID-owned common journal; remote callers use operations.result.

## accounts init

Initialize a new private account registry.

Creates only an empty isolated registry; preserves existing state.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_account_init`).

```sh
codex-wake --wake-root ROOT accounts init
```

### CLI help

```text
usage: codex-wake accounts init [-h] [--json]

Initialize a new private account registry.

Creates only an empty isolated registry; preserves existing state.

options:
  -h, --help  show this help message and exit
  --json      Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT accounts init
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## accounts create

Create a private account home without credentials.

Creates account configuration and a private home; does not sign in.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_account_create`).

```sh
codex-wake --wake-root ROOT accounts create work --alias office
```

### CLI help

```text
usage: codex-wake accounts create [-h] [--alias ALIAS] [--mode {independent}]
                                  [--source SOURCE] [--json]
                                  selector

Create a private account home without credentials.

Creates account configuration and a private home; does not sign in.

positional arguments:
  selector              Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --alias ALIAS         Optional alternate name for the newly created account.
  --mode {independent}  Create an independent private configuration snapshot;
                        legacy creation remains the default.
  --source SOURCE       Registered source store selector, including stock.
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT accounts create work --alias office
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selector` | yes | Account name or configured alias. |
| `alias` | no | Optional alternate name for the newly created account. |
| `mode` | no | Create an independent private configuration snapshot; legacy creation remains the default. |
| `source` | no | Registered source store selector, including stock. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## accounts readiness

Inspect the selected profile readiness and specific remedies.

Read-only; native limits, refresh and backend acceptance remain separately qualified. Remote callers cannot supply launcher or manifest paths.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_account_readiness`).

```sh
codex-wake --wake-root ROOT accounts readiness work --json
```

### CLI help

```text
usage: codex-wake accounts readiness [-h] [--expected-target EXPECTED_TARGET]
                                     [--manifest MANIFEST]
                                     [--launcher LAUNCHER] [--json]
                                     selector

Inspect the selected profile readiness and specific remedies.

Read-only; native limits, refresh and backend acceptance remain separately qualified. Remote callers cannot supply launcher or manifest paths.

positional arguments:
  selector              Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.
  --manifest MANIFEST
  --launcher LAUNCHER
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT accounts readiness work --json
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selector` | yes | Account name or configured alias. |
| `expected_target` | no | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |

## stores register

Register the stable shared stock store in Wake metadata.

Preserves stock configuration and login. Remote admin grant must pin the registry revision and selected home.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_store_register`).

```sh
codex-wake --wake-root ROOT stores register stock --home /absolute/stock/home
```

### CLI help

```text
usage: codex-wake stores register [-h] --home HOME [--json] selector

Register the stable shared stock store in Wake metadata.

Preserves stock configuration and login. Remote admin grant must pin the registry revision and selected home.

positional arguments:
  selector     Account name or configured alias.

options:
  -h, --help   show this help message and exit
  --home HOME  Absolute existing stock home; registration changes only Wake
               metadata.
  --json       Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT stores register stock --home /absolute/stock/home
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selector` | yes | Account name or configured alias. |
| `home` | yes | Absolute existing stock home; registration changes only Wake metadata. |

## stores resolve

Resolve a registered stock or profile store.

Read-only observation; no model turn.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_store_resolve`).

```sh
codex-wake --wake-root ROOT stores resolve stock
```

### CLI help

```text
usage: codex-wake stores resolve [-h] [--json] selector

Resolve a registered stock or profile store.

Read-only observation; no model turn.

positional arguments:
  selector    Account name or configured alias.

options:
  -h, --help  show this help message and exit
  --json      Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT stores resolve stock
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selector` | yes | Account name or configured alias. |

## stores list

List permitted registered stores with stable identities.

Read-only observation; no model turn.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_stores`).

```sh
codex-wake --wake-root ROOT stores list
```

### CLI help

```text
usage: codex-wake stores list [-h] [--json]

List permitted registered stores with stable identities.

Read-only observation; no model turn.

options:
  -h, --help  show this help message and exit
  --json      Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT stores list
```

## configuration sync preview

Preview selected directional configuration changes and conflicts.

Saves a frozen preview outside stock; sensitive values are redacted. Grant must cover every selected store.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_configuration_sync_preview`).

```sh
codex-wake --wake-root ROOT configuration sync preview --source stock --destination work --category mcp --operation-id sync-1
```

### CLI help

```text
usage: codex-wake configuration sync preview [-h] --source SOURCE
                                             --destination DESTINATIONS
                                             --category
                                             {settings,mcp,hooks,skills,rules}
                                             --operation-id OPERATION_ID
                                             [--propagate-deletions]
                                             [--reload] [--json]

Preview selected directional configuration changes and conflicts.

Saves a frozen preview outside stock; sensitive values are redacted. Grant must cover every selected store.

options:
  -h, --help            show this help message and exit
  --source SOURCE       Registered source store selector, including stock.
  --destination DESTINATIONS
                        Explicit destination store selectors.
  --category {settings,mcp,hooks,skills,rules}
                        Selected configuration categories; authentication is
                        excluded.
  --operation-id OPERATION_ID
                        Stable sync intent identifier; reconcile unknown
                        outcomes before resubmitting.
  --propagate-deletions
                        Explicitly propagate matching source deletions;
                        default preserves destination copies.
  --reload              Request selected-profile reload if supported;
                        otherwise each destination reports next-launch remedy.
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT configuration sync preview --source stock --destination work --category mcp --operation-id sync-1
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `source` | yes | Registered source store selector, including stock. |
| `destinations` | yes | Explicit destination store selectors. |
| `categories` | yes | Selected configuration categories; authentication is excluded. |
| `operation_id` | yes | Stable sync intent identifier; reconcile unknown outcomes before resubmitting. |
| `propagate_deletions` | no | Explicitly propagate matching source deletions; default preserves destination copies. |
| `reload` | no | Request selected-profile reload if supported; otherwise each destination reports next-launch remedy. |

## configuration sync apply

Apply safe selected changes and preserve divergent destination entries.

Repeat-safe per-destination results. Default takes effect at next launch; reload reports an explicit unsupported remedy when no selected-profile owner is available.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_configuration_sync_apply`).

```sh
codex-wake --wake-root ROOT configuration sync apply --source stock --destination work --category mcp --operation-id sync-1 --expected-snapshot SNAPSHOT
```

### CLI help

```text
usage: codex-wake configuration sync apply [-h] --source SOURCE --destination
                                           DESTINATIONS --category
                                           {settings,mcp,hooks,skills,rules}
                                           --operation-id OPERATION_ID
                                           --expected-snapshot
                                           EXPECTED_SNAPSHOT
                                           [--propagate-deletions] [--reload]
                                           [--json]

Apply safe selected changes and preserve divergent destination entries.

Repeat-safe per-destination results. Default takes effect at next launch; reload reports an explicit unsupported remedy when no selected-profile owner is available.

options:
  -h, --help            show this help message and exit
  --source SOURCE       Registered source store selector, including stock.
  --destination DESTINATIONS
                        Explicit destination store selectors.
  --category {settings,mcp,hooks,skills,rules}
                        Selected configuration categories; authentication is
                        excluded.
  --operation-id OPERATION_ID
                        Stable sync intent identifier; reconcile unknown
                        outcomes before resubmitting.
  --expected-snapshot EXPECTED_SNAPSHOT
                        Exact snapshot digest returned by sync preview.
  --propagate-deletions
                        Explicitly propagate matching source deletions;
                        default preserves destination copies.
  --reload              Request selected-profile reload if supported;
                        otherwise each destination reports next-launch remedy.
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT configuration sync apply --source stock --destination work --category mcp --operation-id sync-1 --expected-snapshot SNAPSHOT
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `source` | yes | Registered source store selector, including stock. |
| `destinations` | yes | Explicit destination store selectors. |
| `categories` | yes | Selected configuration categories; authentication is excluded. |
| `operation_id` | yes | Stable sync intent identifier; reconcile unknown outcomes before resubmitting. |
| `expected_snapshot` | yes | Exact snapshot digest returned by sync preview. |
| `propagate_deletions` | no | Explicitly propagate matching source deletions; default preserves destination copies. |
| `reload` | no | Request selected-profile reload if supported; otherwise each destination reports next-launch remedy. |

## accounts list

List registered account names and targets.

Read-only observation; no model turn.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_accounts`).

```sh
codex-wake --wake-root ROOT accounts list
```

### CLI help

```text
usage: codex-wake accounts list [-h] [--json]

List registered account names and targets.

Read-only observation; no model turn.

options:
  -h, --help  show this help message and exit
  --json      Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT accounts list
```

## accounts resolve

Resolve one account name to its exact current target.

Read-only observation; no model turn.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_account_resolve`).

```sh
codex-wake --wake-root ROOT accounts resolve work
```

### CLI help

```text
usage: codex-wake accounts resolve [-h] [--json]
                                   [--expected-target EXPECTED_TARGET]
                                   selector

Resolve one account name to its exact current target.

Read-only observation; no model turn.

positional arguments:
  selector              Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --json                Emit structured results for this command.
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.

Examples:
  codex-wake --wake-root ROOT accounts resolve work
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selector` | yes | Account name or configured alias. |
| `expected_target` | no | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |

## accounts login

Sign into a named private account through native login.

Local human CLI only. Writes native credentials; active account clients or daemons hold login.

Transport: Local human CLI only.

```sh
codex-wake --wake-root ROOT accounts login work --device-auth
```

### CLI help

```text
usage: codex-wake accounts login [-h] [--channel {stock,modded}]
                                 [--device-auth | --with-api-key]
                                 selector

Sign into a named private account through native login.

Local human CLI only. Writes native credentials; active account clients or daemons hold login.

positional arguments:
  selector              Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --device-auth         Sign in using a one-time device code approved in your
                        browser.
  --with-api-key        Read the API key from standard input; never put it in
                        command arguments.

Examples:
  codex-wake --wake-root ROOT accounts login work --device-auth
```

## accounts status

Observe sanitized local authentication evidence.

No provider verification or refresh in --json/API/MCP. Human CLI retains native login status.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_account_status`).

```sh
codex-wake --wake-root ROOT accounts status work --json
```

### CLI help

```text
usage: codex-wake accounts status [-h] [--channel {stock,modded}] [--json]
                                  [--expected-target EXPECTED_TARGET]
                                  selector

Observe sanitized local authentication evidence.

No provider verification or refresh in --json/API/MCP. Human CLI retains native login status.

positional arguments:
  selector              Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --json                Emit structured results for this command.
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.

Examples:
  codex-wake --wake-root ROOT accounts status work --json
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selector` | yes | Account name or configured alias. |
| `expected_target` | no | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |

## configuration explain

Explain effective settings, skills and configuration provenance.

Read-only observation; no model turn.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_configuration`).

```sh
codex-wake --wake-root ROOT configuration explain work
```

### CLI help

```text
usage: codex-wake configuration explain [-h]
                                        [--expected-target EXPECTED_TARGET]
                                        [--json]
                                        selector

Explain effective settings, skills and configuration provenance.

Read-only observation; no model turn.

positional arguments:
  selector              Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT configuration explain work
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selector` | yes | Account name or configured alias. |
| `expected_target` | no | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |

## builds list

List registered builds and their exact targets.

Read-only observation; no model turn.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_list`).

```sh
codex-wake --wake-root ROOT builds list --account work
```

### CLI help

```text
usage: codex-wake builds list [-h] [--arguments ARGUMENTS] [--json]
                              [--account ACCOUNT]

List registered builds and their exact targets.

Read-only observation; no model turn.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --json                Emit structured results for this command.
  --account ACCOUNT     Account name or configured alias.

Examples:
  codex-wake --wake-root ROOT builds list --account work
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `account` | yes | Account name or configured alias. |

## builds launch

Open a native client using an exact registered account build.

Attaches a client; no provider turn unless explicitly requested through client arguments.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_launch`).

```sh
codex-wake --wake-root ROOT builds launch --account work --channel modded --expected-target "$TARGET"
```

### CLI help

```text
usage: codex-wake builds launch [-h] [--arguments ARGUMENTS] [--json]
                                [--account ACCOUNT] [--channel {stock,modded}]
                                [--expected-target EXPECTED_TARGET]
                                [--arg NATIVE_ARGS | --args NATIVE_ARGS_JSON]

Open a native client using an exact registered account build.

Attaches a client; no provider turn unless explicitly requested through client arguments.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --json                Emit structured results for this command.
  --account ACCOUNT     Account name or configured alias.
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.
  --arg NATIVE_ARGS     Repeat for each native client argument; use
                        --arg=--flag for options.
  --args NATIVE_ARGS_JSON
                        Native client arguments as a JSON array of strings.

Examples:
  codex-wake --wake-root ROOT builds launch --account work --channel modded --expected-target "$TARGET"
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `account` | yes | Account name or configured alias. |
| `channel` | yes | Registered native build channel (default: modded). |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `args` | no | Native client arguments for the registered build. |

## builds stage

Stage one host-registered immutable build recipe.

Runs the configured build recipe under existing build authority.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_stage`).

```sh
codex-wake --wake-root ROOT builds stage --arguments '{"recipe":"candidate"}'
```

### CLI help

```text
usage: codex-wake builds stage [-h] [--arguments ARGUMENTS] [--json]
                               [--recipe RECIPE]

Stage one host-registered immutable build recipe.

Runs the configured build recipe under existing build authority.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --json                Emit structured results for this command.
  --recipe RECIPE       Host-registered build recipe name, never an arbitrary
                        executable or path.

Examples:
  codex-wake --wake-root ROOT builds stage --arguments '{"recipe":"candidate"}'
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `recipe` | yes | Host-registered build recipe name, never an arbitrary executable or path. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## builds select

Select a staged immutable artifact for an account.

Changes future build selection; does not imply a running daemon changed.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_select`).

```sh
codex-wake --wake-root ROOT builds select --account work --channel modded --expected-target "$TARGET" --identifier ARTIFACT
```

### CLI help

```text
usage: codex-wake builds select [-h] [--arguments ARGUMENTS] [--json]
                                [--account ACCOUNT] [--channel {stock,modded}]
                                [--expected-target EXPECTED_TARGET]
                                [--identifier IDENTIFIER]

Select a staged immutable artifact for an account.

Changes future build selection; does not imply a running daemon changed.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --json                Emit structured results for this command.
  --account ACCOUNT     Account name or configured alias.
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.
  --identifier IDENTIFIER
                        Existing immutable build artifact identifier to
                        select.

Examples:
  codex-wake --wake-root ROOT builds select --account work --channel modded --expected-target "$TARGET" --identifier ARTIFACT
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `account` | yes | Account name or configured alias. |
| `channel` | yes | Registered native build channel (default: modded). |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `identifier` | yes | Existing immutable build artifact identifier to select. |

## builds rollback

Restore the prior registered account build selection.

Changes selected build under existing rollback policy.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_rollback`).

```sh
codex-wake --wake-root ROOT builds rollback --account work --channel modded --expected-target "$TARGET"
```

### CLI help

```text
usage: codex-wake builds rollback [-h] [--arguments ARGUMENTS] [--json]
                                  [--account ACCOUNT]
                                  [--channel {stock,modded}]
                                  [--expected-target EXPECTED_TARGET]

Restore the prior registered account build selection.

Changes selected build under existing rollback policy.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --json                Emit structured results for this command.
  --account ACCOUNT     Account name or configured alias.
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.

Examples:
  codex-wake --wake-root ROOT builds rollback --account work --channel modded --expected-target "$TARGET"
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `account` | yes | Account name or configured alias. |
| `channel` | yes | Registered native build channel (default: modded). |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## history search

Search explicitly permitted saved conversation metadata.

Read-only observation; no model turn.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_history_search`).

```sh
codex-wake --wake-root ROOT history search --owner work --query test
```

### CLI help

```text
usage: codex-wake history search [-h] [--owner OWNERS] [--query QUERY]
                                 [--sort {recent}] [--limit LIMIT] [--json]

Search explicitly permitted saved conversation metadata.

Read-only observation; no model turn.

options:
  -h, --help       show this help message and exit
  --owner OWNERS   Limit search to these explicitly permitted owning accounts;
                   repeat --owner.
  --query QUERY    Filter permitted saved conversation metadata (default:
                   all).
  --sort {recent}  Order by recent activity when set to recent; default
                   preserves existing discovery order.
  --limit LIMIT    Maximum recent conversations, from1 to100 (default:10 for
                   shortcuts).
  --json           Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT history search --owner work --query test
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `owners` | no | Limit search to these explicitly permitted owning accounts; repeat --owner. |
| `query` | no | Filter permitted saved conversation metadata (default: all). |
| `limit` | no | Maximum recent conversations, from1 to100 (default:10 for shortcuts). |
| `sort` | no | Order by recent activity when set to recent; default preserves existing discovery order. |

## history read

Read a saved conversation from its exact permitted owner.

Read-only observation; no model turn.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_history_read`).

```sh
codex-wake --wake-root ROOT history read THREAD --owner work
```

### CLI help

```text
usage: codex-wake history read [-h] --owner OWNER
                               [--expected-target EXPECTED_TARGET] [--json]
                               thread_id

Read a saved conversation from its exact permitted owner.

Read-only observation; no model turn.

positional arguments:
  thread_id             Native saved conversation identifier in its owning
                        account.

options:
  -h, --help            show this help message and exit
  --owner OWNER         Exact account that owns the saved conversation.
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT history read THREAD --owner work
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `owner` | yes | Exact account that owns the saved conversation. |
| `thread_id` | yes | Native saved conversation identifier in its owning account. |
| `expected_target` | no | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |

## history resume

Resume a saved conversation under existing exact-owner authority.

Requires existing enrolled caller permission; does not renew work or allowance.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_history_resume`).

```sh
codex-wake --wake-root ROOT history resume THREAD --owner work --expected-target "$TARGET" --intent INTENT --expires-at TIME --bus-root ROOT --operator-capability FILE
```

### CLI help

```text
usage: codex-wake history resume [-h] --owner OWNER --expected-target
                                 EXPECTED_TARGET [--json] --intent INTENT
                                 --expires-at EXPIRES_AT --bus-root BUS_ROOT
                                 --operator-capability OPERATOR_CAPABILITY
                                 [--app-server APP_SERVER]
                                 thread_id

Resume a saved conversation under existing exact-owner authority.

Requires existing enrolled caller permission; does not renew work or allowance.

positional arguments:
  thread_id             Native saved conversation identifier in its owning
                        account.

options:
  -h, --help            show this help message and exit
  --owner OWNER         Exact account that owns the saved conversation.
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.
  --json                Emit structured results for this command.
  --intent INTENT       Existing exact-owner resume intent; does not grant new
                        work authority.
  --expires-at EXPIRES_AT
                        Expiration timestamp for the resume intent.
  --bus-root BUS_ROOT   Existing enrolled mailbox runtime root for caller
                        verification.
  --operator-capability OPERATOR_CAPABILITY
                        Path to the private operator capability; never its
                        secret contents.
  --app-server APP_SERVER
                        Enrolled native app-server endpoint (default:
                        unix://).

Examples:
  codex-wake --wake-root ROOT history resume THREAD --owner work --expected-target "$TARGET" --intent INTENT --expires-at TIME --bus-root ROOT --operator-capability FILE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `owner` | yes | Exact account that owns the saved conversation. |
| `thread_id` | yes | Native saved conversation identifier in its owning account. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `intent` | yes | Existing exact-owner resume intent; does not grant new work authority. |
| `expires_at` | yes | Expiration timestamp for the resume intent. |

## history import

Copy a supported saved snapshot between stock and profile stores.

Creates a new destination UUID; source remains unchanged. Reports saved snapshot boundaries and excluded unsupported entries; transfers no credentials, grants or allowance.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_history_import`).

```sh
codex-wake --wake-root ROOT history import THREAD --owner work --destination personal --expected-source "$SOURCE" --expected-target "$TARGET" --idempotency-key copy-1
```

### CLI help

```text
usage: codex-wake history import [-h] --owner OWNER --destination DESTINATION
                                 [--channel {stock,modded}]
                                 [--expected-source EXPECTED_SOURCE]
                                 [--expected-target EXPECTED_TARGET]
                                 [--idempotency-key IDEMPOTENCY_KEY] [--yes]
                                 [--json]
                                 thread_id

Copy a supported saved snapshot between stock and profile stores.

Creates a new destination UUID; source remains unchanged. Reports saved snapshot boundaries and excluded unsupported entries; transfers no credentials, grants or allowance.

positional arguments:
  thread_id             Native saved conversation identifier in its owning
                        account.

options:
  -h, --help            show this help message and exit
  --owner OWNER         Exact account that owns the saved conversation.
  --destination DESTINATION
                        Destination account for a distinct source-preserving
                        conversation copy.
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --expected-source EXPECTED_SOURCE
                        Exact source session target JSON from history read.
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.
  --idempotency-key IDEMPOTENCY_KEY
                        Stable key for this intent; retain it to reconcile an
                        uncertain result. Different inputs conflict.
  --yes                 Confirm the displayed scoped effect; does not override
                        a changed target.
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT history import THREAD --owner work --destination personal --expected-source "$SOURCE" --expected-target "$TARGET" --idempotency-key copy-1
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `owner` | yes | Exact account that owns the saved conversation. |
| `thread_id` | yes | Native saved conversation identifier in its owning account. |
| `destination` | yes | Destination account for a distinct source-preserving conversation copy. |
| `channel` | yes | Registered native build channel (default: modded). |
| `expected_source` | yes | Exact source session target JSON from history read. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## daemons list

List account-scoped native daemon observations.

Read-only process/socket/build observation; unavailable is not orphan-free proof.

Transport: CLI / API / OAuth MCP / native MCP (`wake_daemons_list`).

```sh
codex-wake --wake-root ROOT daemons list
```

### CLI help

```text
usage: codex-wake daemons list [-h] [--channel {stock,modded}] [--json]

List account-scoped native daemon observations.

Read-only process/socket/build observation; unavailable is not orphan-free proof.

options:
  -h, --help            show this help message and exit
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT daemons list
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `channel` | no | Registered native build channel (default: modded). |

## daemons status

Inspect the exact account daemon and selected build.

Read-only process/socket/build observation; unavailable is not orphan-free proof.

Transport: CLI / API / OAuth MCP / native MCP (`wake_daemons_status`).

```sh
codex-wake --wake-root ROOT daemons status work
```

### CLI help

```text
usage: codex-wake daemons status [-h] [--channel {stock,modded}] [--json]
                                 account

Inspect the exact account daemon and selected build.

Read-only process/socket/build observation; unavailable is not orphan-free proof.

positional arguments:
  account               Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT daemons status work
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `account` | yes | Account name or configured alias. |
| `channel` | no | Registered native build channel (default: modded). |

## daemons start

Start the selected account daemon.

Exact target and durable intent required. Restart/update/stop interrupt only the selected daemon and require confirmation. Uncertain results require reconciliation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_daemons_start`).

```sh
codex-wake --wake-root ROOT daemons start work --expected-target "$TARGET" --idempotency-key start-1
```

### CLI help

```text
usage: codex-wake daemons start [-h] [--channel {stock,modded}] [--json]
                                [--expected-target EXPECTED_TARGET]
                                [--idempotency-key IDEMPOTENCY_KEY] [--yes]
                                account

Start the selected account daemon.

Exact target and durable intent required. Restart/update/stop interrupt only the selected daemon and require confirmation. Uncertain results require reconciliation.

positional arguments:
  account               Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --json                Emit structured results for this command.
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.
  --idempotency-key IDEMPOTENCY_KEY
                        Stable key for this intent; retain it to reconcile an
                        uncertain result. Different inputs conflict.
  --yes                 Confirm the displayed scoped effect; does not override
                        a changed target.

Examples:
  codex-wake --wake-root ROOT daemons start work --expected-target "$TARGET" --idempotency-key start-1
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `account` | yes | Account name or configured alias. |
| `channel` | no | Registered native build channel (default: modded). |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `confirm` | no | Confirm the displayed scoped effect; does not override a changed target. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## daemons restart

Restart one exact account daemon.

Exact target and durable intent required. Restart/update/stop interrupt only the selected daemon and require confirmation. Uncertain results require reconciliation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_daemons_restart`).

```sh
codex-wake --wake-root ROOT daemons restart work --expected-target "$TARGET" --idempotency-key restart-1 --yes
```

### CLI help

```text
usage: codex-wake daemons restart [-h] [--channel {stock,modded}] [--json]
                                  [--expected-target EXPECTED_TARGET]
                                  [--idempotency-key IDEMPOTENCY_KEY] [--yes]
                                  account

Restart one exact account daemon.

Exact target and durable intent required. Restart/update/stop interrupt only the selected daemon and require confirmation. Uncertain results require reconciliation.

positional arguments:
  account               Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --json                Emit structured results for this command.
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.
  --idempotency-key IDEMPOTENCY_KEY
                        Stable key for this intent; retain it to reconcile an
                        uncertain result. Different inputs conflict.
  --yes                 Confirm the displayed scoped effect; does not override
                        a changed target.

Examples:
  codex-wake --wake-root ROOT daemons restart work --expected-target "$TARGET" --idempotency-key restart-1 --yes
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `account` | yes | Account name or configured alias. |
| `channel` | no | Registered native build channel (default: modded). |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `confirm` | no | Confirm the displayed scoped effect; does not override a changed target. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## daemons update

Update one exact account daemon to a registered build.

Exact target and durable intent required. Restart/update/stop interrupt only the selected daemon and require confirmation. Uncertain results require reconciliation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_daemons_update`).

```sh
codex-wake --wake-root ROOT daemons update work --expected-target "$TARGET" --idempotency-key update-1 --yes
```

### CLI help

```text
usage: codex-wake daemons update [-h] [--channel {stock,modded}] [--json]
                                 [--expected-target EXPECTED_TARGET]
                                 [--idempotency-key IDEMPOTENCY_KEY] [--yes]
                                 account

Update one exact account daemon to a registered build.

Exact target and durable intent required. Restart/update/stop interrupt only the selected daemon and require confirmation. Uncertain results require reconciliation.

positional arguments:
  account               Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --json                Emit structured results for this command.
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.
  --idempotency-key IDEMPOTENCY_KEY
                        Stable key for this intent; retain it to reconcile an
                        uncertain result. Different inputs conflict.
  --yes                 Confirm the displayed scoped effect; does not override
                        a changed target.

Examples:
  codex-wake --wake-root ROOT daemons update work --expected-target "$TARGET" --idempotency-key update-1 --yes
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `account` | yes | Account name or configured alias. |
| `channel` | no | Registered native build channel (default: modded). |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `confirm` | no | Confirm the displayed scoped effect; does not override a changed target. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## daemons stop

Stop one exact account daemon.

Exact target and durable intent required. Restart/update/stop interrupt only the selected daemon and require confirmation. Uncertain results require reconciliation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_daemons_stop`).

```sh
codex-wake --wake-root ROOT daemons stop work --expected-target "$TARGET" --idempotency-key stop-1 --yes
```

### CLI help

```text
usage: codex-wake daemons stop [-h] [--channel {stock,modded}] [--json]
                               [--expected-target EXPECTED_TARGET]
                               [--idempotency-key IDEMPOTENCY_KEY] [--yes]
                               account

Stop one exact account daemon.

Exact target and durable intent required. Restart/update/stop interrupt only the selected daemon and require confirmation. Uncertain results require reconciliation.

positional arguments:
  account               Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --json                Emit structured results for this command.
  --expected-target EXPECTED_TARGET
                        Exact target JSON from the corresponding resolve, list
                        or status command; replacement is refused.
  --idempotency-key IDEMPOTENCY_KEY
                        Stable key for this intent; retain it to reconcile an
                        uncertain result. Different inputs conflict.
  --yes                 Confirm the displayed scoped effect; does not override
                        a changed target.

Examples:
  codex-wake --wake-root ROOT daemons stop work --expected-target "$TARGET" --idempotency-key stop-1 --yes
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `account` | yes | Account name or configured alias. |
| `channel` | no | Registered native build channel (default: modded). |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `confirm` | no | Confirm the displayed scoped effect; does not override a changed target. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## open

Open the registered native client for one private account.

Local human shortcut over builds.launch; internally pins the selected build and starts or attaches its daemon. No model prompt.

Transport: Local human CLI only.

```sh
codex-wake --wake-root ROOT open work
```

### CLI help

```text
usage: codex-wake open [-h] [--channel {stock,modded}] account

Open the registered native client for one private account.

Local human shortcut over builds.launch; internally pins the selected build and starts or attaches its daemon. No model prompt.

positional arguments:
  account               Account name or configured alias.

options:
  -h, --help            show this help message and exit
  --channel {stock,modded}
                        Registered native build channel (default: modded).

Examples:
  codex-wake --wake-root ROOT open work
```

## resume

Reopen a conversation in its named account; bare resume retains emergency-pause release.

ACCOUNT selects the native conversation chooser; --last or UUID selects saved account history. Never mixes account and emergency scope flags.

Transport: Local human CLI only.

```sh
codex-wake --wake-root ROOT resume work --last
```

### CLI help

```text
usage: codex-wake resume [-h] [--all-roots] [--registry-dir REGISTRY_DIR]
                         [--json] [--channel {stock,modded}] [--last]
                         [account] [thread_id]

Reopen a conversation in its named account; bare resume retains emergency-pause release.

ACCOUNT selects the native conversation chooser; --last or UUID selects saved account history. Never mixes account and emergency scope flags.

positional arguments:
  account               Account name or configured alias.
  thread_id             Native saved conversation identifier in its owning
                        account.

options:
  -h, --help            show this help message and exit
  --all-roots           snapshot all registered roots, including disabled
                        roots
  --registry-dir REGISTRY_DIR
                        operator-selected root registry
  --json                Emit structured results for this command.
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --last                Reopen the most recently active saved conversation for
                        the selected account.

Examples:
  codex-wake --wake-root ROOT resume work --last
```

## configuration default-root

Save an explicit user-local root for account shortcuts.

Changes only local shortcut preferences; explicit --wake-root wins. Does not change stock codex or unrelated legacy root defaults.

Transport: Local human CLI only.

```sh
codex-wake --wake-root ROOT configuration default-root ROOT
```

### CLI help

```text
usage: codex-wake configuration default-root [-h] root

Save an explicit user-local root for account shortcuts.

Changes only local shortcut preferences; explicit --wake-root wins. Does not change stock codex or unrelated legacy root defaults.

positional arguments:
  root        Existing private Wake account root saved only for local
              shortcuts.

options:
  -h, --help  show this help message and exit

Examples:
  codex-wake --wake-root ROOT configuration default-root ROOT
```

## history recent

View the latest saved conversations for one permitted account.

Local shortcut to history.search with sort=recent and a bounded limit; API/MCP can use those same search arguments. Partial evidence stays visible.

Transport: Local human CLI only.

```sh
codex-wake --wake-root ROOT history recent --owner work --limit 10
```

### CLI help

```text
usage: codex-wake history recent [-h] --owner OWNER [--limit LIMIT] [--json]

View the latest saved conversations for one permitted account.

Local shortcut to history.search with sort=recent and a bounded limit; API/MCP can use those same search arguments. Partial evidence stays visible.

options:
  -h, --help     show this help message and exit
  --owner OWNER  Exact account that owns the saved conversation.
  --limit LIMIT  Maximum recent conversations, from1 to100 (default:10 for
                 shortcuts).
  --json         Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT history recent --owner work --limit 10
```

## history import-recent

Preview and copy a frozen recent-conversation selection.

Local batch orchestration over protected history.import. Retains exact intents and per-entry outcomes; same source revision/destination reuses the original copy. Requires both account daemons running; preview starts none.

Transport: Local human CLI only.

```sh
codex-wake --wake-root ROOT history import-recent --owner work --destination personal --limit 10
```

### CLI help

```text
usage: codex-wake history import-recent [-h] [--owner OWNER] [--limit LIMIT]
                                        [--json] [--destination DESTINATION]
                                        [--channel {stock,modded}]
                                        [--batch BATCH] [--yes] [--preview]

Preview and copy a frozen recent-conversation selection.

Local batch orchestration over protected history.import. Retains exact intents and per-entry outcomes; same source revision/destination reuses the original copy. Requires both account daemons running; preview starts none.

options:
  -h, --help            show this help message and exit
  --owner OWNER         Exact account that owns the saved conversation.
  --limit LIMIT         Maximum recent conversations, from1 to100 (default:10
                        for shortcuts).
  --json                Emit structured results for this command.
  --destination DESTINATION
                        Destination account for a distinct source-preserving
                        conversation copy.
  --channel {stock,modded}
                        Registered native build channel (default: modded).
  --batch BATCH         Exact frozen copy-batch ID to preview or retry without
                        selecting newer sessions.
  --yes                 Explicitly confirm the frozen source-preserving batch
                        copy.
  --preview             Show/save the frozen selection without native copying
                        or daemon starts.

Examples:
  codex-wake --wake-root ROOT history import-recent --owner work --destination personal --limit 10
```

## builds prepare

Prepare pinned source in an isolated worktree.

Native release work in isolated WSL state; no working-account installation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_prepare`).

```sh
codex-wake --wake-root ROOT builds prepare --recipe RECIPE --upstream SHA --mod-revision SHA
```

### CLI help

```text
usage: codex-wake builds prepare [-h] [--arguments ARGUMENTS]
                                 [--recipe RECIPE] [--upstream UPSTREAM]
                                 [--mod-revision MOD_REVISION]
                                 [--run-id RUN_ID]
                                 [--expected-cache EXPECTED_CACHE]
                                 [--jobs JOBS]
                                 [--output {compact,json,progress,diagnostics}]
                                 [--json] [--max-items MAX_ITEMS] [--confirm]

Prepare pinned source in an isolated worktree.

Native release work in isolated WSL state; no working-account installation.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --recipe RECIPE       Host-registered build recipe name, never an arbitrary
                        executable or path.
  --upstream UPSTREAM   Pinned upstream commit SHA.
  --mod-revision MOD_REVISION
                        Pinned retained mod commit SHA.
  --run-id RUN_ID       Durable native release run identifier.
  --expected-cache EXPECTED_CACHE
                        Exact cache fingerprint returned by cleanup preview.
  --jobs JOBS           Explicit maximum compiler jobs.
  --output {compact,json,progress,diagnostics}
                        Release result presentation.
  --json                Release result presentation.
  --max-items MAX_ITEMS
                        Maximum diagnostic or progress entries.
  --confirm             Confirm the displayed scoped effect; does not override
                        a changed target.

Examples:
  codex-wake --wake-root ROOT builds prepare --recipe RECIPE --upstream SHA --mod-revision SHA
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `recipe` | yes | Host-registered build recipe name, never an arbitrary executable or path. |
| `upstream` | yes | Pinned upstream commit SHA. |
| `mod_revision` | yes | Pinned retained mod commit SHA. |
| `run_id` | no | Durable native release run identifier. |
| `jobs` | no | Explicit maximum compiler jobs. |
| `output` | no | Release result presentation. |
| `max_items` | no | Maximum diagnostic or progress entries. |
| `confirm` | no | Confirm the displayed scoped effect; does not override a changed target. |
| `expected_cache` | no | Exact cache fingerprint returned by cleanup preview. |

## builds status

Inspect a durable native release run.

Native release work in isolated WSL state; no working-account installation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_status`).

```sh
codex-wake --wake-root ROOT builds status --run-id RUN
```

### CLI help

```text
usage: codex-wake builds status [-h] [--arguments ARGUMENTS] [--recipe RECIPE]
                                [--upstream UPSTREAM]
                                [--mod-revision MOD_REVISION]
                                [--run-id RUN_ID]
                                [--expected-cache EXPECTED_CACHE]
                                [--jobs JOBS]
                                [--output {compact,json,progress,diagnostics}]
                                [--json] [--max-items MAX_ITEMS] [--confirm]

Inspect a durable native release run.

Native release work in isolated WSL state; no working-account installation.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --recipe RECIPE       Host-registered build recipe name, never an arbitrary
                        executable or path.
  --upstream UPSTREAM   Pinned upstream commit SHA.
  --mod-revision MOD_REVISION
                        Pinned retained mod commit SHA.
  --run-id RUN_ID       Durable native release run identifier.
  --expected-cache EXPECTED_CACHE
                        Exact cache fingerprint returned by cleanup preview.
  --jobs JOBS           Explicit maximum compiler jobs.
  --output {compact,json,progress,diagnostics}
                        Release result presentation.
  --json                Release result presentation.
  --max-items MAX_ITEMS
                        Maximum diagnostic or progress entries.
  --confirm             Confirm the displayed scoped effect; does not override
                        a changed target.

Examples:
  codex-wake --wake-root ROOT builds status --run-id RUN
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `recipe` | no | Host-registered build recipe name, never an arbitrary executable or path. |
| `upstream` | no | Pinned upstream commit SHA. |
| `mod_revision` | no | Pinned retained mod commit SHA. |
| `run_id` | yes | Durable native release run identifier. |
| `jobs` | no | Explicit maximum compiler jobs. |
| `output` | no | Release result presentation. |
| `max_items` | no | Maximum diagnostic or progress entries. |
| `confirm` | no | Confirm the displayed scoped effect; does not override a changed target. |
| `expected_cache` | no | Exact cache fingerprint returned by cleanup preview. |

## builds build

Build a complete immutable package through Cargo Signal.

Native release work in isolated WSL state; no working-account installation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_build`).

```sh
codex-wake --wake-root ROOT builds build --run-id RUN
```

### CLI help

```text
usage: codex-wake builds build [-h] [--arguments ARGUMENTS] [--recipe RECIPE]
                               [--upstream UPSTREAM]
                               [--mod-revision MOD_REVISION] [--run-id RUN_ID]
                               [--expected-cache EXPECTED_CACHE] [--jobs JOBS]
                               [--output {compact,json,progress,diagnostics}]
                               [--json] [--max-items MAX_ITEMS] [--confirm]

Build a complete immutable package through Cargo Signal.

Native release work in isolated WSL state; no working-account installation.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --recipe RECIPE       Host-registered build recipe name, never an arbitrary
                        executable or path.
  --upstream UPSTREAM   Pinned upstream commit SHA.
  --mod-revision MOD_REVISION
                        Pinned retained mod commit SHA.
  --run-id RUN_ID       Durable native release run identifier.
  --expected-cache EXPECTED_CACHE
                        Exact cache fingerprint returned by cleanup preview.
  --jobs JOBS           Explicit maximum compiler jobs.
  --output {compact,json,progress,diagnostics}
                        Release result presentation.
  --json                Release result presentation.
  --max-items MAX_ITEMS
                        Maximum diagnostic or progress entries.
  --confirm             Confirm the displayed scoped effect; does not override
                        a changed target.

Examples:
  codex-wake --wake-root ROOT builds build --run-id RUN
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `recipe` | no | Host-registered build recipe name, never an arbitrary executable or path. |
| `upstream` | no | Pinned upstream commit SHA. |
| `mod_revision` | no | Pinned retained mod commit SHA. |
| `run_id` | yes | Durable native release run identifier. |
| `jobs` | no | Explicit maximum compiler jobs. |
| `output` | no | Release result presentation. |
| `max_items` | no | Maximum diagnostic or progress entries. |
| `confirm` | no | Confirm the displayed scoped effect; does not override a changed target. |
| `expected_cache` | no | Exact cache fingerprint returned by cleanup preview. |

## builds resume

Reconcile and resume a native release run.

Native release work in isolated WSL state; no working-account installation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_resume`).

```sh
codex-wake --wake-root ROOT builds resume --run-id RUN
```

### CLI help

```text
usage: codex-wake builds resume [-h] [--arguments ARGUMENTS] [--recipe RECIPE]
                                [--upstream UPSTREAM]
                                [--mod-revision MOD_REVISION]
                                [--run-id RUN_ID]
                                [--expected-cache EXPECTED_CACHE]
                                [--jobs JOBS]
                                [--output {compact,json,progress,diagnostics}]
                                [--json] [--max-items MAX_ITEMS] [--confirm]

Reconcile and resume a native release run.

Native release work in isolated WSL state; no working-account installation.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --recipe RECIPE       Host-registered build recipe name, never an arbitrary
                        executable or path.
  --upstream UPSTREAM   Pinned upstream commit SHA.
  --mod-revision MOD_REVISION
                        Pinned retained mod commit SHA.
  --run-id RUN_ID       Durable native release run identifier.
  --expected-cache EXPECTED_CACHE
                        Exact cache fingerprint returned by cleanup preview.
  --jobs JOBS           Explicit maximum compiler jobs.
  --output {compact,json,progress,diagnostics}
                        Release result presentation.
  --json                Release result presentation.
  --max-items MAX_ITEMS
                        Maximum diagnostic or progress entries.
  --confirm             Confirm the displayed scoped effect; does not override
                        a changed target.

Examples:
  codex-wake --wake-root ROOT builds resume --run-id RUN
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `recipe` | no | Host-registered build recipe name, never an arbitrary executable or path. |
| `upstream` | no | Pinned upstream commit SHA. |
| `mod_revision` | no | Pinned retained mod commit SHA. |
| `run_id` | yes | Durable native release run identifier. |
| `jobs` | no | Explicit maximum compiler jobs. |
| `output` | no | Release result presentation. |
| `max_items` | no | Maximum diagnostic or progress entries. |
| `confirm` | no | Confirm the displayed scoped effect; does not override a changed target. |
| `expected_cache` | no | Exact cache fingerprint returned by cleanup preview. |

## builds qualify

Qualify the exact package in disposable state.

Native release work in isolated WSL state; no working-account installation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_qualify`).

```sh
codex-wake --wake-root ROOT builds qualify --run-id RUN
```

### CLI help

```text
usage: codex-wake builds qualify [-h] [--arguments ARGUMENTS]
                                 [--recipe RECIPE] [--upstream UPSTREAM]
                                 [--mod-revision MOD_REVISION]
                                 [--run-id RUN_ID]
                                 [--expected-cache EXPECTED_CACHE]
                                 [--jobs JOBS]
                                 [--output {compact,json,progress,diagnostics}]
                                 [--json] [--max-items MAX_ITEMS] [--confirm]

Qualify the exact package in disposable state.

Native release work in isolated WSL state; no working-account installation.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --recipe RECIPE       Host-registered build recipe name, never an arbitrary
                        executable or path.
  --upstream UPSTREAM   Pinned upstream commit SHA.
  --mod-revision MOD_REVISION
                        Pinned retained mod commit SHA.
  --run-id RUN_ID       Durable native release run identifier.
  --expected-cache EXPECTED_CACHE
                        Exact cache fingerprint returned by cleanup preview.
  --jobs JOBS           Explicit maximum compiler jobs.
  --output {compact,json,progress,diagnostics}
                        Release result presentation.
  --json                Release result presentation.
  --max-items MAX_ITEMS
                        Maximum diagnostic or progress entries.
  --confirm             Confirm the displayed scoped effect; does not override
                        a changed target.

Examples:
  codex-wake --wake-root ROOT builds qualify --run-id RUN
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `recipe` | no | Host-registered build recipe name, never an arbitrary executable or path. |
| `upstream` | no | Pinned upstream commit SHA. |
| `mod_revision` | no | Pinned retained mod commit SHA. |
| `run_id` | yes | Durable native release run identifier. |
| `jobs` | no | Explicit maximum compiler jobs. |
| `output` | no | Release result presentation. |
| `max_items` | no | Maximum diagnostic or progress entries. |
| `confirm` | no | Confirm the displayed scoped effect; does not override a changed target. |
| `expected_cache` | no | Exact cache fingerprint returned by cleanup preview. |

## builds cleanup

Preview or explicitly clean an inactive build cache.

Native release work in isolated WSL state; no working-account installation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_cleanup`).

```sh
codex-wake --wake-root ROOT builds cleanup --run-id RUN
```

### CLI help

```text
usage: codex-wake builds cleanup [-h] [--arguments ARGUMENTS]
                                 [--recipe RECIPE] [--upstream UPSTREAM]
                                 [--mod-revision MOD_REVISION]
                                 [--run-id RUN_ID]
                                 [--expected-cache EXPECTED_CACHE]
                                 [--jobs JOBS]
                                 [--output {compact,json,progress,diagnostics}]
                                 [--json] [--max-items MAX_ITEMS] [--confirm]

Preview or explicitly clean an inactive build cache.

Native release work in isolated WSL state; no working-account installation.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --recipe RECIPE       Host-registered build recipe name, never an arbitrary
                        executable or path.
  --upstream UPSTREAM   Pinned upstream commit SHA.
  --mod-revision MOD_REVISION
                        Pinned retained mod commit SHA.
  --run-id RUN_ID       Durable native release run identifier.
  --expected-cache EXPECTED_CACHE
                        Exact cache fingerprint returned by cleanup preview.
  --jobs JOBS           Explicit maximum compiler jobs.
  --output {compact,json,progress,diagnostics}
                        Release result presentation.
  --json                Release result presentation.
  --max-items MAX_ITEMS
                        Maximum diagnostic or progress entries.
  --confirm             Confirm the displayed scoped effect; does not override
                        a changed target.

Examples:
  codex-wake --wake-root ROOT builds cleanup --run-id RUN
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `recipe` | no | Host-registered build recipe name, never an arbitrary executable or path. |
| `upstream` | no | Pinned upstream commit SHA. |
| `mod_revision` | no | Pinned retained mod commit SHA. |
| `run_id` | yes | Durable native release run identifier. |
| `jobs` | no | Explicit maximum compiler jobs. |
| `output` | no | Release result presentation. |
| `max_items` | no | Maximum diagnostic or progress entries. |
| `confirm` | no | Confirm the displayed scoped effect; does not override a changed target. |
| `expected_cache` | no | Exact cache fingerprint returned by cleanup preview. |

## builds run

Prepare, build and qualify one native release.

Native release work in isolated WSL state; no working-account installation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_builds_run`).

```sh
codex-wake --wake-root ROOT builds run --recipe RECIPE --upstream SHA --mod-revision SHA
```

### CLI help

```text
usage: codex-wake builds run [-h] [--arguments ARGUMENTS] [--recipe RECIPE]
                             [--upstream UPSTREAM]
                             [--mod-revision MOD_REVISION] [--run-id RUN_ID]
                             [--expected-cache EXPECTED_CACHE] [--jobs JOBS]
                             [--output {compact,json,progress,diagnostics}]
                             [--json] [--max-items MAX_ITEMS] [--confirm]

Prepare, build and qualify one native release.

Native release work in isolated WSL state; no working-account installation.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --recipe RECIPE       Host-registered build recipe name, never an arbitrary
                        executable or path.
  --upstream UPSTREAM   Pinned upstream commit SHA.
  --mod-revision MOD_REVISION
                        Pinned retained mod commit SHA.
  --run-id RUN_ID       Durable native release run identifier.
  --expected-cache EXPECTED_CACHE
                        Exact cache fingerprint returned by cleanup preview.
  --jobs JOBS           Explicit maximum compiler jobs.
  --output {compact,json,progress,diagnostics}
                        Release result presentation.
  --json                Release result presentation.
  --max-items MAX_ITEMS
                        Maximum diagnostic or progress entries.
  --confirm             Confirm the displayed scoped effect; does not override
                        a changed target.

Examples:
  codex-wake --wake-root ROOT builds run --recipe RECIPE --upstream SHA --mod-revision SHA
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `recipe` | no | Host-registered build recipe name, never an arbitrary executable or path. |
| `upstream` | no | Pinned upstream commit SHA. |
| `mod_revision` | no | Pinned retained mod commit SHA. |
| `run_id` | no | Durable native release run identifier. |
| `jobs` | no | Explicit maximum compiler jobs. |
| `output` | no | Release result presentation. |
| `max_items` | no | Maximum diagnostic or progress entries. |
| `confirm` | no | Confirm the displayed scoped effect; does not override a changed target. |
| `expected_cache` | no | Exact cache fingerprint returned by cleanup preview. |

## migration preview

Preview the existing host-selected migration or independent-profile adoption.

Host migration strategy adopt_independent preserves history, sign-ins and local settings; no effect in preview.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_migration_preview`).

```sh
codex-wake --wake-root ROOT migration preview
```

### CLI help

```text
usage: codex-wake migration preview [-h] [--arguments ARGUMENTS] [--json]

Preview the existing host-selected migration or independent-profile adoption.

Host migration strategy adopt_independent preserves history, sign-ins and local settings; no effect in preview.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT migration preview
```

## migration apply

Apply a pinned qualified migration or independent-profile adoption.

Local CLI uses operator authority; API/MCP require scoped grants. Mutations retain exact pins, durable intent and rollback custody.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_migration_apply`).

```sh
codex-wake --wake-root ROOT migration apply --arguments "$ARGUMENTS"
```

### CLI help

```text
usage: codex-wake migration apply [-h] [--arguments ARGUMENTS] [--json]

Apply a pinned qualified migration or independent-profile adoption.

Local CLI uses operator authority; API/MCP require scoped grants. Mutations retain exact pins, durable intent and rollback custody.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT migration apply --arguments "$ARGUMENTS"
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## migration rollback

Roll back one attributable unchanged migration or adoption.

Preserves changed targets and uncertain outcomes for reconciliation.

Transport: CLI / API / OAuth MCP / native MCP (`wake_controller_migration_rollback`).

```sh
codex-wake --wake-root ROOT migration rollback --arguments "$ARGUMENTS"
```

### CLI help

```text
usage: codex-wake migration rollback [-h] [--arguments ARGUMENTS] [--json]

Roll back one attributable unchanged migration or adoption.

Preserves changed targets and uncertain outcomes for reconciliation.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced JSON object of operation arguments; preserved
                        for scripts. See generated command reference.
  --json                Emit structured results for this command.

Examples:
  codex-wake --wake-root ROOT migration rollback --arguments "$ARGUMENTS"
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `receipt_id` | yes | Exact prior migration receipt for a qualified rollback. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs apply

Apply owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_apply`).

```sh
codex-wake --wake-root ROOT tabs apply --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs apply [-h] [--arguments ARGUMENTS] [--json]
                             [--request-id REQUEST_ID]
                             [--expected-target EXPECTED_TARGET]
                             [--plan-id PLAN_ID] [--workspace WORKSPACE]
                             [--session SESSION_SELECTOR]
                             [--server SESSION_SERVER]
                             [--socket-path SOCKET_PATH]
                             [--session-id SESSION_ID]
                             [--app-server APP_SERVER] [--timeout TIMEOUT]
                             [--bus-root BUS_ROOT]
                             [--operator-capability OPERATOR_CAPABILITY]
                             [--actor-capability ACTOR_CAPABILITY]

Apply owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --plan-id PLAN_ID     Exact retained plan ID from preview.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.
  --socket-path SOCKET_PATH
                        Legacy explicit tmux adapter option.
  --session-id SESSION_ID
                        Legacy explicit tmux adapter option.
  --app-server APP_SERVER
                        Legacy explicit tmux adapter option.
  --timeout TIMEOUT
  --bus-root BUS_ROOT
  --operator-capability OPERATOR_CAPABILITY
  --actor-capability ACTOR_CAPABILITY

Examples:
  codex-wake --wake-root ROOT tabs apply --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `plan_id` | yes | plan id. |
| `workspace` | yes | workspace. |

## tabs capture

Capture owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_capture`).

```sh
codex-wake --wake-root ROOT tabs capture --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs capture [-h] [--arguments ARGUMENTS] [--json]
                               [--request-id REQUEST_ID]
                               [--expected-target EXPECTED_TARGET]
                               [--lines LINES] [--pane PANE]
                               [--workspace WORKSPACE]
                               [--session SESSION_SELECTOR]
                               [--server SESSION_SERVER]

Capture owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --lines LINES         Lines.
  --pane PANE           Exact native pane ID from tabs show (for example %4).
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs capture --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `lines` | no | lines. |
| `pane` | yes | pane. |
| `workspace` | yes | workspace. |

## tabs close

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_close`).

```sh
codex-wake --wake-root ROOT tabs close --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs close [-h] [--arguments ARGUMENTS] [--json]
                             [--request-id REQUEST_ID]
                             [--expected-target EXPECTED_TARGET] [--force]
                             [--dry-run] [--window WINDOW]
                             [--workspace WORKSPACE]
                             [--session SESSION_SELECTOR]
                             [--server SESSION_SERVER]

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --force               Explicitly override supported active/focused guards;
                        never overrides stale identity.
  --dry-run             Preview only; no terminal layout mutation.
  --window WINDOW       Exact native window ID from tabs list/show (for
                        example @3); names are not identity pins.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs close --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `force` | no | force. |
| `preview` | no | Show/save the frozen selection without native copying or daemon starts. |
| `window` | yes | window. |
| `workspace` | yes | workspace. |

## tabs create

Create an owned shell tab, or select --profile for a qualified host-owned native profile attachment; no fallback.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_create`).

```sh
codex-wake --wake-root ROOT tabs create --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs create [-h] [--arguments ARGUMENTS] [--json]
                              [--request-id REQUEST_ID] [--argv ARGV]
                              [--cwd CWD] [--expected-target EXPECTED_TARGET]
                              [--name NAME] [--dry-run] [--profile PROFILE]
                              [--workspace WORKSPACE]
                              [--session SESSION_SELECTOR]
                              [--server SESSION_SERVER]

Create an owned shell tab, or select --profile for a qualified host-owned native profile attachment; no fallback.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --argv ARGV           Explicit new-tab command argv; overrides saved command
                        defaults.
  --cwd CWD             Cwd.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --name NAME           Name.
  --dry-run             Preview only; no terminal layout mutation.
  --profile PROFILE     Existing account/profile selector or alias; host
                        registry selects build and home. Unsupported backends
                        remain held; no shell fallback.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs create --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `cwd` | no | cwd. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `name` | yes | name. |
| `preview` | no | Show/save the frozen selection without native copying or daemon starts. |
| `workspace` | yes | workspace. |
| `argv` | no | argv. |
| `profile` | no | profile. |

## tabs focus

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_focus`).

```sh
codex-wake --wake-root ROOT tabs focus --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs focus [-h] [--arguments ARGUMENTS] [--json]
                             [--request-id REQUEST_ID]
                             [--expected-target EXPECTED_TARGET] [--dry-run]
                             [--window WINDOW] [--workspace WORKSPACE]
                             [--session SESSION_SELECTOR]
                             [--server SESSION_SERVER]

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --dry-run             Preview only; no terminal layout mutation.
  --window WINDOW       Exact native window ID from tabs list/show (for
                        example @3); names are not identity pins.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs focus --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `preview` | no | Show/save the frozen selection without native copying or daemon starts. |
| `window` | yes | window. |
| `workspace` | yes | workspace. |

## tabs group-delete

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_group_delete`).

```sh
codex-wake --wake-root ROOT tabs group-delete
```

### CLI help

```text
usage: codex-wake tabs group-delete [-h] [--arguments ARGUMENTS] [--json]
                                    [--request-id REQUEST_ID]
                                    [--expected-target EXPECTED_TARGET]
                                    [--name NAME]
                                    [view_name]

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

positional arguments:
  view_name             Saved logical view or group name.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --name NAME           Name.

Examples:
  codex-wake --wake-root ROOT tabs group-delete
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `name` | yes | name. |

## tabs group-list

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_group_list`).

```sh
codex-wake --wake-root ROOT tabs group-list
```

### CLI help

```text
usage: codex-wake tabs group-list [-h] [--arguments ARGUMENTS] [--json]

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.

Examples:
  codex-wake --wake-root ROOT tabs group-list
```

## tabs group-save

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_group_save`).

```sh
codex-wake --wake-root ROOT tabs group-save
```

### CLI help

```text
usage: codex-wake tabs group-save [-h] [--arguments ARGUMENTS] [--json]
                                  [--request-id REQUEST_ID]
                                  [--expected-target EXPECTED_TARGET]
                                  [--labels LABELS] [--member MEMBERS]
                                  [--name NAME]
                                  [view_name]

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

positional arguments:
  view_name             Saved logical view or group name.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --labels LABELS       Labels.
  --member MEMBERS      Stable attachment references from tabs list; repeat
                        --member.
  --name NAME           Name.

Examples:
  codex-wake --wake-root ROOT tabs group-save
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `members` | yes | members. |
| `name` | yes | name. |
| `labels` | no | labels. |

## tabs group-show

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_group_show`).

```sh
codex-wake --wake-root ROOT tabs group-show
```

### CLI help

```text
usage: codex-wake tabs group-show [-h] [--arguments ARGUMENTS] [--json]
                                  [--name NAME]
                                  [view_name]

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

positional arguments:
  view_name             Saved logical view or group name.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --name NAME           Name.

Examples:
  codex-wake --wake-root ROOT tabs group-show
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `name` | yes | name. |

## tabs input

Input owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_input`).

```sh
codex-wake --wake-root ROOT tabs input --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs input [-h] [--arguments ARGUMENTS] [--json]
                             [--request-id REQUEST_ID] [--custody CUSTODY]
                             [--expected-target EXPECTED_TARGET]
                             [--input INPUT] [--pane PANE]
                             [--transport {structured,terminal}]
                             [--workspace WORKSPACE]
                             [--session SESSION_SELECTOR]
                             [--server SESSION_SERVER]

Input owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --custody CUSTODY     Exact host input custody object from tabs show; never
                        grants ownership of another stdin.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --input INPUT         Literal prompt text; only sent through separately
                        qualified host input custody.
  --pane PANE           Exact native pane ID from tabs show (for example %4).
  --transport {structured,terminal}
                        Explicit qualified input transport; terminal is never
                        fallback after uncertain structured input.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs input --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `custody` | yes | custody. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `input` | yes | input. |
| `pane` | yes | pane. |
| `transport` | yes | transport. |
| `workspace` | yes | workspace. |

## tabs list

List owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_list`).

```sh
codex-wake --wake-root ROOT tabs list
```

### CLI help

```text
usage: codex-wake tabs list [-h] [--arguments ARGUMENTS] [--json]

List owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.

Examples:
  codex-wake --wake-root ROOT tabs list
```

## tabs monitor refresh

Observe or control the bounded read-only tab monitor.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_monitor_refresh`).

```sh
codex-wake --wake-root ROOT tabs monitor-refresh
```

### CLI help

```text
usage: codex-wake tabs monitor-refresh [-h] [--arguments ARGUMENTS] [--json]

Observe or control the bounded read-only tab monitor.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.

Examples:
  codex-wake --wake-root ROOT tabs monitor-refresh
```

## tabs monitor start

Observe or control the bounded read-only tab monitor.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_monitor_start`).

```sh
codex-wake --wake-root ROOT tabs monitor-start
```

### CLI help

```text
usage: codex-wake tabs monitor-start [-h] [--arguments ARGUMENTS] [--json]
                                     [--request-id REQUEST_ID]
                                     [--activity | --no-activity]
                                     [--cycle-timeout CYCLE_TIMEOUT]
                                     [--error-interval ERROR_INTERVAL]
                                     [--errors | --no-errors]
                                     [--expected-target EXPECTED_TARGET]
                                     [--health | --no-health]
                                     [--health-interval HEALTH_INTERVAL]
                                     [--interval INTERVAL]
                                     [--probe-timeout PROBE_TIMEOUT]
                                     [--stale-after STALE_AFTER]

Observe or control the bounded read-only tab monitor.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --activity, --no-activity
                        Enable passive activity observations; --no-activity
                        disables this tier.
  --cycle-timeout CYCLE_TIMEOUT
                        Cycle timeout.
  --error-interval ERROR_INTERVAL
                        Eligible visible-error cadence in seconds, minimum5.
  --errors, --no-errors
                        Enable redacted visible-error checks; independent of
                        activity.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --health, --no-health
                        Enable exact responsiveness checks; independent of
                        activity.
  --health-interval HEALTH_INTERVAL
                        Background responsiveness cadence in seconds,
                        minimum60.
  --interval INTERVAL   Interval.
  --probe-timeout PROBE_TIMEOUT
                        Probe timeout.
  --stale-after STALE_AFTER
                        Stale after.

Examples:
  codex-wake --wake-root ROOT tabs monitor-start
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `activity` | no | activity. |
| `health` | no | health. |
| `errors` | no | errors. |
| `health_interval` | no | health interval. |
| `error_interval` | no | error interval. |
| `cycle_timeout` | no | cycle timeout. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `interval` | no | interval. |
| `probe_timeout` | no | probe timeout. |
| `stale_after` | no | stale after. |

## tabs monitor status

Observe or control the bounded read-only tab monitor.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_monitor_status`).

```sh
codex-wake --wake-root ROOT tabs monitor-status
```

### CLI help

```text
usage: codex-wake tabs monitor-status [-h] [--arguments ARGUMENTS] [--json]

Observe or control the bounded read-only tab monitor.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.

Examples:
  codex-wake --wake-root ROOT tabs monitor-status
```

## tabs monitor stop

Observe or control the bounded read-only tab monitor.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_monitor_stop`).

```sh
codex-wake --wake-root ROOT tabs monitor-stop
```

### CLI help

```text
usage: codex-wake tabs monitor-stop [-h] [--arguments ARGUMENTS] [--json]
                                    [--request-id REQUEST_ID]
                                    [--expected-target EXPECTED_TARGET]
                                    [--timeout TIMEOUT]

Observe or control the bounded read-only tab monitor.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --timeout TIMEOUT     Timeout.

Examples:
  codex-wake --wake-root ROOT tabs monitor-stop
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `timeout` | no | timeout. |

## tabs move

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_move`).

```sh
codex-wake --wake-root ROOT tabs move --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs move [-h] [--arguments ARGUMENTS] [--json]
                            [--request-id REQUEST_ID]
                            [--destination DESTINATION]
                            [--expected-destination EXPECTED_DESTINATION]
                            [--expected-target EXPECTED_TARGET] [--force]
                            [--index INDEX] [--dry-run] [--window WINDOW]
                            [--workspace WORKSPACE]
                            [--session SESSION_SELECTOR]
                            [--server SESSION_SERVER]

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --destination DESTINATION
                        Destination terminal session name or stable ID;
                        compatible backend/server required.
  --expected-destination EXPECTED_DESTINATION
                        Exact destination target; ordinary local CLI resolves
                        it.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --force               Explicitly override supported active/focused guards;
                        never overrides stale identity.
  --index INDEX         Index.
  --dry-run             Preview only; no terminal layout mutation.
  --window WINDOW       Exact native window ID from tabs list/show (for
                        example @3); names are not identity pins.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs move --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `destination` | yes | Destination account for a distinct source-preserving conversation copy. |
| `expected_destination` | yes | expected destination. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `force` | no | force. |
| `index` | no | index. |
| `preview` | no | Show/save the frozen selection without native copying or daemon starts. |
| `window` | yes | window. |
| `workspace` | yes | workspace. |

## tabs park

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_park`).

```sh
codex-wake --wake-root ROOT tabs park --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs park [-h] [--arguments ARGUMENTS] [--json]
                            [--request-id REQUEST_ID]
                            [--destination DESTINATION]
                            [--expected-destination EXPECTED_DESTINATION]
                            [--expected-target EXPECTED_TARGET] [--force]
                            [--dry-run] [--window WINDOW]
                            [--workspace WORKSPACE]
                            [--session SESSION_SELECTOR]
                            [--server SESSION_SERVER]

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --destination DESTINATION
                        Destination terminal session name or stable ID;
                        compatible backend/server required.
  --expected-destination EXPECTED_DESTINATION
                        Exact destination target; ordinary local CLI resolves
                        it.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --force               Explicitly override supported active/focused guards;
                        never overrides stale identity.
  --dry-run             Preview only; no terminal layout mutation.
  --window WINDOW       Exact native window ID from tabs list/show (for
                        example @3); names are not identity pins.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs park --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `destination` | yes | Destination account for a distinct source-preserving conversation copy. |
| `expected_destination` | yes | expected destination. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `force` | no | force. |
| `preview` | no | Show/save the frozen selection without native copying or daemon starts. |
| `window` | yes | window. |
| `workspace` | yes | workspace. |

## tabs policy configure

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_policy_configure`).

```sh
codex-wake --wake-root ROOT tabs policy-configure --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs policy-configure [-h] [--arguments ARGUMENTS] [--json]
                                        [--request-id REQUEST_ID]
                                        [--criterion CRITERIA]
                                        [--debounce-seconds DEBOUNCE_SECONDS]
                                        [--expected-target EXPECTED_TARGET]
                                        [--max-swaps-per-tick MAX_SWAPS_PER_TICK]
                                        [--min-interval-seconds MIN_INTERVAL_SECONDS]
                                        [--mode MODE] [--pin PINS]
                                        [--stale-after-seconds STALE_AFTER_SECONDS]
                                        [--view VIEW] [--workspace WORKSPACE]
                                        [--session SESSION_SELECTOR]
                                        [--server SESSION_SERVER]
                                        [--group-by GROUP_BY]
                                        [--sort-by SORT_BY]

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --criterion CRITERIA  Layered trait ordering criterion; repeat --criterion.
  --debounce-seconds DEBOUNCE_SECONDS
                        Debounce seconds.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --max-swaps-per-tick MAX_SWAPS_PER_TICK
                        Max swaps per tick.
  --min-interval-seconds MIN_INTERVAL_SECONDS
                        Min interval seconds.
  --mode MODE           Mode.
  --pin PINS            Pins.
  --stale-after-seconds STALE_AFTER_SECONDS
                        Stale after seconds.
  --view VIEW           View.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.
  --group-by GROUP_BY   Layered grouping trait; repeat in order.
  --sort-by SORT_BY     Layered sorting trait; repeat in order.

Examples:
  codex-wake --wake-root ROOT tabs policy-configure --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `criteria` | no | criteria. |
| `debounce_seconds` | no | debounce seconds. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `max_swaps_per_tick` | no | max swaps per tick. |
| `min_interval_seconds` | no | min interval seconds. |
| `mode` | no | Create an independent private configuration snapshot; legacy creation remains the default. |
| `pins` | no | pins. |
| `stale_after_seconds` | no | stale after seconds. |
| `view` | no | view. |
| `workspace` | yes | workspace. |

## tabs policy disable

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_policy_disable`).

```sh
codex-wake --wake-root ROOT tabs policy-disable
```

### CLI help

```text
usage: codex-wake tabs policy-disable [-h] [--arguments ARGUMENTS] [--json]
                                      [--request-id REQUEST_ID]
                                      [--expected-target EXPECTED_TARGET]

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.

Examples:
  codex-wake --wake-root ROOT tabs policy-disable
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |

## tabs policy enable

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_policy_enable`).

```sh
codex-wake --wake-root ROOT tabs policy-enable
```

### CLI help

```text
usage: codex-wake tabs policy-enable [-h] [--arguments ARGUMENTS] [--json]
                                     [--request-id REQUEST_ID]
                                     [--acknowledge-pending]
                                     [--expected-target EXPECTED_TARGET]

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --acknowledge-pending
                        Acknowledge pending.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.

Examples:
  codex-wake --wake-root ROOT tabs policy-enable
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `acknowledge_pending` | no | acknowledge pending. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |

## tabs policy pause

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_policy_pause`).

```sh
codex-wake --wake-root ROOT tabs policy-pause
```

### CLI help

```text
usage: codex-wake tabs policy-pause [-h] [--arguments ARGUMENTS] [--json]
                                    [--request-id REQUEST_ID]
                                    [--expected-target EXPECTED_TARGET]
                                    [--reason REASON]

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --reason REASON       Reason.

Examples:
  codex-wake --wake-root ROOT tabs policy-pause
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `reason` | no | reason. |

## tabs policy status

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_policy_status`).

```sh
codex-wake --wake-root ROOT tabs policy-status
```

### CLI help

```text
usage: codex-wake tabs policy-status [-h] [--arguments ARGUMENTS] [--json]

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.

Examples:
  codex-wake --wake-root ROOT tabs policy-status
```

## tabs policy tick

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_policy_tick`).

```sh
codex-wake --wake-root ROOT tabs policy-tick
```

### CLI help

```text
usage: codex-wake tabs policy-tick [-h] [--arguments ARGUMENTS] [--json]
                                   [--request-id REQUEST_ID]
                                   [--expected-target EXPECTED_TARGET]

Opt-in bounded physical organization; preserve manual changes.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.

Examples:
  codex-wake --wake-root ROOT tabs policy-tick
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |

## tabs preview

Preview owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_preview`).

```sh
codex-wake --wake-root ROOT tabs preview --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs preview [-h] [--arguments ARGUMENTS] [--json]
                               [--request-id REQUEST_ID]
                               [--criterion CRITERIA]
                               [--expected-target EXPECTED_TARGET]
                               [--mode {activity,repository,traits}]
                               [--pin PINS] [--workspace WORKSPACE]
                               [--session SESSION_SELECTOR]
                               [--server SESSION_SERVER] [--group-by GROUP_BY]
                               [--sort-by SORT_BY] [--socket-path SOCKET_PATH]
                               [--session-id SESSION_ID]
                               [--app-server APP_SERVER] [--timeout TIMEOUT]
                               [--bus-root BUS_ROOT]
                               [--operator-capability OPERATOR_CAPABILITY]
                               [--actor-capability ACTOR_CAPABILITY]

Preview owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --criterion CRITERIA  Layered trait ordering criterion; repeat --criterion.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --mode {activity,repository,traits}
                        Mode.
  --pin PINS            Pins.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.
  --group-by GROUP_BY   Layered grouping trait; repeat in order.
  --sort-by SORT_BY     Layered sorting trait; repeat in order.
  --socket-path SOCKET_PATH
                        Legacy explicit tmux adapter option.
  --session-id SESSION_ID
                        Legacy explicit tmux adapter option.
  --app-server APP_SERVER
                        Legacy explicit tmux adapter option.
  --timeout TIMEOUT
  --bus-root BUS_ROOT
  --operator-capability OPERATOR_CAPABILITY
  --actor-capability ACTOR_CAPABILITY

Examples:
  codex-wake --wake-root ROOT tabs preview --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `criteria` | no | criteria. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `mode` | no | Create an independent private configuration snapshot; legacy creation remains the default. |
| `pins` | no | pins. |
| `workspace` | yes | workspace. |

## tabs reattach-apply

Reattach the exact saved conversation; retain source by default and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_reattach_apply`).

```sh
codex-wake --wake-root ROOT tabs reattach-apply
```

### CLI help

```text
usage: codex-wake tabs reattach-apply [-h] [--arguments ARGUMENTS] [--json]
                                      [--request-id REQUEST_ID]
                                      [--expected-target EXPECTED_TARGET]
                                      [--plan-id PLAN_ID]

Reattach the exact saved conversation; retain source by default and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --plan-id PLAN_ID     Exact retained plan ID from preview.

Examples:
  codex-wake --wake-root ROOT tabs reattach-apply
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `plan_id` | yes | plan id. |

## tabs reattach-preview

Reattach the exact saved conversation; retain source by default and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_reattach_preview`).

```sh
codex-wake --wake-root ROOT tabs reattach-preview --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs reattach-preview [-h] [--arguments ARGUMENTS] [--json]
                                        [--request-id REQUEST_ID]
                                        [--destination DESTINATION]
                                        [--expected-destination EXPECTED_DESTINATION]
                                        [--expected-target EXPECTED_TARGET]
                                        [--force] [--retire-source]
                                        [--window WINDOW]
                                        [--workspace WORKSPACE]
                                        [--session SESSION_SELECTOR]
                                        [--server SESSION_SERVER]

Reattach the exact saved conversation; retain source by default and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --destination DESTINATION
                        Destination terminal session name or stable ID;
                        compatible backend/server required.
  --expected-destination EXPECTED_DESTINATION
                        Exact destination target; ordinary local CLI resolves
                        it.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --force               Explicitly override supported active/focused guards;
                        never overrides stale identity.
  --retire-source       Retire source only after exact destination
                        verification; default retains source.
  --window WINDOW       Exact native window ID from tabs list/show (for
                        example @3); names are not identity pins.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs reattach-preview --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `destination` | yes | Destination account for a distinct source-preserving conversation copy. |
| `expected_destination` | yes | expected destination. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `force` | no | force. |
| `retire_source` | no | retire source. |
| `window` | yes | window. |
| `workspace` | yes | workspace. |

## tabs reattach-status

Reattach the exact saved conversation; retain source by default and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_reattach_status`).

```sh
codex-wake --wake-root ROOT tabs reattach-status
```

### CLI help

```text
usage: codex-wake tabs reattach-status [-h] [--arguments ARGUMENTS] [--json]
                                       [--expected-target EXPECTED_TARGET]
                                       [--plan-id PLAN_ID]

Reattach the exact saved conversation; retain source by default and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --plan-id PLAN_ID     Exact retained plan ID from preview.

Examples:
  codex-wake --wake-root ROOT tabs reattach-status
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `expected_target` | no | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `plan_id` | yes | plan id. |

## tabs recovery apply

Capture or restore exact workspace conversations; unknown historical mappings remain held.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_recovery_apply`).

```sh
codex-wake --wake-root ROOT tabs recovery-apply --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs recovery-apply [-h] [--arguments ARGUMENTS] [--json]
                                      [--request-id REQUEST_ID]
                                      [--capture-id CAPTURE_ID]
                                      [--expected-target EXPECTED_TARGET]
                                      [--intent INTENT] [--restore-layout]
                                      [--workspace WORKSPACE]
                                      [--session SESSION_SELECTOR]
                                      [--server SESSION_SERVER]

Capture or restore exact workspace conversations; unknown historical mappings remain held.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --capture-id CAPTURE_ID
                        Durable whole-workspace capture identifier.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --intent INTENT       Stable recovery intent; reconcile uncertain prior
                        launches before trying another intent.
  --restore-layout      Restore missing exact captured conversations into the
                        selected recreated workspace.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs recovery-apply --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `capture_id` | yes | capture id. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `intent` | yes | Existing exact-owner resume intent; does not grant new work authority. |
| `restore_layout` | no | restore layout. |
| `workspace` | yes | workspace. |

## tabs recovery capture

Capture or restore exact workspace conversations; unknown historical mappings remain held.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_recovery_capture`).

```sh
codex-wake --wake-root ROOT tabs recovery-capture --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs recovery-capture [-h] [--arguments ARGUMENTS] [--json]
                                        [--request-id REQUEST_ID]
                                        [--capture-id CAPTURE_ID]
                                        [--expected-target EXPECTED_TARGET]
                                        [--workspace WORKSPACE]
                                        [--session SESSION_SELECTOR]
                                        [--server SESSION_SERVER]

Capture or restore exact workspace conversations; unknown historical mappings remain held.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --capture-id CAPTURE_ID
                        Durable whole-workspace capture identifier.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs recovery-capture --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `capture_id` | no | capture id. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `workspace` | yes | workspace. |

## tabs recovery preview

Capture or restore exact workspace conversations; unknown historical mappings remain held.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_recovery_preview`).

```sh
codex-wake --wake-root ROOT tabs recovery-preview --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs recovery-preview [-h] [--arguments ARGUMENTS] [--json]
                                        [--capture-id CAPTURE_ID]
                                        [--restore-layout]
                                        [--workspace WORKSPACE]
                                        [--session SESSION_SELECTOR]
                                        [--server SESSION_SERVER]

Capture or restore exact workspace conversations; unknown historical mappings remain held.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --capture-id CAPTURE_ID
                        Durable whole-workspace capture identifier.
  --restore-layout      Restore missing exact captured conversations into the
                        selected recreated workspace.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs recovery-preview --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `capture_id` | yes | capture id. |
| `restore_layout` | no | restore layout. |
| `workspace` | yes | workspace. |

## tabs recovery status

Capture or restore exact workspace conversations; unknown historical mappings remain held.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_recovery_status`).

```sh
codex-wake --wake-root ROOT tabs recovery-status
```

### CLI help

```text
usage: codex-wake tabs recovery-status [-h] [--arguments ARGUMENTS] [--json]
                                       [--capture-id CAPTURE_ID]
                                       [--intent INTENT]

Capture or restore exact workspace conversations; unknown historical mappings remain held.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --capture-id CAPTURE_ID
                        Durable whole-workspace capture identifier.
  --intent INTENT       Stable recovery intent; reconcile uncertain prior
                        launches before trying another intent.

Examples:
  codex-wake --wake-root ROOT tabs recovery-status
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `capture_id` | no | capture id. |
| `intent` | no | Existing exact-owner resume intent; does not grant new work authority. |

## tabs rename

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_rename`).

```sh
codex-wake --wake-root ROOT tabs rename --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs rename [-h] [--arguments ARGUMENTS] [--json]
                              [--request-id REQUEST_ID]
                              [--expected-target EXPECTED_TARGET]
                              [--name NAME] [--dry-run] [--window WINDOW]
                              [--workspace WORKSPACE]
                              [--session SESSION_SELECTOR]
                              [--server SESSION_SERVER]

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --name NAME           Name.
  --dry-run             Preview only; no terminal layout mutation.
  --window WINDOW       Exact native window ID from tabs list/show (for
                        example @3); names are not identity pins.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs rename --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `name` | yes | name. |
| `preview` | no | Show/save the frozen selection without native copying or daemon starts. |
| `window` | yes | window. |
| `workspace` | yes | workspace. |

## tabs restore

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_restore`).

```sh
codex-wake --wake-root ROOT tabs restore --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs restore [-h] [--arguments ARGUMENTS] [--json]
                               [--request-id REQUEST_ID]
                               [--destination DESTINATION]
                               [--expected-destination EXPECTED_DESTINATION]
                               [--expected-target EXPECTED_TARGET] [--force]
                               [--dry-run] [--receipt-id RECEIPT_ID]
                               [--window WINDOW] [--workspace WORKSPACE]
                               [--session SESSION_SELECTOR]
                               [--server SESSION_SERVER]

Manage one exact owned attachment; preserve conversations and reconcile uncertain effects.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --destination DESTINATION
                        Destination terminal session name or stable ID;
                        compatible backend/server required.
  --expected-destination EXPECTED_DESTINATION
                        Exact destination target; ordinary local CLI resolves
                        it.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --force               Explicitly override supported active/focused guards;
                        never overrides stale identity.
  --dry-run             Preview only; no terminal layout mutation.
  --receipt-id RECEIPT_ID
                        Exact retained receipt ID; conditional undo/restore
                        preserves newer human changes.
  --window WINDOW       Exact native window ID from tabs list/show (for
                        example @3); names are not identity pins.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs restore --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `destination` | yes | Destination account for a distinct source-preserving conversation copy. |
| `expected_destination` | yes | expected destination. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `force` | no | force. |
| `preview` | no | Show/save the frozen selection without native copying or daemon starts. |
| `receipt_id` | yes | Exact prior migration receipt for a qualified rollback. |
| `window` | yes | window. |
| `workspace` | yes | workspace. |

## tabs show

Show owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_show`).

```sh
codex-wake --wake-root ROOT tabs show --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs show [-h] [--arguments ARGUMENTS] [--json]
                            [--selector SELECTOR] [--workspace WORKSPACE]
                            [--session SESSION_SELECTOR]
                            [--server SESSION_SERVER]
                            [--socket-path SOCKET_PATH]
                            [--session-id SESSION_ID]
                            [--app-server APP_SERVER] [--timeout TIMEOUT]
                            [--bus-root BUS_ROOT]
                            [--operator-capability OPERATOR_CAPABILITY]
                            [--actor-capability ACTOR_CAPABILITY]
                            [--plan-id PLAN_ID] [--receipt-id RECEIPT_ID]

Show owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --selector SELECTOR   Window ID or unambiguous friendly name to inspect.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.
  --socket-path SOCKET_PATH
                        Legacy explicit tmux adapter option.
  --session-id SESSION_ID
                        Legacy explicit tmux adapter option.
  --app-server APP_SERVER
                        Legacy explicit tmux adapter option.
  --timeout TIMEOUT
  --bus-root BUS_ROOT
  --operator-capability OPERATOR_CAPABILITY
  --actor-capability ACTOR_CAPABILITY
  --plan-id PLAN_ID
  --receipt-id RECEIPT_ID

Examples:
  codex-wake --wake-root ROOT tabs show --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selector` | no | Account name or configured alias. |
| `workspace` | yes | workspace. |

## tabs undo

Undo owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_undo`).

```sh
codex-wake --wake-root ROOT tabs undo --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs undo [-h] [--arguments ARGUMENTS] [--json]
                            [--request-id REQUEST_ID]
                            [--expected-target EXPECTED_TARGET]
                            [--receipt-id RECEIPT_ID] [--workspace WORKSPACE]
                            [--session SESSION_SELECTOR]
                            [--server SESSION_SERVER]
                            [--socket-path SOCKET_PATH]
                            [--session-id SESSION_ID]
                            [--app-server APP_SERVER] [--timeout TIMEOUT]
                            [--bus-root BUS_ROOT]
                            [--operator-capability OPERATOR_CAPABILITY]
                            [--actor-capability ACTOR_CAPABILITY]

Undo owned attachments; automatic same-user discovery, exact identities, no input ownership implied.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --receipt-id RECEIPT_ID
                        Exact retained receipt ID; conditional undo/restore
                        preserves newer human changes.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.
  --socket-path SOCKET_PATH
                        Legacy explicit tmux adapter option.
  --session-id SESSION_ID
                        Legacy explicit tmux adapter option.
  --app-server APP_SERVER
                        Legacy explicit tmux adapter option.
  --timeout TIMEOUT
  --bus-root BUS_ROOT
  --operator-capability OPERATOR_CAPABILITY
  --actor-capability ACTOR_CAPABILITY

Examples:
  codex-wake --wake-root ROOT tabs undo --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `receipt_id` | yes | Exact prior migration receipt for a qualified rollback. |
| `workspace` | yes | workspace. |

## tabs view-delete

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_view_delete`).

```sh
codex-wake --wake-root ROOT tabs view-delete
```

### CLI help

```text
usage: codex-wake tabs view-delete [-h] [--arguments ARGUMENTS] [--json]
                                   [--request-id REQUEST_ID]
                                   [--expected-target EXPECTED_TARGET]
                                   [--name NAME]
                                   [view_name]

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

positional arguments:
  view_name             Saved logical view or group name.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --name NAME           Name.

Examples:
  codex-wake --wake-root ROOT tabs view-delete
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `name` | yes | name. |

## tabs view-evaluate

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_view_evaluate`).

```sh
codex-wake --wake-root ROOT tabs view-evaluate
```

### CLI help

```text
usage: codex-wake tabs view-evaluate [-h] [--arguments ARGUMENTS] [--json]
                                     [--name NAME]
                                     [view_name]

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

positional arguments:
  view_name             Saved logical view or group name.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --name NAME           Name.

Examples:
  codex-wake --wake-root ROOT tabs view-evaluate
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `name` | yes | name. |

## tabs view-list

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_view_list`).

```sh
codex-wake --wake-root ROOT tabs view-list
```

### CLI help

```text
usage: codex-wake tabs view-list [-h] [--arguments ARGUMENTS] [--json]

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.

Examples:
  codex-wake --wake-root ROOT tabs view-list
```

## tabs view-save

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_view_save`).

```sh
codex-wake --wake-root ROOT tabs view-save
```

### CLI help

```text
usage: codex-wake tabs view-save [-h] [--arguments ARGUMENTS] [--json]
                                 [--request-id REQUEST_ID]
                                 [--definition DEFINITION]
                                 [--expected-target EXPECTED_TARGET]
                                 [--name NAME] [--group-by GROUP_BY]
                                 [--sort-by SORT_BY] [--filter FILTERS]
                                 [--group GROUP]
                                 [view_name]

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

positional arguments:
  view_name             Saved logical view or group name.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --definition DEFINITION
                        Advanced saved view JSON; ordinary CLI offers
                        --filter/--group-by/--sort-by.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --name NAME           Name.
  --group-by GROUP_BY   Layered grouping trait; repeat in order.
  --sort-by SORT_BY     Layered sorting trait; repeat in order.
  --filter FILTERS      Read-only trait=value filter.
  --group GROUP         Saved named group restriction.

Examples:
  codex-wake --wake-root ROOT tabs view-save
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |
| `definition` | yes | definition. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `name` | yes | name. |

## tabs view-show

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_view_show`).

```sh
codex-wake --wake-root ROOT tabs view-show
```

### CLI help

```text
usage: codex-wake tabs view-show [-h] [--arguments ARGUMENTS] [--json]
                                 [--name NAME]
                                 [view_name]

Inspect or update logical tab group/view definitions without moving attachments.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

positional arguments:
  view_name             Saved logical view or group name.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --name NAME           Name.

Examples:
  codex-wake --wake-root ROOT tabs view-show
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `name` | yes | name. |

## tabs format status

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_format_status`).

```sh
codex-wake --wake-root ROOT tabs format-status --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs format-status [-h] [--arguments ARGUMENTS] [--json]
                                     [--scope {workspace,global}]
                                     [--workspace WORKSPACE]
                                     [--session SESSION_SELECTOR]
                                     [--server SESSION_SERVER]

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --scope {workspace,global}
                        Workspace display control (default) or global display
                        policy; global requires a matching formatting
                        authority grant.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs format-status --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `workspace` | no | workspace. |
| `scope` | no | scope. |

## tabs format inspect

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_format_inspect`).

```sh
codex-wake --wake-root ROOT tabs format-inspect --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs format-inspect [-h] [--arguments ARGUMENTS] [--json]
                                      [--scope {workspace,global}]
                                      [--workspace WORKSPACE]
                                      [--session SESSION_SELECTOR]
                                      [--server SESSION_SERVER]

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --scope {workspace,global}
                        Workspace display control (default) or global display
                        policy; global requires a matching formatting
                        authority grant.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs format-inspect --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `workspace` | no | workspace. |
| `scope` | no | scope. |

## tabs format enable

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_format_enable`).

```sh
codex-wake --wake-root ROOT tabs format-enable --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs format-enable [-h] [--arguments ARGUMENTS] [--json]
                                     [--request-id REQUEST_ID]
                                     [--expected-target EXPECTED_TARGET]
                                     [--scope {workspace,global}]
                                     [--workspace WORKSPACE]
                                     [--session SESSION_SELECTOR]
                                     [--server SESSION_SERVER]

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --scope {workspace,global}
                        Workspace display control (default) or global display
                        policy; global requires a matching formatting
                        authority grant.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs format-enable --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `workspace` | no | workspace. |
| `scope` | no | scope. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs format pause

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_format_pause`).

```sh
codex-wake --wake-root ROOT tabs format-pause --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs format-pause [-h] [--arguments ARGUMENTS] [--json]
                                    [--request-id REQUEST_ID]
                                    [--expected-target EXPECTED_TARGET]
                                    [--scope {workspace,global}]
                                    [--workspace WORKSPACE]
                                    [--session SESSION_SELECTOR]
                                    [--server SESSION_SERVER]

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --scope {workspace,global}
                        Workspace display control (default) or global display
                        policy; global requires a matching formatting
                        authority grant.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs format-pause --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `workspace` | no | workspace. |
| `scope` | no | scope. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs format resume

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_format_resume`).

```sh
codex-wake --wake-root ROOT tabs format-resume --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs format-resume [-h] [--arguments ARGUMENTS] [--json]
                                     [--request-id REQUEST_ID]
                                     [--expected-target EXPECTED_TARGET]
                                     [--scope {workspace,global}]
                                     [--workspace WORKSPACE]
                                     [--session SESSION_SELECTOR]
                                     [--server SESSION_SERVER]

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --scope {workspace,global}
                        Workspace display control (default) or global display
                        policy; global requires a matching formatting
                        authority grant.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs format-resume --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `workspace` | no | workspace. |
| `scope` | no | scope. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs format rollback

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_format_rollback`).

```sh
codex-wake --wake-root ROOT tabs format-rollback --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs format-rollback [-h] [--arguments ARGUMENTS] [--json]
                                       [--request-id REQUEST_ID]
                                       [--expected-target EXPECTED_TARGET]
                                       [--scope {workspace,global}]
                                       [--workspace WORKSPACE]
                                       [--session SESSION_SELECTOR]
                                       [--server SESSION_SERVER]

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --scope {workspace,global}
                        Workspace display control (default) or global display
                        policy; global requires a matching formatting
                        authority grant.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs format-rollback --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `workspace` | no | workspace. |
| `scope` | no | scope. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs format reenable

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_format_reenable`).

```sh
codex-wake --wake-root ROOT tabs format-reenable --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs format-reenable [-h] [--arguments ARGUMENTS] [--json]
                                       [--request-id REQUEST_ID]
                                       [--expected-target EXPECTED_TARGET]
                                       [--scope {workspace,global}]
                                       [--workspace WORKSPACE]
                                       [--session SESSION_SELECTOR]
                                       [--server SESSION_SERVER]

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --scope {workspace,global}
                        Workspace display control (default) or global display
                        policy; global requires a matching formatting
                        authority grant.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs format-reenable --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `workspace` | no | workspace. |
| `scope` | no | scope. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs format reset

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_format_reset`).

```sh
codex-wake --wake-root ROOT tabs format-reset --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs format-reset [-h] [--arguments ARGUMENTS] [--json]
                                    [--request-id REQUEST_ID]
                                    [--expected-target EXPECTED_TARGET]
                                    [--scope {workspace,global}]
                                    [--workspace WORKSPACE]
                                    [--session SESSION_SELECTOR]
                                    [--server SESSION_SERVER]

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --scope {workspace,global}
                        Workspace display control (default) or global display
                        policy; global requires a matching formatting
                        authority grant.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs format-reset --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `workspace` | no | workspace. |
| `scope` | no | scope. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs format configure

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_format_configure`).

```sh
codex-wake --wake-root ROOT tabs format-configure --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs format-configure [-h] [--arguments ARGUMENTS] [--json]
                                        [--request-id REQUEST_ID]
                                        [--expected-target EXPECTED_TARGET]
                                        [--policy POLICY]
                                        [--preset {slate,dusk,graphite,legacy}]
                                        [--scope {workspace,global}]
                                        [--workspace WORKSPACE]
                                        [--session SESSION_SELECTOR]
                                        [--server SESSION_SERVER]

Inspect or control reversible owned-tab decoration; rollback restores original settings; reenable retains the baseline.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --policy POLICY       Persistent display policy JSON.
  --preset {slate,dusk,graphite,legacy}
                        Named compact color palette; slate, dusk and graphite
                        omit repeated STALE text.
  --scope {workspace,global}
                        Workspace display control (default) or global display
                        policy; global requires a matching formatting
                        authority grant.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs format-configure --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `workspace` | no | workspace. |
| `scope` | no | scope. |
| `policy` | no | policy. |
| `preset` | no | preset. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs session list

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_session_list`).

```sh
codex-wake --wake-root ROOT tabs session-list
```

### CLI help

```text
usage: codex-wake tabs session-list [-h] [--arguments ARGUMENTS] [--json]
                                    [--server SERVER] [--session SESSION]

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --server SERVER       Terminal server qualifier when names are ambiguous.
  --session SESSION     Terminal session name or stable ID.

Examples:
  codex-wake --wake-root ROOT tabs session-list
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `session` | no | session. |
| `server` | no | server. |

## tabs session show

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_session_show`).

```sh
codex-wake --wake-root ROOT tabs session-show
```

### CLI help

```text
usage: codex-wake tabs session-show [-h] [--arguments ARGUMENTS] [--json]
                                    [--server SERVER] [--session SESSION]

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --server SERVER       Terminal server qualifier when names are ambiguous.
  --session SESSION     Terminal session name or stable ID.

Examples:
  codex-wake --wake-root ROOT tabs session-show
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `session` | yes | session. |
| `server` | no | server. |

## tabs session create

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_session_create`).

```sh
codex-wake --wake-root ROOT tabs session-create
```

### CLI help

```text
usage: codex-wake tabs session-create [-h] [--arguments ARGUMENTS] [--json]
                                      [--request-id REQUEST_ID]
                                      [--backend {tmux,byobu,psmux}]
                                      [--defaults DEFAULTS]
                                      [--expected-target EXPECTED_TARGET]
                                      [--name NAME] [--server SERVER]
                                      [--session SESSION] [--start]

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --backend {tmux,byobu,psmux}
                        Backend.
  --defaults DEFAULTS   Defaults.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --name NAME           Name.
  --server SERVER       Terminal server qualifier when names are ambiguous.
  --session SESSION     Terminal session name or stable ID.
  --start               Start.

Examples:
  codex-wake --wake-root ROOT tabs session-create
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `session` | no | session. |
| `server` | no | server. |
| `name` | yes | name. |
| `backend` | no | backend. |
| `start` | no | start. |
| `defaults` | no | defaults. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs session update

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_session_update`).

```sh
codex-wake --wake-root ROOT tabs session-update
```

### CLI help

```text
usage: codex-wake tabs session-update [-h] [--arguments ARGUMENTS] [--json]
                                      [--request-id REQUEST_ID]
                                      [--changes CHANGES]
                                      [--expected-target EXPECTED_TARGET]
                                      [--server SERVER] [--session SESSION]

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --changes CHANGES     Changes.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --server SERVER       Terminal server qualifier when names are ambiguous.
  --session SESSION     Terminal session name or stable ID.

Examples:
  codex-wake --wake-root ROOT tabs session-update
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `session` | yes | session. |
| `server` | no | server. |
| `changes` | yes | changes. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs session open

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_session_open`).

```sh
codex-wake --wake-root ROOT tabs session-open
```

### CLI help

```text
usage: codex-wake tabs session-open [-h] [--arguments ARGUMENTS] [--json]
                                    [--request-id REQUEST_ID]
                                    [--expected-target EXPECTED_TARGET]
                                    [--server SERVER] [--session SESSION]

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --server SERVER       Terminal server qualifier when names are ambiguous.
  --session SESSION     Terminal session name or stable ID.

Examples:
  codex-wake --wake-root ROOT tabs session-open
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `session` | yes | session. |
| `server` | no | server. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs session delete

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_session_delete`).

```sh
codex-wake --wake-root ROOT tabs session-delete
```

### CLI help

```text
usage: codex-wake tabs session-delete [-h] [--arguments ARGUMENTS] [--json]
                                      [--request-id REQUEST_ID]
                                      [--destination DESTINATION]
                                      [--expected-target EXPECTED_TARGET]
                                      [--plan-id PLAN_ID] [--server SERVER]
                                      [--session SESSION] [--terminate]

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --destination DESTINATION
                        Destination terminal session name or stable ID;
                        compatible backend/server required.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --plan-id PLAN_ID     Exact retained plan ID from preview.
  --server SERVER       Terminal server qualifier when names are ambiguous.
  --session SESSION     Terminal session name or stable ID.
  --terminate           Terminate.

Examples:
  codex-wake --wake-root ROOT tabs session-delete
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `session` | no | session. |
| `server` | no | server. |
| `destination` | no | Destination account for a distinct source-preserving conversation copy. |
| `terminate` | no | terminate. |
| `plan_id` | no | plan id. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs session ensure

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_session_ensure`).

```sh
codex-wake --wake-root ROOT tabs session-ensure
```

### CLI help

```text
usage: codex-wake tabs session-ensure [-h] [--arguments ARGUMENTS] [--json]
                                      [--request-id REQUEST_ID]
                                      [--backend {tmux,byobu,psmux}]
                                      [--defaults DEFAULTS]
                                      [--expected-target EXPECTED_TARGET]
                                      [--name NAME] [--server SERVER]
                                      [--session SESSION] [--start]

Manage named terminal sessions; empty definitions persist independently of running tabs.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --backend {tmux,byobu,psmux}
                        Backend.
  --defaults DEFAULTS   Defaults.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --name NAME           Name.
  --server SERVER       Terminal server qualifier when names are ambiguous.
  --session SESSION     Terminal session name or stable ID.
  --start               Start.

Examples:
  codex-wake --wake-root ROOT tabs session-ensure
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `session` | no | session. |
| `server` | no | server. |
| `name` | yes | name. |
| `backend` | no | backend. |
| `start` | no | start. |
| `defaults` | no | defaults. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs relocate preview

Preview and relocate whole tabs by selection; reconcile partial results and conditionally undo.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_relocate_preview`).

```sh
codex-wake --wake-root ROOT tabs relocate-preview
```

### CLI help

```text
usage: codex-wake tabs relocate-preview [-h] [--arguments ARGUMENTS] [--json]
                                        [--request-id REQUEST_ID]
                                        [--destination DESTINATION]
                                        [--expected-target EXPECTED_TARGET]
                                        [--plan-id PLAN_ID]
                                        [--receipt-id RECEIPT_ID]
                                        [--selection SELECTION]
                                        [--session SESSION]
                                        [--filter SELECTION_FILTERS]
                                        [--pattern SELECTION_PATTERNS]
                                        [--exclude SELECTION_EXCLUDES]
                                        [--group SELECTION_GROUPS]
                                        [--label SELECTION_LABELS]
                                        [--tab SELECTION_TABS]

Preview and relocate whole tabs by selection; reconcile partial results and conditionally undo.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --destination DESTINATION
                        Destination terminal session name or stable ID;
                        compatible backend/server required.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --plan-id PLAN_ID     Exact retained plan ID from preview.
  --receipt-id RECEIPT_ID
                        Exact retained receipt ID; conditional undo/restore
                        preserves newer human changes.
  --selection SELECTION
                        Selection.
  --session SESSION     Session.
  --filter SELECTION_FILTERS
                        Match TRAIT=VALUE; repeat to combine with AND.
  --pattern SELECTION_PATTERNS
                        Match TRAIT=GLOB.
  --exclude SELECTION_EXCLUDES
                        Exclude known TRAIT=VALUE matches.
  --group SELECTION_GROUPS
                        Select a saved named group.
  --label SELECTION_LABELS
                        Select a custom category label.
  --tab SELECTION_TABS  Select SESSION:@WINDOW; repeat for several tabs.

Examples:
  codex-wake --wake-root ROOT tabs relocate-preview
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `session` | no | session. |
| `destination` | yes | Destination account for a distinct source-preserving conversation copy. |
| `selection` | no | selection. |
| `plan_id` | no | plan id. |
| `receipt_id` | no | Exact prior migration receipt for a qualified rollback. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs relocate apply

Preview and relocate whole tabs by selection; reconcile partial results and conditionally undo.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_relocate_apply`).

```sh
codex-wake --wake-root ROOT tabs relocate-apply
```

### CLI help

```text
usage: codex-wake tabs relocate-apply [-h] [--arguments ARGUMENTS] [--json]
                                      [--request-id REQUEST_ID]
                                      [--destination DESTINATION]
                                      [--expected-target EXPECTED_TARGET]
                                      [--plan-id PLAN_ID]
                                      [--receipt-id RECEIPT_ID]
                                      [--selection SELECTION]
                                      [--session SESSION]
                                      [--filter SELECTION_FILTERS]
                                      [--pattern SELECTION_PATTERNS]
                                      [--exclude SELECTION_EXCLUDES]
                                      [--group SELECTION_GROUPS]
                                      [--label SELECTION_LABELS]
                                      [--tab SELECTION_TABS]

Preview and relocate whole tabs by selection; reconcile partial results and conditionally undo.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --destination DESTINATION
                        Destination terminal session name or stable ID;
                        compatible backend/server required.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --plan-id PLAN_ID     Exact retained plan ID from preview.
  --receipt-id RECEIPT_ID
                        Exact retained receipt ID; conditional undo/restore
                        preserves newer human changes.
  --selection SELECTION
                        Selection.
  --session SESSION     Session.
  --filter SELECTION_FILTERS
                        Match TRAIT=VALUE; repeat to combine with AND.
  --pattern SELECTION_PATTERNS
                        Match TRAIT=GLOB.
  --exclude SELECTION_EXCLUDES
                        Exclude known TRAIT=VALUE matches.
  --group SELECTION_GROUPS
                        Select a saved named group.
  --label SELECTION_LABELS
                        Select a custom category label.
  --tab SELECTION_TABS  Select SESSION:@WINDOW; repeat for several tabs.

Examples:
  codex-wake --wake-root ROOT tabs relocate-apply
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `session` | no | session. |
| `destination` | no | Destination account for a distinct source-preserving conversation copy. |
| `selection` | no | selection. |
| `plan_id` | no | plan id. |
| `receipt_id` | no | Exact prior migration receipt for a qualified rollback. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs relocate status

Preview and relocate whole tabs by selection; reconcile partial results and conditionally undo.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_relocate_status`).

```sh
codex-wake --wake-root ROOT tabs relocate-status
```

### CLI help

```text
usage: codex-wake tabs relocate-status [-h] [--arguments ARGUMENTS] [--json]
                                       [--destination DESTINATION]
                                       [--plan-id PLAN_ID]
                                       [--receipt-id RECEIPT_ID]
                                       [--selection SELECTION]
                                       [--session SESSION]
                                       [--filter SELECTION_FILTERS]
                                       [--pattern SELECTION_PATTERNS]
                                       [--exclude SELECTION_EXCLUDES]
                                       [--group SELECTION_GROUPS]
                                       [--label SELECTION_LABELS]
                                       [--tab SELECTION_TABS]

Preview and relocate whole tabs by selection; reconcile partial results and conditionally undo.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --destination DESTINATION
                        Destination terminal session name or stable ID;
                        compatible backend/server required.
  --plan-id PLAN_ID     Exact retained plan ID from preview.
  --receipt-id RECEIPT_ID
                        Exact retained receipt ID; conditional undo/restore
                        preserves newer human changes.
  --selection SELECTION
                        Selection.
  --session SESSION     Session.
  --filter SELECTION_FILTERS
                        Match TRAIT=VALUE; repeat to combine with AND.
  --pattern SELECTION_PATTERNS
                        Match TRAIT=GLOB.
  --exclude SELECTION_EXCLUDES
                        Exclude known TRAIT=VALUE matches.
  --group SELECTION_GROUPS
                        Select a saved named group.
  --label SELECTION_LABELS
                        Select a custom category label.
  --tab SELECTION_TABS  Select SESSION:@WINDOW; repeat for several tabs.

Examples:
  codex-wake --wake-root ROOT tabs relocate-status
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `session` | no | session. |
| `destination` | no | Destination account for a distinct source-preserving conversation copy. |
| `selection` | no | selection. |
| `plan_id` | no | plan id. |
| `receipt_id` | no | Exact prior migration receipt for a qualified rollback. |

## tabs relocate undo

Preview and relocate whole tabs by selection; reconcile partial results and conditionally undo.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_relocate_undo`).

```sh
codex-wake --wake-root ROOT tabs relocate-undo
```

### CLI help

```text
usage: codex-wake tabs relocate-undo [-h] [--arguments ARGUMENTS] [--json]
                                     [--request-id REQUEST_ID]
                                     [--destination DESTINATION]
                                     [--expected-target EXPECTED_TARGET]
                                     [--plan-id PLAN_ID]
                                     [--receipt-id RECEIPT_ID]
                                     [--selection SELECTION]
                                     [--session SESSION]
                                     [--filter SELECTION_FILTERS]
                                     [--pattern SELECTION_PATTERNS]
                                     [--exclude SELECTION_EXCLUDES]
                                     [--group SELECTION_GROUPS]
                                     [--label SELECTION_LABELS]
                                     [--tab SELECTION_TABS]

Preview and relocate whole tabs by selection; reconcile partial results and conditionally undo.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --destination DESTINATION
                        Destination terminal session name or stable ID;
                        compatible backend/server required.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --plan-id PLAN_ID     Exact retained plan ID from preview.
  --receipt-id RECEIPT_ID
                        Exact retained receipt ID; conditional undo/restore
                        preserves newer human changes.
  --selection SELECTION
                        Selection.
  --session SESSION     Session.
  --filter SELECTION_FILTERS
                        Match TRAIT=VALUE; repeat to combine with AND.
  --pattern SELECTION_PATTERNS
                        Match TRAIT=GLOB.
  --exclude SELECTION_EXCLUDES
                        Exclude known TRAIT=VALUE matches.
  --group SELECTION_GROUPS
                        Select a saved named group.
  --label SELECTION_LABELS
                        Select a custom category label.
  --tab SELECTION_TABS  Select SESSION:@WINDOW; repeat for several tabs.

Examples:
  codex-wake --wake-root ROOT tabs relocate-undo
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `session` | no | session. |
| `destination` | no | Destination account for a distinct source-preserving conversation copy. |
| `selection` | no | selection. |
| `plan_id` | no | plan id. |
| `receipt_id` | no | Exact prior migration receipt for a qualified rollback. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs route list

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_list`).

```sh
codex-wake --wake-root ROOT tabs route-list
```

### CLI help

```text
usage: codex-wake tabs route-list [-h] [--arguments ARGUMENTS] [--json]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.

Examples:
  codex-wake --wake-root ROOT tabs route-list
```

## tabs route show

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_show`).

```sh
codex-wake --wake-root ROOT tabs route-show
```

### CLI help

```text
usage: codex-wake tabs route-show [-h] [--arguments ARGUMENTS] [--json]
                                  [--name NAME] [--rule-id RULE_ID]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --name NAME           Name.
  --rule-id RULE_ID     Rule id.

Examples:
  codex-wake --wake-root ROOT tabs route-show
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `name` | no | name. |
| `rule_id` | no | rule id. |

## tabs route save

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_save`).

```sh
codex-wake --wake-root ROOT tabs route-save
```

### CLI help

```text
usage: codex-wake tabs route-save [-h] [--arguments ARGUMENTS] [--json]
                                  [--request-id REQUEST_ID]
                                  [--destination DESTINATION]
                                  [--expected-target EXPECTED_TARGET]
                                  [--name NAME] [--priority PRIORITY]
                                  [--rule-id RULE_ID] [--selection SELECTION]
                                  [--stability-seconds STABILITY_SECONDS]
                                  [--filter SELECTION_FILTERS]
                                  [--pattern SELECTION_PATTERNS]
                                  [--exclude SELECTION_EXCLUDES]
                                  [--group SELECTION_GROUPS]
                                  [--label SELECTION_LABELS]
                                  [--tab SELECTION_TABS]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --destination DESTINATION
                        Destination terminal session name or stable ID;
                        compatible backend/server required.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --name NAME           Name.
  --priority PRIORITY   Priority.
  --rule-id RULE_ID     Rule id.
  --selection SELECTION
                        Selection.
  --stability-seconds STABILITY_SECONDS
                        Stability seconds.
  --filter SELECTION_FILTERS
                        Match TRAIT=VALUE; repeat to combine with AND.
  --pattern SELECTION_PATTERNS
                        Match TRAIT=GLOB.
  --exclude SELECTION_EXCLUDES
                        Exclude known TRAIT=VALUE matches.
  --group SELECTION_GROUPS
                        Select a saved named group.
  --label SELECTION_LABELS
                        Select a custom category label.
  --tab SELECTION_TABS  Select SESSION:@WINDOW; repeat for several tabs.

Examples:
  codex-wake --wake-root ROOT tabs route-save
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `name` | yes | name. |
| `rule_id` | no | rule id. |
| `destination` | yes | Destination account for a distinct source-preserving conversation copy. |
| `selection` | yes | selection. |
| `priority` | no | priority. |
| `stability_seconds` | no | stability seconds. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs route delete

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_delete`).

```sh
codex-wake --wake-root ROOT tabs route-delete
```

### CLI help

```text
usage: codex-wake tabs route-delete [-h] [--arguments ARGUMENTS] [--json]
                                    [--request-id REQUEST_ID]
                                    [--expected-target EXPECTED_TARGET]
                                    [--name NAME] [--rule-id RULE_ID]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --name NAME           Name.
  --rule-id RULE_ID     Rule id.

Examples:
  codex-wake --wake-root ROOT tabs route-delete
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `name` | no | name. |
| `rule_id` | no | rule id. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs route enable

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_enable`).

```sh
codex-wake --wake-root ROOT tabs route-enable
```

### CLI help

```text
usage: codex-wake tabs route-enable [-h] [--arguments ARGUMENTS] [--json]
                                    [--request-id REQUEST_ID]
                                    [--expected-target EXPECTED_TARGET]
                                    [--include-existing] [--name NAME]
                                    [--rule-id RULE_ID]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --include-existing    Include existing.
  --name NAME           Name.
  --rule-id RULE_ID     Rule id.

Examples:
  codex-wake --wake-root ROOT tabs route-enable
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `name` | no | name. |
| `rule_id` | no | rule id. |
| `include_existing` | no | include existing. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs route pause

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_pause`).

```sh
codex-wake --wake-root ROOT tabs route-pause
```

### CLI help

```text
usage: codex-wake tabs route-pause [-h] [--arguments ARGUMENTS] [--json]
                                   [--request-id REQUEST_ID]
                                   [--expected-target EXPECTED_TARGET]
                                   [--name NAME] [--rule-id RULE_ID]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --name NAME           Name.
  --rule-id RULE_ID     Rule id.

Examples:
  codex-wake --wake-root ROOT tabs route-pause
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `name` | no | name. |
| `rule_id` | no | rule id. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs route tick

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_tick`).

```sh
codex-wake --wake-root ROOT tabs route-tick
```

### CLI help

```text
usage: codex-wake tabs route-tick [-h] [--arguments ARGUMENTS] [--json]
                                  [--request-id REQUEST_ID]
                                  [--expected-target EXPECTED_TARGET]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.

Examples:
  codex-wake --wake-root ROOT tabs route-tick
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs route status

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_status`).

```sh
codex-wake --wake-root ROOT tabs route-status
```

### CLI help

```text
usage: codex-wake tabs route-status [-h] [--arguments ARGUMENTS] [--json]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.

Examples:
  codex-wake --wake-root ROOT tabs route-status
```

## tabs route hold

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_hold`).

```sh
codex-wake --wake-root ROOT tabs route-hold
```

### CLI help

```text
usage: codex-wake tabs route-hold [-h] [--arguments ARGUMENTS] [--json]
                                  [--request-id REQUEST_ID]
                                  [--expected-target EXPECTED_TARGET]
                                  [--reason REASON] [--selection SELECTION]
                                  [--filter SELECTION_FILTERS]
                                  [--pattern SELECTION_PATTERNS]
                                  [--exclude SELECTION_EXCLUDES]
                                  [--group SELECTION_GROUPS]
                                  [--label SELECTION_LABELS]
                                  [--tab SELECTION_TABS]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --reason REASON       Reason.
  --selection SELECTION
                        Selection.
  --filter SELECTION_FILTERS
                        Match TRAIT=VALUE; repeat to combine with AND.
  --pattern SELECTION_PATTERNS
                        Match TRAIT=GLOB.
  --exclude SELECTION_EXCLUDES
                        Exclude known TRAIT=VALUE matches.
  --group SELECTION_GROUPS
                        Select a saved named group.
  --label SELECTION_LABELS
                        Select a custom category label.
  --tab SELECTION_TABS  Select SESSION:@WINDOW; repeat for several tabs.

Examples:
  codex-wake --wake-root ROOT tabs route-hold
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selection` | yes | selection. |
| `reason` | no | reason. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs route resume

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_resume`).

```sh
codex-wake --wake-root ROOT tabs route-resume
```

### CLI help

```text
usage: codex-wake tabs route-resume [-h] [--arguments ARGUMENTS] [--json]
                                    [--request-id REQUEST_ID]
                                    [--expected-target EXPECTED_TARGET]
                                    [--reason REASON] [--selection SELECTION]
                                    [--filter SELECTION_FILTERS]
                                    [--pattern SELECTION_PATTERNS]
                                    [--exclude SELECTION_EXCLUDES]
                                    [--group SELECTION_GROUPS]
                                    [--label SELECTION_LABELS]
                                    [--tab SELECTION_TABS]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --reason REASON       Reason.
  --selection SELECTION
                        Selection.
  --filter SELECTION_FILTERS
                        Match TRAIT=VALUE; repeat to combine with AND.
  --pattern SELECTION_PATTERNS
                        Match TRAIT=GLOB.
  --exclude SELECTION_EXCLUDES
                        Exclude known TRAIT=VALUE matches.
  --group SELECTION_GROUPS
                        Select a saved named group.
  --label SELECTION_LABELS
                        Select a custom category label.
  --tab SELECTION_TABS  Select SESSION:@WINDOW; repeat for several tabs.

Examples:
  codex-wake --wake-root ROOT tabs route-resume
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selection` | yes | selection. |
| `reason` | no | reason. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs route pin

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_pin`).

```sh
codex-wake --wake-root ROOT tabs route-pin
```

### CLI help

```text
usage: codex-wake tabs route-pin [-h] [--arguments ARGUMENTS] [--json]
                                 [--request-id REQUEST_ID]
                                 [--expected-target EXPECTED_TARGET]
                                 [--reason REASON] [--selection SELECTION]
                                 [--filter SELECTION_FILTERS]
                                 [--pattern SELECTION_PATTERNS]
                                 [--exclude SELECTION_EXCLUDES]
                                 [--group SELECTION_GROUPS]
                                 [--label SELECTION_LABELS]
                                 [--tab SELECTION_TABS]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --reason REASON       Reason.
  --selection SELECTION
                        Selection.
  --filter SELECTION_FILTERS
                        Match TRAIT=VALUE; repeat to combine with AND.
  --pattern SELECTION_PATTERNS
                        Match TRAIT=GLOB.
  --exclude SELECTION_EXCLUDES
                        Exclude known TRAIT=VALUE matches.
  --group SELECTION_GROUPS
                        Select a saved named group.
  --label SELECTION_LABELS
                        Select a custom category label.
  --tab SELECTION_TABS  Select SESSION:@WINDOW; repeat for several tabs.

Examples:
  codex-wake --wake-root ROOT tabs route-pin
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selection` | yes | selection. |
| `reason` | no | reason. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs route unpin

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_route_unpin`).

```sh
codex-wake --wake-root ROOT tabs route-unpin
```

### CLI help

```text
usage: codex-wake tabs route-unpin [-h] [--arguments ARGUMENTS] [--json]
                                   [--request-id REQUEST_ID]
                                   [--expected-target EXPECTED_TARGET]
                                   [--reason REASON] [--selection SELECTION]
                                   [--filter SELECTION_FILTERS]
                                   [--pattern SELECTION_PATTERNS]
                                   [--exclude SELECTION_EXCLUDES]
                                   [--group SELECTION_GROUPS]
                                   [--label SELECTION_LABELS]
                                   [--tab SELECTION_TABS]

Manage opt-in stable routing rules, explicit pins and manual placement holds.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --reason REASON       Reason.
  --selection SELECTION
                        Selection.
  --filter SELECTION_FILTERS
                        Match TRAIT=VALUE; repeat to combine with AND.
  --pattern SELECTION_PATTERNS
                        Match TRAIT=GLOB.
  --exclude SELECTION_EXCLUDES
                        Exclude known TRAIT=VALUE matches.
  --group SELECTION_GROUPS
                        Select a saved named group.
  --label SELECTION_LABELS
                        Select a custom category label.
  --tab SELECTION_TABS  Select SESSION:@WINDOW; repeat for several tabs.

Examples:
  codex-wake --wake-root ROOT tabs route-unpin
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `selection` | yes | selection. |
| `reason` | no | reason. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs family register

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_family_register`).

```sh
codex-wake --wake-root ROOT tabs family-register
```

### CLI help

```text
usage: codex-wake tabs family-register [-h] [--arguments ARGUMENTS] [--json]
                                       [--request-id REQUEST_ID]
                                       [--bot-id BOT_ID]
                                       [--expected-target EXPECTED_TARGET]
                                       [--name NAME]
                                       [--parent-bot-id PARENT_BOT_ID]
                                       [--scope-kind SCOPE_KIND]
                                       [--scope-ref SCOPE_REF] [--temporary]

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --bot-id BOT_ID       Bot id.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --name NAME           Name.
  --parent-bot-id PARENT_BOT_ID
                        Parent bot id.
  --scope-kind SCOPE_KIND
                        Scope kind.
  --scope-ref SCOPE_REF
                        Scope ref.
  --temporary           Temporary.

Examples:
  codex-wake --wake-root ROOT tabs family-register
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `bot_id` | yes | bot id. |
| `parent_bot_id` | no | parent bot id. |
| `name` | no | name. |
| `scope_kind` | no | scope kind. |
| `scope_ref` | no | scope ref. |
| `temporary` | no | temporary. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs family list

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_family_list`).

```sh
codex-wake --wake-root ROOT tabs family-list
```

### CLI help

```text
usage: codex-wake tabs family-list [-h] [--arguments ARGUMENTS] [--json]
                                   [--root-bot-id ROOT_BOT_ID]

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --root-bot-id ROOT_BOT_ID
                        Root bot id.

Examples:
  codex-wake --wake-root ROOT tabs family-list
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `root_bot_id` | no | root bot id. |

## tabs family show

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_family_show`).

```sh
codex-wake --wake-root ROOT tabs family-show
```

### CLI help

```text
usage: codex-wake tabs family-show [-h] [--arguments ARGUMENTS] [--json]
                                   [--bot-id BOT_ID]

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --bot-id BOT_ID       Bot id.

Examples:
  codex-wake --wake-root ROOT tabs family-show
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `bot_id` | yes | bot id. |

## tabs family bind

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_family_bind`).

```sh
codex-wake --wake-root ROOT tabs family-bind --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs family-bind [-h] [--arguments ARGUMENTS] [--json]
                                   [--request-id REQUEST_ID] [--bot-id BOT_ID]
                                   [--client-id CLIENT_ID]
                                   [--environment ENVIRONMENT]
                                   [--expected-target EXPECTED_TARGET]
                                   [--pane-id PANE_ID] [--thread-id THREAD_ID]
                                   [--window-id WINDOW_ID]
                                   [--workspace WORKSPACE]
                                   [--session SESSION_SELECTOR]
                                   [--server SESSION_SERVER]

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --bot-id BOT_ID       Bot id.
  --client-id CLIENT_ID
                        Client id.
  --environment ENVIRONMENT
                        Environment.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --pane-id PANE_ID     Pane id.
  --thread-id THREAD_ID
                        Thread id.
  --window-id WINDOW_ID
                        Window id.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).
  --server SESSION_SERVER
                        Terminal server qualifier.

Examples:
  codex-wake --wake-root ROOT tabs family-bind --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `bot_id` | yes | bot id. |
| `client_id` | yes | client id. |
| `environment` | no | environment. |
| `workspace` | yes | workspace. |
| `window_id` | yes | window id. |
| `pane_id` | yes | pane id. |
| `thread_id` | no | Native saved conversation identifier in its owning account. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs family open

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_family_open`).

```sh
codex-wake --wake-root ROOT tabs family-open --workspace WORKSPACE
```

### CLI help

```text
usage: codex-wake tabs family-open [-h] [--arguments ARGUMENTS] [--json]
                                   [--request-id REQUEST_ID] [--argv ARGV]
                                   [--bot-id BOT_ID] [--client-id CLIENT_ID]
                                   [--cwd CWD] [--environment ENVIRONMENT]
                                   [--expected-target EXPECTED_TARGET]
                                   [--placement {workers,adjacent}]
                                   [--profile PROFILE] [--server SERVER]
                                   [--thread-id THREAD_ID]
                                   [--workspace WORKSPACE]
                                   [--session SESSION_SELECTOR]

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --argv ARGV           Argv.
  --bot-id BOT_ID       Bot id.
  --client-id CLIENT_ID
                        Client id.
  --cwd CWD             Cwd.
  --environment ENVIRONMENT
                        Environment.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --placement {workers,adjacent}
                        Placement.
  --profile PROFILE     Profile.
  --server SERVER       Server.
  --thread-id THREAD_ID
                        Thread id.
  --workspace WORKSPACE
                        Workspace ID or unique label from tabs list; same-user
                        CLI can select its only workspace.
  --session SESSION_SELECTOR
                        Terminal session name or stable ID (alias for
                        --workspace).

Examples:
  codex-wake --wake-root ROOT tabs family-open --workspace WORKSPACE
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `bot_id` | yes | bot id. |
| `client_id` | yes | client id. |
| `environment` | no | environment. |
| `workspace` | no | workspace. |
| `server` | no | server. |
| `profile` | no | profile. |
| `cwd` | no | cwd. |
| `thread_id` | no | Native saved conversation identifier in its owning account. |
| `argv` | no | argv. |
| `placement` | no | placement. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs family accept

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_family_accept`).

```sh
codex-wake --wake-root ROOT tabs family-accept
```

### CLI help

```text
usage: codex-wake tabs family-accept [-h] [--arguments ARGUMENTS] [--json]
                                     [--request-id REQUEST_ID]
                                     [--bot-id BOT_ID] [--client-id CLIENT_ID]
                                     [--environment ENVIRONMENT]
                                     [--expected-target EXPECTED_TARGET]
                                     [--parent-bot-id PARENT_BOT_ID]
                                     [--result-id RESULT_ID] [--successful]

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --bot-id BOT_ID       Bot id.
  --client-id CLIENT_ID
                        Client id.
  --environment ENVIRONMENT
                        Environment.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --parent-bot-id PARENT_BOT_ID
                        Parent bot id.
  --result-id RESULT_ID
                        Result id.
  --successful          Successful.

Examples:
  codex-wake --wake-root ROOT tabs family-accept
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `bot_id` | yes | bot id. |
| `client_id` | yes | client id. |
| `environment` | no | environment. |
| `parent_bot_id` | yes | parent bot id. |
| `result_id` | yes | result id. |
| `successful` | yes | successful. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs family adopt

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_family_adopt`).

```sh
codex-wake --wake-root ROOT tabs family-adopt
```

### CLI help

```text
usage: codex-wake tabs family-adopt [-h] [--arguments ARGUMENTS] [--json]
                                    [--request-id REQUEST_ID]
                                    [--bot-id BOT_ID] [--client-id CLIENT_ID]
                                    [--environment ENVIRONMENT]
                                    [--expected-target EXPECTED_TARGET]

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --bot-id BOT_ID       Bot id.
  --client-id CLIENT_ID
                        Client id.
  --environment ENVIRONMENT
                        Environment.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.

Examples:
  codex-wake --wake-root ROOT tabs family-adopt
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `bot_id` | yes | bot id. |
| `client_id` | yes | client id. |
| `environment` | no | environment. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs family focus

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

Transport: CLI / API / OAuth MCP / native MCP (`wake_tabs_family_focus`).

```sh
codex-wake --wake-root ROOT tabs family-focus
```

### CLI help

```text
usage: codex-wake tabs family-focus [-h] [--arguments ARGUMENTS] [--json]
                                    [--request-id REQUEST_ID]
                                    [--bot-id BOT_ID] [--client-id CLIENT_ID]
                                    [--environment ENVIRONMENT]
                                    [--expected-target EXPECTED_TARGET]
                                    [--relation {self,parent,root}]

Organize durable bot families and exact client tabs; identity does not grant account or input authority.

Same-user local CLI resolves exact generations and retains durable request identity; API/MCP use explicit pins and authenticated scopes. Uncertain effects are never replayed. Grok/SSH exact health and unsupported backend continuity remain explicit unknown/held. Raw capture and input retain separate privacy/custody checks; observation grants no input access.

options:
  -h, --help            show this help message and exit
  --arguments ARGUMENTS
                        Advanced operation JSON; typed flags fill only omitted
                        fields.
  --json                Emit structured results.
  --request-id REQUEST_ID
                        Stable intent ID; reuse only for identical inputs.
                        Retrieve with tabs result.
  --bot-id BOT_ID       Bot id.
  --client-id CLIENT_ID
                        Client id.
  --environment ENVIRONMENT
                        Environment.
  --expected-target EXPECTED_TARGET
                        Exact current target object; ordinary local CLI
                        resolves it, remote callers must supply it.
  --relation {self,parent,root}
                        Relation.

Examples:
  codex-wake --wake-root ROOT tabs family-focus
```

| Argument | Required remotely | Meaning |
|---|---|---|
| `bot_id` | yes | bot id. |
| `client_id` | yes | client id. |
| `environment` | no | environment. |
| `relation` | no | relation. |
| `expected_target` | yes | Exact target JSON from the corresponding resolve, list or status command; replacement is refused. |
| `_request` | yes | Durable request metadata: operation_id, idempotency_key, correlation_id, binding and exact target. |

## tabs result

Read a retained local UID-owned tab request after disconnect or workspace closure.

Local CLI shortcut for authenticated common operations.result; no live workspace or new effect.

Transport: Local human CLI only.

```sh
codex-wake --wake-root ROOT tabs result --request-id REQUEST
```

### CLI help

```text
usage: codex-wake tabs result [-h] --request-id REQUEST_ID [--json]

Read a retained local UID-owned tab request after disconnect or workspace closure.

Local CLI shortcut for authenticated common operations.result; no live workspace or new effect.

options:
  -h, --help            show this help message and exit
  --request-id REQUEST_ID
  --json

Examples:
  codex-wake --wake-root ROOT tabs result --request-id REQUEST
```

## tabs startup enable

Manage the owned per-controller tab-monitor systemd user unit.

Local operator only; enable/disable affects only this root-specific user service. No agent or terminal launch.

Transport: Local human CLI only.

```sh
codex-wake --wake-root ROOT tabs startup enable
```

## tabs startup disable

Manage the owned per-controller tab-monitor systemd user unit.

Local operator only; enable/disable affects only this root-specific user service. No agent or terminal launch.

Transport: Local human CLI only.

```sh
codex-wake --wake-root ROOT tabs startup disable
```

## tabs startup status

Manage the owned per-controller tab-monitor systemd user unit.

Local operator only; enable/disable affects only this root-specific user service. No agent or terminal launch.

Transport: Local human CLI only.

```sh
codex-wake --wake-root ROOT tabs startup status
```


## Local session controller

See [workflow](local-session-control.md) and generated [transport contract](local-controller-contract.json).

| CLI | API operation | Local MCP |
|---|---|---|
| `control create` | `local.create` | `wake_local_create` |
| `control load` | `local.load` | `wake_local_load` |
| `control prompt` | `local.prompt` | `wake_local_prompt` |
| `control output` | `local.output` | `wake_local_output` |
| `control result` | `local.result` | `wake_local_result` |
| `control cancel` | `local.cancel` | `wake_local_cancel` |
| `control list` | `local.list` | `wake_local_list` |
| `control resolve` | `local.resolve` | `wake_local_resolve` |
| `control health` | `local.health` | `wake_local_health` |
| `control slash list` | `local.slash.list` | `wake_control_slash_list` |
| `control slash run` | `local.slash.run` | `wake_control_slash_run` |
| `control slash result` | `local.slash.result` | `wake_control_slash_result` |
| `control slash respond` | `local.slash.respond` | `wake_control_slash_respond` |
| `control slash cancel` | `local.slash.cancel` | `wake_control_slash_cancel` |
| `self-limits show` | `local.self_limits.show` | `wake_self_limits_show` |
| `self-limits set` | `local.self_limits.set` | `wake_self_limits_set` |
| `control observe` | `local.observe` | `wake_local_observe` |
| `control observation output` | `local.observation.output` | `wake_local_observation_output` |
| `control observation result` | `local.observation.result` | `wake_local_observation_result` |
| `control observation cancel` | `local.observation.cancel` | `wake_local_observation_cancel` |
| `governor status` | `local.governor.status` | `wake_governor_status` |
| `governor activate` | `local.governor.activate` | `wake_governor_activate` |
| `governor extend` | `local.governor.extend` | `wake_governor_extend` |
| `governor reset` | `local.governor.reset` | `wake_governor_reset` |
| `governor disable` | `local.governor.disable` | `wake_governor_disable` |
| `governor resume` | `local.governor.resume` | `wake_governor_resume` |
| `governor advisory` | `local.governor.advisory` | `wake_governor_advisory` |
| `environment snapshot` | `environment.snapshot` | `wake_environment_snapshot` |
| `environment children` | `environment.children` | `wake_environment_children` |
| `control wakes schedules register` | `wakes.schedules.register` | `wake_wakes_schedules_register` |
| `control wakes schedules list` | `wakes.schedules.list` | `wake_wakes_schedules_list` |
| `control wakes schedules show` | `wakes.schedules.show` | `wake_wakes_schedules_show` |
| `control wakes schedules revise` | `wakes.schedules.revise` | `wake_wakes_schedules_revise` |
| `control wakes schedules cancel` | `wakes.schedules.cancel` | `wake_wakes_schedules_cancel` |
| `control wakes intents after` | `wakes.intents.after` | `wake_wakes_intents_after` |
| `control wakes intents at` | `wakes.intents.at` | `wake_wakes_intents_at` |
| `control wakes intents file` | `wakes.intents.file` | `wake_wakes_intents_file` |
| `environment panes capture` | `environment.panes.capture` | `wake_environment_panes_capture` |
| `environment panes observe` | `environment.panes.observe` | `wake_environment_panes_observe` |
| `environment panes output` | `environment.panes.output` | `wake_environment_panes_output` |
| `environment panes paste` | `environment.panes.paste` | `wake_environment_panes_paste` |
| `environment panes keys` | `environment.panes.keys` | `wake_environment_panes_keys` |
| `environment conversations input submit` | `environment.conversations.input.submit` | `wake_environment_conversations_input_submit` |
| `environment conversations input result` | `environment.conversations.input.result` | `wake_environment_conversations_input_result` |
| `environment conversations presentation background` | `environment.conversations.presentation.background` | `wake_environment_conversations_presentation_background` |
| `environment conversations presentation foreground` | `environment.conversations.presentation.foreground` | `wake_environment_conversations_presentation_foreground` |
| `control connectors grants create` | `connectors.grants.create` | `wake_connectors_grants_create` |
| `control connectors grants list` | `connectors.grants.list` | `wake_connectors_grants_list` |
| `control connectors grants show` | `connectors.grants.show` | `wake_connectors_grants_show` |
| `control connectors grants revoke` | `connectors.grants.revoke` | `wake_connectors_grants_revoke` |
| `control programs bulk start` | `programs.bulk.start` | `wake_programs_bulk_start` |
| `control programs bulk status` | `programs.bulk.status` | `wake_programs_bulk_status` |
| `control programs bulk result` | `programs.bulk.result` | `wake_programs_bulk_result` |
| `control programs bulk advance` | `programs.bulk.advance` | `wake_programs_bulk_advance` |
| `control programs bulk reconcile` | `programs.bulk.reconcile` | `wake_programs_bulk_reconcile` |
| `control programs bulk cancel` | `programs.bulk.cancel` | `wake_programs_bulk_cancel` |
| `environment conversations create` | `environment.conversations.create` | `wake_environment_conversations_create` |
| `environment conversations load` | `environment.conversations.load` | `wake_environment_conversations_load` |
| `environment conversations prompt` | `environment.conversations.prompt` | `wake_environment_conversations_prompt` |
| `environment conversations output` | `environment.conversations.output` | `wake_environment_conversations_output` |
| `environment conversations result` | `environment.conversations.result` | `wake_environment_conversations_result` |
| `environment conversations cancel` | `environment.conversations.cancel` | `wake_environment_conversations_cancel` |
| `environment conversations list` | `environment.conversations.list` | `wake_environment_conversations_list` |
| `environment conversations resolve` | `environment.conversations.resolve` | `wake_environment_conversations_resolve` |
| `environment conversations health` | `environment.conversations.health` | `wake_environment_conversations_health` |
| `environment conversations slash list` | `environment.conversations.slash.list` | `wake_environment_conversations_slash_list` |
| `environment conversations slash run` | `environment.conversations.slash.run` | `wake_environment_conversations_slash_run` |
| `environment conversations slash result` | `environment.conversations.slash.result` | `wake_environment_conversations_slash_result` |
| `environment conversations slash respond` | `environment.conversations.slash.respond` | `wake_environment_conversations_slash_respond` |
| `environment conversations slash cancel` | `environment.conversations.slash.cancel` | `wake_environment_conversations_slash_cancel` |
| `control programs limits show` | `programs.limits.show` | `wake_programs_limits_show` |
| `control programs limits set` | `programs.limits.set` | `wake_programs_limits_set` |
| `environment conversations observe` | `environment.conversations.observe` | `wake_environment_conversations_observe` |
| `environment conversations observation output` | `environment.conversations.observation.output` | `wake_environment_conversations_observation_output` |
| `environment conversations observation result` | `environment.conversations.observation.result` | `wake_environment_conversations_observation_result` |
| `environment conversations observation cancel` | `environment.conversations.observation.cancel` | `wake_environment_conversations_observation_cancel` |
| `control programs governor status` | `programs.governor.status` | `wake_programs_governor_status` |
| `control programs governor activate` | `programs.governor.activate` | `wake_programs_governor_activate` |
| `control programs governor extend` | `programs.governor.extend` | `wake_programs_governor_extend` |
| `control programs governor reset` | `programs.governor.reset` | `wake_programs_governor_reset` |
| `control programs governor disable` | `programs.governor.disable` | `wake_programs_governor_disable` |
| `control programs governor resume` | `programs.governor.resume` | `wake_programs_governor_resume` |
| `control programs governor advisory` | `programs.governor.advisory` | `wake_programs_governor_advisory` |
