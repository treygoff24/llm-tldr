# Pre-Edit Hook Model Confusion — Fix Plan (v3, all reviews folded)

**Date:** 2026-05-23
**Branch:** `fix/pre-edit-hook-model-confusion`
**Owner:** Trey
**Status:** v3 — reconciled review feedback from `plan-reviewer`, `delegate droid qwen37 safe`, `delegate codex safe`

## What changed v1 → v3

v1 had two structural bugs:
1. **Wrong target function.** Pre-edit text comes from `_format_edit_structure` (`tldr/hooks/file_context.py:411`), NOT `format_nav_map`. v1's Fix 2 would have done nothing on the edit path.
2. **Telemetry regression.** Switching `clean_no_diagnostics` from `noop` to `ok` silently breaks `scripts/tldr_outcome_model.py:143` and three related snapshot tests.

v3 also folds in three additional findings from `delegate codex safe`:
3. **Second edit-mode header emitter** at `file_context.py:572-574` for non-code files (config/YAML/SQL). v2 missed it; v3 covers it.
4. **`tests/test_current_cli_hook_shapes.py:34-50`** asserts Codex apply_patch CLI shape. Fix 4 changes that shape → update the test.
5. **"Edit applied cleanly" overclaims.** The clean-confirmation path in `post_edit.py` also fires when language is unknown or `get_diagnostics` raises — not strictly "clean," just "no diagnostics surfaced." Use the more precise wording.

v3 also tightens the in-block phrasing per Codex's specific suggestions: "Before editing:" → "Pre-edit snapshot only.", "after edit, diagnostics hook will run" → "After the tool completes, TLDR may report diagnostics."

## Problem (unchanged)

Delegated subagents (Cursor Composer, Codex, Droid/Qwen/GLM, etc.) repeatedly report that the llm-tldr `PreToolUse` hook **stopped or reverted their edits**. The hook never does this — `build_pre_edit_response` returns context-only (`ok` with `additional_context`), never `permission_decision="deny"`, never `decision="block"`, never `updated_input`. The edit always applies. Models hallucinate the block.

## Root-cause theory (unchanged)

1. **The pre-edit edit context is a snapshot of the file BEFORE the edit applies.** Models see their freshly-added symbol absent from `Functions:` / `Classes:` and conclude the edit didn't land.
2. **`Likely target symbol: foo`** (`edit.py:78-80`) names the symbol the model just wrote, then implicitly contrasts it against a file that doesn't contain it.
3. **No PostToolUse confirmation on clean edits.** `post_edit.py:135-136` returns `noop("clean_no_diagnostics")` → silence after a confusing pre-edit message.
4. **Framing is ambiguous for non-Claude models.** `[TLDR edit context: ...]` reads as "the system replaced my edit with context." The token "TLDR" connotes "summary that elides detail" outside this project.
5. **Codex `apply_patch` already shows the diff inline.** Pre-edit context is redundant.
6. **Trailing line "after edit, diagnostics hook will run"** (`file_context.py:434`) is misleading — diagnostics currently only emit when there are errors, so the model expects a follow-up that never comes.
7. **Trailing line "Read specific lines with offset=N limit=M."** (in `format_nav_map`) is read-mode advice that may leak into edit-mode framing perception if it ever fires there.

## Goal & non-goals (unchanged)

Eliminate the "hook reverted my edit" hallucination across diverse model populations. Don't change extraction logic, hook protocol surface, or project branding.

## Scope (files we touch)

- `tldr/hooks/edit.py` (Fix 1, Fix 4, Fix 5)
- `tldr/hooks/file_context.py` (Fix 2 — `_format_edit_structure` + relabel "Functions:" → "Pre-existing functions:")
- `tldr/hooks/post_edit.py` (Fix 3)
- `scripts/tldr_outcome_model.py` (Fix 3 telemetry preservation)
- `tests/test_hooks_edit.py` (Fix 1, Fix 2, Fix 4)
- `tests/test_hooks_post_edit.py` (Fix 3)
- `tests/test_tldr_outcome_model.py` (Fix 3 — `clean_no_diagnostics` semantics)
- `tests/test_render_tldr_outcome_report.py` (Fix 3 — same)
- `tests/test_current_cli_hook_shapes.py` — update Codex apply_patch CLI shape test (L34-50) to reflect skip
- `tests/test_hooks_runtime.py` — verify renderers still wrap correctly (no fixture changes expected — these tests assert `parse_hook_event`, not full pre_edit responses)
- (New) `tests/test_hook_framing_perception.py` — framing-token tests

## Spec

### Fix 1 — Rephrase `Likely target symbol`

**File:** `tldr/hooks/edit.py:78-80`

**Current:**
```python
if symbol:
    context += f"\n\nLikely target symbol: {symbol}"
```

**Replacement:**
```python
if symbol:
    context += (
        f"\n\nYour pending edit introduces or modifies: {symbol} "
        "(will appear in the file structure above after this edit applies)."
    )
```

Source: Qwen's suggestion, lightly tuned. "Pending edit introduces or modifies" + the explicit "will appear after this edit applies" closes the inference loop.

### Fix 2 — Add temporal framing to edit-mode emitters

**File 2a:** `tldr/hooks/file_context.py:411-441` (`_format_edit_structure`) — for code/test files.

**Current header:**
```python
lines = [f"[TLDR edit context: {file_path.name}]", "", "File structure:"]
```

**Replacement header:**
```python
lines = [
    f"[TLDR pre-edit context: {file_path.name}]",
    "(Showing the file as it exists BEFORE your pending edit lands. "
    "This hook is informational — your tool call is NOT blocked, "
    "modified, or reverted. Proceed normally.)",
    "",
    "Pre-existing file structure:",
]
```

**Also relabel `Imports:` within the same function:**
```python
# was: lines.extend(["", "Imports:"])
lines.extend(["", "Pre-existing imports:"])
```

(`_format_edit_structure` doesn't have a separate "Functions:" header — it lists functions directly in the file-structure list. The relabel covers Imports only.)

**Also rewrite the misleading trailing block** (current `file_context.py:429-436`):
```python
lines.extend(
    [
        "",
        "Before editing:",
        "- preserve signatures unless the task requires an API change",
        "- after edit, diagnostics hook will run",
    ]
)
```

Replace with:
```python
lines.extend(
    [
        "",
        "Pre-edit snapshot only — your edit will apply normally.",
        "- preserve signatures unless the task requires an API change",
        "- after the tool completes, TLDR will confirm the edit "
        "and surface any diagnostics",
    ]
)
```

The new line is true under Fix 3 (always-emitted post-edit confirmation). Phrasing per Codex review.

**File 2b:** `tldr/hooks/file_context.py:570-574` (`build_file_context_for_path`, non-code-file edit branch).

**Current:**
```python
if mode == "edit":
    context = context.replace("[TLDR ", "[TLDR before editing: ", 1)
    context += "\n- keep edits minimal and preserve existing structure"
```

**Replacement:**
```python
if mode == "edit":
    context = context.replace("[TLDR ", "[TLDR pre-edit context — ", 1)
    context += (
        "\n(Pre-edit snapshot only. This hook does NOT block or modify "
        "your edit. The post-edit hook will confirm completion.)"
        "\n- keep edits minimal and preserve existing structure"
    )
```

`format_nav_map` itself is **not** changed (read mode is fine and read can legitimately modify `updated_input` via `tldr/hooks/read.py:31-40` — adding "NOT modified" framing would be inaccurate there).

Rationale per Qwen + plan-reviewer + Codex: "Pre-existing" + explicit "Pre-edit snapshot only" defangs the "where's my symbol?" misread at the source.

### Fix 3 — Always emit a PostToolUse confirmation, preserving telemetry

**File:** `tldr/hooks/post_edit.py:135-136`

**Current:**
```python
if not messages:
    return noop(reason="clean_no_diagnostics", trigger_files=trigger)
```

**Replacement:**
```python
if not messages:
    if os.environ.get("TLDR_POST_EDIT_CLEAN_CONFIRM") == "0":
        return noop(reason="clean_no_diagnostics", trigger_files=trigger)
    confirmation = _format_clean_edit_confirmation(edited_files)
    return ok(
        HookResponse(
            message=confirmation,
            additional_context=confirmation,
            suppress_output=False,
        ),
        trigger_files=trigger,
        noop_reason="clean_no_diagnostics",
    )
```

**Add helper near bottom of `post_edit.py`:**

```python
def _format_clean_edit_confirmation(edited_files: list[Path]) -> str:
    names = ", ".join(p.name for p in edited_files[:5])
    suffix = f" (+{len(edited_files) - 5} more)" if len(edited_files) > 5 else ""
    return (
        f"[TLDR post-edit] Edit completed for {names}{suffix}. "
        "Post-edit check ran; no diagnostics were surfaced."
    )
```

Wording per Codex review — "no diagnostics were surfaced" is precise (the clean path also fires when the language is unknown or `get_diagnostics` raises an exception; saying "no errors found" would overclaim).

**Telemetry preservation in `scripts/tldr_outcome_model.py:131-148` (`record_hook`):**

Current branch counts `tldr_clean_checks` only when `status == "noop"`. Extend it to also count when `status == "ok"`:

```python
elif event.status == "noop":
    # ...existing branch...
elif event.status == "ok":
    if event.noop_reason == "clean_no_diagnostics":
        self.tldr_clean_checks += 1
        # also surface in the per-reason rollup so reports remain consistent
        self.tldr_noop_reason_counts[event.noop_reason] = (
            self.tldr_noop_reason_counts.get(event.noop_reason, 0) + 1
        )
```

The `noop_reason` field stays valid on `ok` results (the `HookExecutionResult` dataclass allows it; `ok()` in `outcome.py:101` accepts `**kwargs` that flow through to the dataclass).

**Env flag:** `TLDR_POST_EDIT_CLEAN_CONFIRM=0` reverts to the v1 silent-noop behavior. Default behavior is to emit the confirmation. Rollback story: flip the env flag. Per plan-reviewer suggestion.

**Imports needed in `post_edit.py`:** add `import os` at top.

### Fix 4 — Skip pre-edit context for `apply_patch`

**File:** `tldr/hooks/edit.py:63-89` (`build_pre_edit_response`)

Insert early-skip after the existing tool-name guard:

```python
def build_pre_edit_response(event: HookEvent, budget: int = 2000) -> HookExecutionResult:
    if event.tool_name not in EDIT_TOOLS:
        return skipped(reason="wrong_tool")
    if event.tool_name == "apply_patch":
        # Codex shows the diff inline; pre-edit context causes more confusion
        # than orientation. Post-edit diagnostics still run.
        return skipped(reason="apply_patch_pre_edit_suppressed")
    # ... rest unchanged
```

`extract_apply_patch_paths` stays in `edit.py` — still imported by `post_edit.py` for touched-file extraction.

### Fix 5 — Client-aware gating scaffold (no behavior change in v1)

**File:** `tldr/hooks/edit.py`

Add a constant near the top:
```python
# Clients for which pre-edit context (nav map) is suppressed entirely.
# Codex is handled by the `apply_patch` tool-name skip above; this set
# is for future tuning of other clients if real-world data demands it.
CLIENTS_PRE_EDIT_CONTEXT_SUPPRESSED: frozenset[str] = frozenset()
```

In `build_pre_edit_response` after the `apply_patch` skip:
```python
if event.client in CLIENTS_PRE_EDIT_CONTEXT_SUPPRESSED:
    return skipped(reason="client_pre_edit_suppressed")
```

Default is empty set → no behavior change. One-line tuning when needed.

### Fix 6 — Post-edit nav map on clean edits (deferred)

Defer. Fix 3's confirmation should close the loop; if real-world data shows it doesn't, we open a follow-up plan for emitting the updated nav.

### Fix 7 — Framing-token tests + perception eval

**New file:** `tests/test_hook_framing_perception.py`

Two test classes:

1. **`TestPreEditFraming`** — for each `EDIT_TOOLS` member except `apply_patch`, construct the rendered JSON and assert `additionalContext` contains both:
   - `"BEFORE your pending edit lands"`
   - `"NOT blocked"` or `"Proceed normally"`

2. **`TestPostEditFraming`** — for a clean edit, assert the rendered `additionalContext` contains `"no diagnostics were surfaced"`.

3. **`TestApplyPatchSkip`** — assert Codex `apply_patch` PreToolUse returns `skipped(reason="apply_patch_pre_edit_suppressed")` and the rendered output is `{}` (or whatever the runtime renders for noop responses).

**Manual perception eval** (gated, not in CI):

**New file:** `scripts/perception_eval.py`

Small script that:
- Builds the rendered pre-edit + post-edit JSON for a representative `def foo` Edit on a real source file.
- Hands each rendered response to `delegate codex safe` and `delegate droid qwen37 safe` with the prompt: *"Given this hook output, did the system block, modify, or revert my edit? Answer yes/no with one sentence."*
- Parses each completion report, asserts "no" with regex.
- Prints a pass/fail line per model.

Documented as `python3 scripts/perception_eval.py` for Trey to run on demand. Not in CI (model latency, cost). Logs to `reports/perception-eval-<date>.md`.

## Test plan

### Tests to UPDATE

- `tests/test_hooks_edit.py::test_edit_event_on_code_file_returns_structure` — assert new header substring `"BEFORE your pending edit lands"` is present.
- `tests/test_hooks_edit.py::test_codex_apply_patch_update_returns_existing_file_context` — **rename to `test_codex_apply_patch_is_suppressed`** and replace body:
  ```python
  result = build_pre_edit_response(event)
  assert result.status == "skipped"
  assert result.noop_reason == "apply_patch_pre_edit_suppressed"
  assert result.additional_context is None
  ```
- `tests/test_hooks_edit.py::test_output_stays_under_budget` — budget assertion. The header grew ~200 chars; bump the assertion threshold from `<= 420` to `<= 700` (verify against actual output first), or tighten internal per-section budgets.
- `tests/test_hooks_post_edit.py::test_clean_diagnostics_noop` — **rename to `test_clean_diagnostics_emits_confirmation`**:
  ```python
  response = build_post_edit_response(_event(...))
  assert response.status == "ok"
  assert response.noop_reason == "clean_no_diagnostics"
  assert "no diagnostics were surfaced" in response.additional_context
  assert "app.py" in response.additional_context
  ```
- All other `assert response.noop_reason == "clean_no_diagnostics"` in `test_hooks_post_edit.py:160,187` — same pattern.
- `tests/test_tldr_outcome_model.py:71,75` — `TldrHookEvent` test: keep `noop_reason="clean_no_diagnostics"` but also add a sibling event with `status="ok", noop_reason="clean_no_diagnostics"` and assert `tldr_clean_checks` increments for both. Update `tldr_noop_reason_counts` expectation: now both ok-and-noop with that reason count toward it (combined into one dict).
- `tests/test_render_tldr_outcome_report.py:94,104` — the report renderer test; update expected text if needed.

### Tests to ADD

- `tests/test_hooks_edit.py::test_likely_symbol_uses_pending_framing` — assert the rephrased line is present when a `def`/`class` is detected in the edit payload.
- `tests/test_hook_framing_perception.py` — see Fix 7.
- `tests/test_hooks_post_edit.py::test_clean_confirmation_can_be_disabled_via_env` — monkeypatch `os.environ`, assert behavior reverts to `noop`.
- `tests/test_hooks_post_edit.py::test_clean_confirmation_lists_multiple_files` — `apply_patch` with several touched files → confirmation lists them.

### Gate

```
cd ~/Code/llm-tldr && python3 -m pytest tests/ -x -q
```

(Project has no separate lint/format gate per `pyproject.toml`.)

## Risks

- **Token budget creep.** Pre-edit header adds ~250 chars; clean-edit confirmation adds ~100 chars per edit. Net: ~350 chars per edit event. Acceptable for the psychological win.
- **Telemetry consumers outside this repo.** The reports in `reports/tldr-*` rely on `tldr_clean_checks` and `tldr_noop_reason_counts`. Both stay populated under Fix 3. Verify after first run.
- **Codex apply_patch users who relied on pre-edit nav.** None of our delegate flows seem to. Flag in commit.
- **`os.environ` lookup on every clean post-edit.** Negligible cost; one dict lookup.
- **README/docs.** `README.md` may not reference the old strings, but grep to confirm. The plan in `docs/plans/2026-05-21-tldr-skip-reduction-non-md-context.md` introduces the `clean_no_diagnostics` contract; cross-reference it in commit message but don't edit it (historical plan).

## Open questions (resolved from v1)

1. ~~`format_nav_map` mode kwarg?~~ → Wrong function entirely. `_format_edit_structure` gets the temporal header directly. `format_nav_map` (read mode) stays as-is.
2. ~~Session-start framing?~~ → No change. Read-mode framing untouched.
3. ~~`systemMessage` vs `additionalContext`?~~ → Keep `additionalContext` for cross-client parity.
4. ~~Should clean-edit confirmation change `status` to `ok`?~~ → Yes, but preserve `noop_reason="clean_no_diagnostics"` and update telemetry rollup to recognize the new shape.

## Implementation lanes

**Lane A — framing & confirmation (low risk, behavior changes are additive):**
- Fix 1 (rephrase target-symbol line) — `edit.py`
- Fix 2 (`_format_edit_structure` header + relabels + trailing line) — `file_context.py`
- Fix 3 (post-edit confirmation + env flag + telemetry update) — `post_edit.py`, `scripts/tldr_outcome_model.py`
- Update tests: `test_hooks_edit.py`, `test_hooks_post_edit.py`, `test_tldr_outcome_model.py`, `test_render_tldr_outcome_report.py`
- Run gate.

**Lane B — structural (touches same files, runs serially after A):**
- Fix 4 (apply_patch skip) — `edit.py`
- Fix 5 (client-gating scaffold) — `edit.py`
- Fix 7 (framing-token unit tests + perception eval script) — new files
- Update `test_hooks_edit.py::test_codex_apply_patch_*`.
- Run gate.

Both lanes touch `edit.py` and `tests/test_hooks_edit.py`. Run serially A → B, not in parallel.

## Done when

1. `python3 -m pytest tests/ -x` is green.
2. Rendered pre-edit JSON for a representative Edit contains `"BEFORE your pending edit lands"`, `"Pre-existing file structure:"`, and `"Your pending edit introduces or modifies"`.
3. Rendered post-edit JSON for a clean Edit contains `"Edit applied to"` and `"no diagnostics were surfaced"`.
4. Codex `apply_patch` pre-edit returns `skipped(reason="apply_patch_pre_edit_suppressed")`.
5. `tldr_clean_checks` telemetry still increments for clean edits (verify via a unit test).
6. `TLDR_POST_EDIT_CLEAN_CONFIRM=0` reverts behavior to silent noop (verify via a unit test).
7. Manual delegate-driven perception eval: both `delegate codex safe` and `delegate droid qwen37 safe` answer "no" when asked whether the hook blocked their edit.
8. Code review pass via delegate (codex safe + a droid model on the diff) addressed.

## Review trail

- v1 reviewed by `@agent-plan-reviewer` → NEEDS-CHANGES (9 concerns).
- v1 reviewed by `delegate droid qwen37 safe` → NEEDS-CHANGES (5 concerns, partial overlap with above).
- v1 reviewed by `delegate codex safe` → NEEDS-CHANGES (5 concerns; converged with plan-reviewer and Qwen on the two critical bugs; surfaced three additional gaps).
- v2 → v3 incorporates: wrong-function fix (both code and non-code edit emitters), telemetry preservation, "Pre-existing" relabels, "Pre-edit snapshot only." gentling, "no diagnostics were surfaced" precision wording, `test_current_cli_hook_shapes.py` snapshot update, env-flag rollback, and a documented perception eval script.
