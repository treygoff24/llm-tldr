# Agent Hook Expansion Implementation Plan

Date: 2026-05-20
Status: Approved v4 for implementation
Spec: `docs/plans/2026-05-20-agent-hook-expansion-spec.md`
Research appendix: `docs/dev-notes/agent_hook_surfaces_2026-05-20.md`

## Goal

Implement the reviewed hook expansion spec in phases, using Codex as orchestrator/reviewer and delegated agents for bounded implementation and review lanes. The implementation must expand stable Codex and Droid hook support, add an OpenCode adapter, keep Cursor hooks experimental, and preserve user config safety.

## Orchestration model

- Codex owns architecture, integration, final review, final verification, and git operations.
- Delegated agents do bounded codebase exploration, isolated implementation slices, and second-opinion review.
- Preferred delegate model: `delegate cursor work`.
- Fallback models: `delegate droid glm work`, `delegate droid grok work`, `delegate droid gemini work`.
- Use `safe` mode for review/exploration. Use `work` mode only with explicit owned files and verification commands.
- Review every delegated diff before integration; never delegate git commit/push.
- Execute phases sequentially overnight unless an explicit sub-slice has disjoint write ownership and no dependency on an unfinished earlier phase.

## Clean-code constraints

- Keep hook behavior modules small and single-purpose.
- Prefer declarative client capability tables over scattered client conditionals.
- Keep policy rules conservative and named by intent.
- Do not install no-op hooks by default.
- Preserve current public commands and behavior.
- Document only external client quirks and schema hazards; avoid narration comments.

## Delegation boundaries

- Phase 0 contract fixtures/tests are orchestrator-owned or strictly serial. No parallel worker may edit `tests/test_hooks_runtime.py` after Phase 0 until Phase 0 is merged.
- Phase 1 runtime worker owns `tldr/hooks/runtime.py`, `tldr/hooks/runner.py`, `tldr/hooks/prompt.py`, `tldr/hooks/permission.py`, `tldr/hooks/tool.py`, `tldr/cli.py` for `hooks run` choices only, `tests/test_hooks_prompt.py`, and `tests/test_hooks_permission.py`.
- Phase 1 integration owner, not a parallel worker, must extend shared runtime tests in `tests/test_hooks_runtime.py` and CLI shape tests in `tests/test_current_cli_hook_shapes.py` immediately after reviewing Phase 1 runtime changes and before Phase 1 is considered merged.
- After each delegated runtime or installer diff, the orchestrator runs the relevant focused contract gate before the next worker begins: runtime gate is `python -m pytest tests/test_hooks_runtime.py tests/test_hooks_prompt.py tests/test_hooks_permission.py tests/test_current_cli_hook_shapes.py`; installer gate is `python -m pytest tests/test_hook_installer.py tests/test_readme_examples.py`; OpenCode gate is `python -m pytest tests/test_opencode_adapter.py tests/test_hook_installer.py`.
- Phase 2 installer worker owns JSON hook installer changes in `tldr/hook_installer.py`, install/doctor CLI changes in `tldr/cli.py`, and installer tests in `tests/test_hook_installer.py` / `tests/test_readme_examples.py`.
- Phase 3 OpenCode worker owns `tldr/hooks/opencode_adapter.py` and `tests/test_opencode_adapter.py`. The orchestrator owns the small integration call site in `tldr/hook_installer.py` after Phase 2 lands.
- Phase 4 smoke/docs worker owns only `README.md`, `docs/TLDR.md`, `scripts/smoke_current_cli_hooks.py`, and docs/smoke tests after runtime/installer phases land.
- Shared files are integration-owner only unless a worker is explicitly assigned a non-overlapping line range.
- Treat `docs/dev-notes/agent_hook_surfaces_2026-05-20.md` as read-only during implementation. Only the orchestrator may append dated new observations, and only after a local runtime smoke changes a fixture assumption.

## Phase 0: fixtures and contract scaffolding

Owned files:

- `tests/fixtures/hooks/codex_session_start.json`
- `tests/fixtures/hooks/codex_pretooluse_apply_patch.json`
- `tests/fixtures/hooks/codex_permission_request_bash.json`
- `tests/fixtures/hooks/codex_posttooluse_apply_patch.json`
- `tests/fixtures/hooks/codex_user_prompt_submit.json`
- `tests/fixtures/hooks/codex_stop.json`
- `tests/fixtures/hooks/droid_session_start.json`
- `tests/fixtures/hooks/droid_pretooluse_read.json`
- `tests/fixtures/hooks/droid_pretooluse_edit.json`
- `tests/fixtures/hooks/droid_pretooluse_create.json`
- `tests/fixtures/hooks/droid_pretooluse_apply_patch.json`
- `tests/fixtures/hooks/droid_pretooluse_execute.json`
- `tests/fixtures/hooks/droid_posttooluse_create.json`
- `tests/fixtures/hooks/droid_user_prompt_submit.json`
- `tests/fixtures/hooks/droid_precompact_manual.json`
- `tests/fixtures/hooks/droid_stop.json`
- `tests/fixtures/hooks/droid_session_end.json`
- `tests/fixtures/hooks/opencode_session_created.json`
- `tests/fixtures/hooks/opencode_tool_execute_before_edit.json`
- `tests/fixtures/hooks/opencode_tool_execute_after_edit.json`
- `tests/fixtures/hooks/opencode_permission_asked.json`
- `tests/fixtures/hooks/opencode_file_edited.json`
- `tests/test_hooks_runtime.py`

Tasks:

1. Add the golden fixture JSON payloads named above.
2. Add parametrized fixture tests asserting each fixture normalizes to expected `HookEvent`: canonical event name, client, tool name, cwd, session_id, tool input/result, and compact raw metadata.
3. Add expected output assertions for Codex and Droid renderers.
4. Add runner/CLI exit-behavior tests for no-op, context, and blocking events where TLDR controls exit behavior.
5. Add negative render tests for every Codex and Droid event proving forbidden fields are absent.
6. Add Droid `Stop`/`SubagentStop` loop-prevention tests: when `stop_hook_active` is truthy, TLDR must emit `{}` and take no decision action even if a future stop gate is configured.
7. Add OpenCode fixture normalization tests even though callback behavior is adapter-tested in Phase 3.
8. Add a Droid renderer assertion table:
   - SessionStart emits `hookSpecificOutput.hookEventName` and `additionalContext` only when context exists.
   - PreToolUse denial emits `hookSpecificOutput.permissionDecision=deny` and `permissionDecisionReason`; no generic `decision`.
   - PostToolUse diagnostics emit `hookSpecificOutput.additionalContext` and do not block.
   - UserPromptSubmit prompt guard emits `decision=block` plus redacted `reason`; context uses `hookSpecificOutput.additionalContext`.
   - Stop/SubagentStop no-op emits `{}`.
   - Stop/SubagentStop with `stop_hook_active=true` emits `{}` and never returns `decision=block`.
   - PreCompact context emits `hookSpecificOutput.additionalContext` only behind opt-in behavior.

Verification:

- `python -m pytest tests/test_hooks_runtime.py`

## Phase 1: shared runtime and Codex 0.131 expansion

Owned files:

- `tldr/hooks/runtime.py`
- `tldr/hooks/runner.py`
- `tldr/hooks/prompt.py`
- `tldr/hooks/permission.py`
- `tldr/hooks/tool.py`
- `tldr/cli.py` for `hooks run` event/client choices only
- `tests/test_hooks_prompt.py`
- `tests/test_hooks_permission.py`
- Integration-owner additions to `tests/test_hooks_runtime.py` and `tests/test_current_cli_hook_shapes.py`

Tasks:

1. Expand recognized client names for stable clients and adapters: `claude`, `codex`, `droid`, `factory`, `opencode`, `generic`; keep Cursor experimental behind explicit paths rather than a stable default.
2. Add event aliases for new internal commands.
3. Expand `tldr hooks run` CLI choices for all recognized internal events and stable/adapter clients so runtime dispatch is executable before installer work begins.
4. Extend `HookResponse` minimally for:
   - permission-deny reason,
   - prompt/stop block decision reason,
   - Codex PermissionRequest behavior,
   - explicit optional hook process exit-code metadata if a client/event must use exit-code blocking instead of JSON decisions.
5. Define and test runner exit behavior explicitly: documented JSON-control clients/events return exit `0` with JSON decisions; simple exit-code fallback returns `2` only for events that cannot safely consume JSON decisions. Do not leave `run_hook_from_stdin` behavior implicit.
6. Implement event-aware Codex rendering exactly from the spec output matrix.
7. Implement prompt-secret guard with high-confidence detectors and redacted messages.
8. Implement high-confidence destructive shell/tool guard.
9. Wire runner dispatch for `user-prompt-submit`, `permission-request`, `pre-tool`, `post-tool`, `stop`, `session-end`, `notification`, `subagent-start`, `subagent-stop`, `pre-compact`.
10. Promote Droid `stop_hook_active` from raw payload into explicit stop/subagent-stop handling so future gates cannot loop; add no-op behavior while no stop gate is enabled. Also check `TLDR_STOP_HOOK_ACTIVE=1` as a process-level reentrancy fuse for any future nested hook subprocesses.
11. `tests/test_hooks_prompt.py` must cover:
   - blocks provider-shaped OpenAI/Anthropic/GitHub/Slack/AWS-looking fake keys,
   - blocks PEM private key blocks,
   - blocks `.env` multi-line credential pastes with recognized key names and high-entropy values,
   - does not block generic `password`, placeholders, docs snippets, or short tokens,
   - never echoes the secret or surrounding value in the blocking reason.
12. `tests/test_hooks_permission.py` must cover:
   - blocks `rm -rf /`, `sudo rm -rf ~`, repo-root recursive forced deletion, and disk erase/format commands,
   - allows package-manager, test, git, build, and harmless read commands,
   - uses shell-aware tokenization enough to avoid naive substring failures.

Verification:

- `python -m pytest tests/test_hooks_runtime.py tests/test_hooks_prompt.py tests/test_hooks_permission.py tests/test_current_cli_hook_shapes.py`

## Phase 2: installer and Droid/Factory stable hooks

Owned files:

- `tldr/hook_installer.py`
- `tldr/cli.py` for install/doctor options only
- `tests/test_hook_installer.py`
- `tests/test_readme_examples.py`

Tasks:

1. Add CLI choices/aliases for `droid` and `factory`.
2. Add opt-in install flags:
   - `--enable-prompt-guard`
   - `--enable-tool-guard`
   - `--enable-compact-context`
   - Cursor hook work must stay disabled until a future local fixture proves the runtime shape.
3. Add Codex default and opt-in hook groups.
4. Add Droid default and opt-in hook groups with Droid matcher names.
5. Keep Cursor install blocked until a local fixture proves hook config path, payload, and output schema.
6. Add invalid JSON no-mutation behavior and atomic writes for JSON config files.
7. Extend doctor report with stable clients and experimental/adapter caveats.
8. Preserve existing config file mode after atomic writes.
9. Reject managed/enterprise policy paths or managed-policy markers without mutation. Initial managed path markers: `/Library/Application Support/`, `/etc/`, and other system-wide config roots; initial JSON markers: `enterprise_managed: true`, `managed: true`, or a top-level `managedPolicy` object.
10. Assert invalid JSON leaves bytes, mtime, and file mode unchanged.
11. Assert dry-run and write-mode action reports list exact added/removed TLDR-owned groups.
12. Extend TLDR-owned hook detection to all recognized internal event names and verify stale replacement for new prompt/tool/compact groups.
13. Add backup/unrelated-preservation tests for Claude, Codex, and Droid/Factory JSON hook config writes.
14. Add tests that `tldr hooks install cursor` fails while hook status is `experimental_unverified`.
15. Add doctor tests that Cursor hook status is `experimental_unverified` unless a local fixture/runtime proof is recorded.

Verification:

- `python -m pytest tests/test_hook_installer.py tests/test_readme_examples.py`

## Phase 3: OpenCode generated adapter

Owned files:

- `tldr/hooks/opencode_adapter.py`
- `tests/test_opencode_adapter.py`
- `tldr/hook_installer.py` only for orchestrator-owned integration call site after worker output is reviewed

Tasks:

1. Generate adapter source from a dedicated Python module, not inline inside `hook_installer.py`.
2. Generate a dependency-free `tldr-hooks.js` adapter for global OpenCode plugin installation.
3. Use absolute resolved TLDR command path in generated adapter.
4. Implement adapter callbacks only for default events:
   - `session.created`
   - `tool.execute.before`
   - `tool.execute.after`
   - `file.edited`
5. Use a concrete adapter subprocess timeout of 1500 ms by default; expose it as a generated constant for future tuning.
6. Keep `permission.asked` and compaction callbacks opt-in only.
7. Generate async Promise-returning callback handlers using asynchronous child-process execution where OpenCode supports async callbacks; avoid blocking OpenCode's event loop with sync subprocess calls.
8. Unit-test event normalization for every default callback.
9. Unit-test empty stdout, `{}`, JSON parse failure, subprocess failure, and timeout as no-op.
10. Unit-test `permission.asked` and compaction are absent by default and present only with opt-in flags.
11. Unit-test generated source contains no external dependency imports and no project install path.
12. Unit-test generated source contains the resolved absolute TLDR command path and never a relative `tldr` invocation.
13. Add a Node.js syntax/runtime smoke test when `node` is available: load the generated adapter against a mock OpenCode callback payload and verify it parses and no-ops correctly. If Node is unavailable, skip with an explicit reason.
14. Add orchestrator-owned installer integration tests for OpenCode adapter dry-run/write behavior, backups, and unrelated existing plugin-file preservation after the adapter module is reviewed.
15. Do not implement OpenCode prompt guard until a direct prompt event is proven.

Verification:

- `python -m pytest tests/test_opencode_adapter.py tests/test_hook_installer.py`

## Phase 4: docs, smoke safety, and Cursor proof gate

Owned files:

- `README.md`
- `docs/TLDR.md`
- `scripts/smoke_current_cli_hooks.py`
- `tests/test_current_cli_hook_shapes.py` only for smoke-related additions after runtime tests land

Tasks:

1. Update hook integration matrix and examples.
2. Document stable vs experimental surfaces.
3. Extend smoke script with temp configs/adapters for Claude, Codex, Droid, and OpenCode.
4. Keep Cursor runtime smoke disabled until a local fixture/runtime proof exists.
5. If local Cursor hook smoke cannot prove path, payload, and output schema, do not implement Cursor hook rendering; document Cursor rules/MCP fallback only.
6. If local proof is added, add fixture-backed tests before emitting anything other than `{}` for Cursor.
7. Fingerprint real config paths before/after but never mutate them in smoke.

Verification:

- `python -m pytest tests/test_current_cli_hook_shapes.py`
- `python scripts/smoke_current_cli_hooks.py`

## Phase 5: review, hardening, and ship

Tasks:

1. Inspect delegated diffs and simplify/refactor where needed.
2. Run focused tests after each phase.
3. Run full suite once focused tests are green: `python -m pytest`.
4. Run code review subagent plus delegate model reviews:
   - Cursor Composer code review if available.
   - Gemini 3.5 Flash code review.
   - GLM or Grok review if Composer/Gemini fail or surface material findings.
5. Fix all actionable review findings.
6. Commit and push only after the working tree is clean and tests pass or any residual external-runtime limits are explicitly documented.

Verification:

- `python -m pytest`
- `python scripts/smoke_current_cli_hooks.py`
- `git status --short`

## Review gates before implementation

1. Plan reviewer approves the spec.
2. Plan reviewer approves this implementation plan.
3. Delegate second opinions from Gemini 3.5 Flash, GLM, and Grok review both spec and plan.
4. Incorporate actionable feedback before coding.

## Risks and mitigations

- Cursor hook docs are not stable enough: keep Cursor hook install disabled/experimental until a local fixture proves the runtime shape.
- OpenCode uses JS plugins, not command hooks: generate a tiny dependency-free adapter and test its static contract.
- Codex unsupported output fields can fail open/noisy: event-aware renderer with negative tests.
- Stop hooks can create loops: not installed by default; future gates must check stop-active flags.
- Config mutation risk: temp configs, fingerprints, atomic writes, backups, invalid JSON no-mutation behavior.
