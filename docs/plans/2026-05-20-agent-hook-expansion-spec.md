# Agent Hook Expansion Spec

Date: 2026-05-20
Status: Draft v2 for adversarial review
Repo: `/Users/treygoff/Code/llm-tldr`
Research appendix: `docs/dev-notes/agent_hook_surfaces_2026-05-20.md`

## Goal

Expand TLDR's package-owned hook runtime from Claude/Codex edit-context support into a conservative multi-agent hook layer for Codex CLI, Factory Droid, OpenCode, and experimental Cursor hooks. TLDR should add value at lifecycle points where it can safely inject context, protect prompts/tools, or update diagnostics without surprising users, mutating configs unsafely, or installing hooks that intentionally do nothing.

## Non-goals

- Do not install telemetry-only or no-op hooks by default.
- Do not mutate real user configs during tests or smoke scripts.
- Do not depend on unstable transcript formats as a primary contract.
- Do not treat hook policy as a complete security boundary; these hooks are guardrails.
- Do not block stop/subagent-stop by default.
- Do not implement Cursor hook support as stable until the installed Cursor runtime is locally proven.
- Do not generate repo-tracked OpenCode plugin files containing machine-specific absolute TLDR paths.

## Current baseline

TLDR currently supports:

- `tldr hooks run session-start|pre-read|pre-edit|post-edit --client claude|codex|generic`.
- Claude install into `~/.claude/settings.json` with SessionStart, PreToolUse(Read/Edit/Write/MultiEdit/Update), and PostToolUse(Edit/Write/MultiEdit/Update).
- Codex install into `~/.codex/hooks.json` with SessionStart plus apply_patch-backed PreToolUse/PostToolUse edit support.
- Safe config merge behavior that removes stale TLDR-owned groups and leaves unrelated config intact.
- Temp-config smoke coverage in `scripts/smoke_current_cli_hooks.py`.

## Confirmed external hook surfaces

### Codex CLI 0.131.0

Primary docs: <https://developers.openai.com/codex/hooks>. Local version checked: `codex-cli 0.131.0`.

Stable events for this implementation:

- `SessionStart`
- `PreToolUse`
- `PermissionRequest`
- `PostToolUse`
- `UserPromptSubmit`
- `Stop`

Default-installed TLDR hooks:

| Event | Matcher | Default? | TLDR behavior |
| --- | --- | --- | --- |
| `SessionStart` | `startup|resume|clear` | Yes | Existing daemon start + background warm + context injection. |
| `PreToolUse` | `apply_patch|Edit|Write` | Yes | Existing edit context for apply_patch-backed edits. |
| `PostToolUse` | `apply_patch|Edit|Write` | Yes | Existing diagnostics + daemon notify for edited files. |
| `UserPromptSubmit` | none | No, opt-in `--enable-prompt-guard` | Prompt-secret guard and tiny workspace context if useful. |
| `PreToolUse` | `Bash` | No, opt-in `--enable-tool-guard` | High-confidence destructive command guard only. |
| `PermissionRequest` | `Bash|apply_patch|Edit|Write|mcp__.*` | No, opt-in `--enable-tool-guard` | Deny high-confidence destructive escalations; abstain otherwise. |
| `PostToolUse` | `Bash|mcp__.*` | No | Recognized for future diagnostics but not installed by default. |
| `Stop` | none | No | Recognized no-op; future opt-in diagnostic continuation gate only. |

Codex constraints:

- `PreToolUse`, `PermissionRequest`, `PostToolUse`, `UserPromptSubmit`, and `Stop` run at turn scope.
- `PreToolUse` and `PostToolUse` do not intercept every possible shell/tool path. TLDR policy is advisory guardrail behavior, not a sandbox.
- `UserPromptSubmit` and `Stop` ignore matchers.
- `Stop` expects JSON stdout or no output; TLDR must never emit plain text for Codex Stop.
- Codex project-local hooks require trusted project config; TLDR global installer should not assume project hooks are active.

### Factory Droid / Factory CLI 0.129.0

Primary docs: <https://docs.factory.ai/reference/hooks-reference> and <https://docs.factory.ai/factory-cli/configuration/settings>. Local version checked: `droid 0.129.0`. No local `factory` binary was present; `factory` is only a TLDR alias for Droid hook config.

Stable events for this implementation:

- `PreToolUse`
- `PostToolUse`
- `Notification`
- `UserPromptSubmit`
- `Stop`
- `SubagentStop`
- `PreCompact`
- `SessionStart`
- `SessionEnd`

Default-installed TLDR hooks:

| Event | Matcher | Default? | TLDR behavior |
| --- | --- | --- | --- |
| `SessionStart` | `startup|resume|clear|compact` | Yes | Daemon start + background warm + context injection. |
| `PreToolUse` | `Read` | Yes | Read/navigation context where payloads expose file paths. |
| `PreToolUse` | `Edit|Create|ApplyPatch` | Yes | Edit context where payloads expose paths or patches. |
| `PostToolUse` | `Edit|Create|ApplyPatch` | Yes | Diagnostics + daemon notify. |
| `UserPromptSubmit` | none | No, opt-in `--enable-prompt-guard` | Prompt-secret guard and tiny workspace context. |
| `PreToolUse` | `Execute` | No, opt-in `--enable-tool-guard` | High-confidence destructive command guard. Do not use Claude/Codex `Bash` matcher names. |
| `PreCompact` | `manual|auto` | No, opt-in `--enable-compact-context` | Compact TLDR workspace summary if available within budget. |
| `Notification` | none | No | Recognized no-op/telemetry only. |
| `Stop` | none | No | Recognized no-op; future opt-in continuation gate only. |
| `SubagentStop` | none | No | Recognized no-op; future opt-in subagent continuation gate only. |
| `SessionEnd` | none | No | Future telemetry flush/cleanup only; not default. |

Droid constraints:

- Use Droid matcher names: `Execute`, `Read`, `Edit`, `Create`, `ApplyPatch`, not `Bash`/`Write`.
- Unknown MCP-like Droid tool names are experimental; install no MCP matcher until local payloads prove the matcher/tool names.
- Hooks may use `$FACTORY_PROJECT_DIR`, but global TLDR installs should use absolute resolved TLDR command paths.
- Droid JSON output and exit-code behavior vary by event; renderer must be event-specific.

### Cursor CLI and Cursor app — experimental only until hook runtime is locally proven

Primary docs checked: <https://docs.cursor.com/en/cli/using>, <https://docs.cursor.com/en/cli/reference/configuration>, <https://docs.cursor.com/en/context>, Cursor Marketplace hook/plugin pages. Local versions checked: `cursor-agent 2026.05.16-0338208`, Cursor app CLI `3.5.11` build `4830a52b... arm64`.

Confirmed stable Cursor surfaces:

- Cursor CLI and IDE share rules/MCP context.
- CLI reads `.cursor/rules`, root `AGENTS.md`, and root `CLAUDE.md`.
- CLI config uses `~/.cursor/cli-config.json` globally and `<project>/.cursor/cli.json` project-locally.
- Marketplace plugins can expose hooks, but official docs checked do not provide a full stable hook reference comparable to Codex or Factory.

Cursor TLDR stance:

- Treat Cursor hooks as experimental.
- `tldr hooks install cursor` remains disabled until a local fixture proves the exact hook config path, payload, and output schema. There is no default write path.
- `doctor_report()` may report Cursor rules/MCP readiness by default, but hook status must be `experimental_unverified` unless a local smoke has proven the exact hook path, payload, and output schema.
- Do not claim Claude/Droid-compatible output for Cursor unless a fixture or local smoke proves the event accepts that exact shape.
- Provide docs for stable Cursor rules fallback rather than default hook install.

### OpenCode 1.14.29

Primary docs: <https://opencode.ai/docs/config/> and <https://opencode.ai/docs/plugins/>. Local version checked: `opencode 1.14.29`.

OpenCode uses JS/TS plugin callbacks, not Claude-style shell hook JSON. TLDR must implement a generated JS plugin adapter, not a JSON hook merger.

Default-installed TLDR callbacks for a global OpenCode adapter:

| OpenCode event | Default? | TLDR mapping |
| --- | --- | --- |
| `session.created` | Yes | Normalize to `session-start`. |
| `tool.execute.before` | Yes | Normalize read/edit/shell tool payloads to `pre-read`, `pre-edit`, or `pre-tool` when recognized. |
| `tool.execute.after` | Yes | Normalize edit/file results to `post-edit`; otherwise no-op. |
| `permission.asked` | No, opt-in `--enable-tool-guard` | Normalize to `permission-request` when the callback can block/deny safely. |
| `file.edited` | Yes | Notify daemon/dirty flag. |
| `session.idle` | No | Recognized no-op; not installed by default. |
| `experimental.session.compacting` | No, opt-in `--enable-compact-context` | Add compact TLDR workspace summary if supported and fast. |
| Message/todo/tui/server/installation events | No | Recognized only in docs; no default adapter callback. |

OpenCode adapter contract:

- Generated file path for global install: `~/.config/opencode/plugins/tldr-hooks.js`.
- Project install is disabled until a separate spec decides tracked vs local-only semantics.
- Adapter must be plain JS with no external dependencies.
- Adapter shells out to the resolved absolute TLDR command with a short timeout.
- Adapter sends normalized JSON payloads containing `hook_event_name`, `cwd`, `session_id` if known, `tool_name`, `tool_input`, `tool_response`, and raw metadata under `raw` if compact.
- Adapter parses TLDR stdout as JSON. Empty stdout or `{}` means no-op.
- Parse errors, process failures, and timeouts log through OpenCode logging if available and otherwise no-op; they must not interrupt OpenCode.
- Blocking behavior is allowed only for callback/event mappings with fixture-tested support. If support is not proven, adapter must no-op rather than throw.
- OpenCode has no documented direct `UserPromptSubmit` plugin event in the current list; do not promise OpenCode prompt-secret blocking until a prompt event is proven locally.

## Internal TLDR event taxonomy

Preserve current public commands and add aliases.

Existing:

- `session-start`
- `pre-read`
- `pre-edit`
- `post-edit`

New recognized commands:

- `user-prompt-submit`
- `permission-request`
- `pre-tool`
- `post-tool`
- `stop`
- `session-end`
- `notification`
- `subagent-start`
- `subagent-stop`
- `pre-compact`

Native spellings must alias to the same commands where applicable: `UserPromptSubmit`, `PermissionRequest`, `Stop`, `SessionEnd`, `Notification`, `SubagentStart`, `SubagentStop`, `PreCompact`.

## Output rendering matrix

Each implemented client/event pair must have golden tests covering accepted stdout shape, text handling, blocking mechanism, no-op representation, and forbidden fields.

### Codex output matrix

| Event | Context/no-op output | Blocking/decision output | Forbidden TLDR fields |
| --- | --- | --- | --- |
| `SessionStart` | `{}` or `hookSpecificOutput.additionalContext` | `continue:false` only if future explicit stop reason exists; not used by TLDR MVP | none beyond docs |
| `PreToolUse` | `{}` or `hookSpecificOutput.additionalContext` | `hookSpecificOutput.permissionDecision="deny"` + `permissionDecisionReason`; no exit-code reliance in Python renderer | `continue`, `stopReason`, `suppressOutput`, `updatedPermissions`, unrelated decision fields |
| `PermissionRequest` | `{}` to abstain | `hookSpecificOutput.decision.behavior="deny"` with message; optional future allow only with explicit opt-in | `updatedInput`, `updatedPermissions`, `interrupt`, generic `permissionDecision` |
| `PostToolUse` | `{}` or `hookSpecificOutput.additionalContext` | Future `decision:"block"` only after explicit tests; MVP diagnostics context only | unsupported `updatedMCPToolOutput`, `suppressOutput` |
| `UserPromptSubmit` | `{}` or `hookSpecificOutput.additionalContext` | `decision:"block"` + redacted `reason` | secret echo, unsupported tool fields |
| `Stop` | `{}` only in MVP | Future `decision:"block"` + reason behind explicit opt-in | plain text stdout, secret echo |

### Droid/Factory output matrix

| Event | Context/no-op output | Blocking/decision output | Notes |
| --- | --- | --- | --- |
| `SessionStart` | `{}` or `hookSpecificOutput.additionalContext`; stdout context allowed | no blocking in MVP | Source matcher includes `compact`. |
| `PreToolUse` | `{}` or `systemMessage`/context where docs allow | `hookSpecificOutput.permissionDecision="deny"` + reason for high-confidence guards | `permissionDecision:"ask"` is supported by Droid but TLDR will not emit it initially. |
| `PostToolUse` | `{}` or `hookSpecificOutput.additionalContext` | `decision:"block"` only if future diagnostics feedback loop is enabled | Diagnostics context should not block by default. |
| `UserPromptSubmit` | `{}` or `hookSpecificOutput.additionalContext` | `decision:"block"` + redacted reason | Blocks prompt and erases prompt from context. |
| `Stop`/`SubagentStop` | `{}` | Future `decision:"block"` + reason behind explicit opt-in | Must avoid loops by checking `stop_hook_active`. |
| `PreCompact` | `{}` or compact context where supported | no blocking | Must fit latency/token budget. |
| `SessionEnd`/`Notification` | `{}` | no blocking | Not installed by default. |

### Cursor output matrix

No stable default renderer. Every Cursor event must remain experimental and require an observed fixture before TLDR emits anything other than `{}`.

### OpenCode output matrix

OpenCode does not consume stdout JSON directly. The generated adapter is responsible for interpreting TLDR JSON and mutating callback output only for fixture-tested callbacks. Empty stdout, `{}`, process failure, parse failure, or timeout must no-op.

## Installer requirements

- Separate "runtime recognizes event" from "installer enables event by default".
- Default installs include only value-positive hooks listed as default above.
- Opt-in flags:
  - `--enable-prompt-guard`
  - `--enable-tool-guard`
  - `--enable-compact-context`
  - Future Cursor hook work must add a separate explicit proof gate after local runtime fixtures exist.
- `default_config_path(client)` supports stable JSON hook clients `claude`, `codex`, and `factory`/`droid` only.
- Cursor install refuses to write until local runtime proof exists; `doctor_report()` can still report `experimental_unverified`.
- OpenCode uses plugin install paths, not JSON hook config paths.
- `doctor_report()` reports stable clients by default. Cursor/OpenCode appear under an `experimental` or `adapters` section with explicit caveats and observed version metadata.
- JSON hook clients must:
  - parse before writing and fail without mutation on invalid JSON,
  - write atomically via temp file + rename,
  - preserve existing file mode where possible,
  - create timestamped backups before mutation,
  - never edit enterprise/managed policy files,
  - report exact added/removed TLDR-owned groups in dry-run and write mode.
- Existing stale TLDR hook replacement and unrelated settings preservation remain mandatory.
- OpenCode global adapter install must use an absolute resolved TLDR command and must not require external npm/Bun dependencies beyond OpenCode's plugin loader.

## Prompt and tool policy requirements

Prompt-secret guard:

- Initial blockers are allowlisted high-confidence detectors only:
  - OpenAI/Anthropic/GitHub/Slack/AWS-style API keys using provider-shaped regexes.
  - PEM private key blocks.
  - `.env`-style multi-line credential pastes with at least one recognized secret key name and high-entropy value.
- Do not block generic words like `password`, placeholders, docs snippets, or short tokens.
- Blocking messages must name only the class, e.g. `possible OpenAI API key`; never echo the secret or surrounding value.
- Tests must cover false positives and false negatives.

Shell/tool guard:

- Use shell-aware tokenization where feasible.
- Block only high-confidence destructive commands:
  - recursive forced deletion of `/`, `$HOME`, `~`, or repository root;
  - disk erase/format commands;
  - destructive `sudo rm -rf` variants.
- Do not block normal package-manager, test, git, build, or harmless read commands.
- Policy hooks are guardrails, not security guarantees.

## Latency and noise requirements

- No-op/policy hooks target p95 under 150 ms and must hard-timeout under 2 seconds unless the client has a stricter default.
- Context hooks target p95 under 750 ms and must truncate aggressively.
- Hooks must be quiet by default and return `{}` on unknown payloads.
- Hooks must never trigger semantic model downloads or prompt for heavy setup.

## Documentation requirements

Update:

- `README.md` and `docs/TLDR.md` hook sections.
- `docs/dev-notes/agent_hook_surfaces_2026-05-20.md` research appendix.
- `docs/plans/2026-05-20-agent-hook-expansion-implementation.md` implementation plan after separate review approval.

Docs must clearly label Cursor hooks as experimental and OpenCode as a generated adapter rather than JSON hook config.

## Verification requirements

- Golden fixture tests for each supported client/event pair:
  - input payload fixture,
  - expected normalized `HookEvent`,
  - expected rendered stdout JSON or empty output,
  - expected exit behavior where TLDR controls it.
- Negative render tests proving unsupported fields are not emitted for Codex `PreToolUse`, Codex `PermissionRequest`, Codex `Stop`, and each Droid event.
- Installer tests for:
  - Codex default hooks and opt-in prompt/tool hooks,
  - Droid default hooks and opt-in prompt/tool/compact hooks,
  - Cursor explicit-config experimental guard,
  - OpenCode adapter dry-run/write behavior,
  - invalid JSON no-mutation behavior,
  - backups and unrelated config preservation.
- Smoke script must continue fingerprinting real `~/.claude/settings.json` and `~/.codex/hooks.json` before/after. Extend to include `~/.factory/settings.json` and `~/.config/opencode/plugins/tldr-hooks.js` fingerprints when present.
- Cursor hook fingerprints remain out of scope until a local runtime proof exists.
- Optional runtime smokes are version-gated:
  - `--with-codex-runtime`
  - `--with-droid-runtime`
  - `--with-opencode-runtime`
  - Cursor install refusal / experimental-unverified status
- Runtime smokes must never mutate real user config; they must use temp config/plugin dirs or explicit test config paths.
- Run focused hook tests before the full Python test suite.

## Implementation phases required

- Phase 0: research appendix + golden fixtures.
- Phase 1: Codex 0.131 expansion.
- Phase 2: Droid/Factory stable hooks.
- Phase 3: OpenCode generated adapter.
- Phase 4: Cursor experimental hooks only after local proof.
