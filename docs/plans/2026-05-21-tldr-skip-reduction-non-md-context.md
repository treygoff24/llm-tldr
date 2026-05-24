# TLDR Skip Reduction for Non-Markdown Agent Work Implementation Plan

**Goal:** Reduce unhelpful TLDR hook skips by supporting common non-Markdown agent workflows: test files, line-specific reads, shell-command file references, HTML/SQL/YAML/JSON/config files, and clean post-edit checks.

**Architecture:** Keep Markdown explicitly excluded. Add file-type-aware context builders for selected non-code artifacts, broaden path eligibility for tests and selected structured/config/document-like files, add lightweight shell command file-intent extraction, and split skip/noop reason codes so telemetry reveals exactly why hooks abstain. Keep hooks best-effort, fast, local, and safe; never emit raw file contents except small structural summaries already derived from local files.

**Tech Stack:** Python 3.14-compatible stdlib-first implementation, existing `tldr/hooks/*` runtime, pytest, existing telemetry/backfill report stack, pipx-installed CLI smoke after verification.

---

## Non-negotiable constraints

1. **Do not support Markdown context.** `.md` and `.mdx` must remain skipped for context injection. Telemetry may record the skip reason, but TLDR must not fire useful read/edit context for Markdown.
2. **Do not weaken secret/junk exclusion.** `.env*`, secret/credential paths, private keys, `.git`, `.tldr`, virtualenvs, `node_modules`, generated build dirs, and coverage/cache dirs remain excluded.
3. **Keep hooks best-effort.** Hook failures must not block normal agent work unless an existing guard already intentionally blocks dangerous actions.
4. **Keep emitted context small.** New context summaries must be structural and bounded; no full-file dumping.
5. **Improve observability.** Generic `bypass` should be replaced with actionable reason codes whenever possible.
6. **Prefer tests before implementation.** Each behavior change gets a failing pytest first.
7. **Delegate execution requirement.** Implementation should be executed by `delegate cursor work` from `/Users/treygoff/Code/llm-tldr`; Codex orchestrates and reviews the diff.

## Current live evidence motivating this plan

Yesterday's matched backfill showed:

- `1,742` matched hook runs; `1,383` skipped.
- Matched skips were mostly:
  - `pre-read` bypass: `501`
  - `pre-edit` bypass: `417`
  - `post-edit` `no_diagnostics`: `434`
- Claude tool calls were dominated by `Bash` (`1,638`) and many direct `Read/Edit/Write` calls targeted `.md`, `.html`, `.sql`, `.yml`, `.json`, tests, line ranges, or outside-project files.
- Markdown was a major skip source, but per user instruction Markdown remains intentionally unsupported.

## Desired final behavior

1. **Tests are eligible.** Test files are allowed for `pre-read`, `pre-edit`, and `post-edit` context/diagnostics unless otherwise excluded by secret/junk policy.
2. **Line-specific reads get compact context.** A `Read` with `offset`/`limit` on an eligible file should still return a small containing-symbol/import/related-file context instead of generic bypass.
3. **Selected non-Markdown file types get structural summaries.** HTML, SQL, YAML/YML, JSON, shell scripts, and extensionless config files like `.gitignore` can receive lightweight context summaries, except lockfiles/generated blobs/credential configs/oversized files.
4. **Markdown stays skipped.** `.md`/`.mdx` return a reason like `markdown_unsupported`.
5. **Shell command file references are understood.** `pre-tool` for `Bash`/`shell`/`command`/`execute`/`exec_command` should parse obvious file references in common commands (`sed`, `nl`, `cat`, `rg`, `grep`, `git diff`, heredocs, `python -m pytest` test paths) and provide compact context where safe.
6. **Clean post-edit checks are not framed as unhelpful skips.** No diagnostics should be represented as a `noop`/clean outcome or a more explicit `clean_no_diagnostics` reason so reports can separate successful clean checks from true abstentions.

---

### Task 1: Actionable path policy and file-kind classification

**Parallel:** no
**Blocked by:** none
**Owned files:** `tldr/hooks/path_policy.py`, `tests/test_path_policy.py`
**Invariants:** Markdown is unsupported; secret/junk/generated paths remain excluded; existing code-file behavior remains valid.
**Out of scope:** Shell parsing, telemetry rendering, installing hooks.

**Files:**
- Modify: `tldr/hooks/path_policy.py`
- Modify: `tests/test_path_policy.py`

**Step 1: Add failing tests for path classification**
Add tests proving:

```python
from pathlib import Path

from tldr.hooks.path_policy import classify_context_path, should_exclude_context_path


def test_classify_context_path_keeps_markdown_unsupported(tmp_path):
    project = tmp_path
    path = project / "README.md"
    path.write_text("# Hello\n", encoding="utf-8")

    result = classify_context_path(project, path)

    assert result.allowed is False
    assert result.reason == "markdown_unsupported"
    assert should_exclude_context_path(project, path) is True


def test_classify_context_path_allows_tests_and_structured_files(tmp_path):
    project = tmp_path
    for rel in [
        "tests/test_app.py",
        "src/widget.test.tsx",
        "templates/page.html",
        "db/migration.sql",
        "config/watch.yml",
        "config/settings.json",
        ".gitignore",
        "scripts/run.sh",
    ]:
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
        assert classify_context_path(project, path).allowed is True
        assert should_exclude_context_path(project, path) is False
```

Also add tests proving `node_modules/foo.ts`, `.env`, and `src/secret_config.py` remain excluded.

**Step 2: Implement classification dataclass**
In `tldr/hooks/path_policy.py`, add:

```python
from dataclasses import dataclass

MARKDOWN_EXTENSIONS = {".md", ".mdx"}
STRUCTURED_EXTENSIONS = {".html", ".htm", ".sql", ".yaml", ".yml", ".json", ".sh"}
CONFIG_FILENAMES = {".gitignore", ".prettierignore", ".dockerignore", "Dockerfile", "Makefile"}
GENERATED_OR_LOCK_FILENAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "composer.lock", "Cargo.lock"}
SECRET_CONFIG_PATTERNS = ("service-account", "credentials", "credential")

@dataclass(frozen=True)
class ContextPathDecision:
    allowed: bool
    reason: str
    file_kind: str
```

Add `classify_context_path(project: Path, path: Path, *, include_tests: bool = True) -> ContextPathDecision` with reason codes:

- `outside_project`
- `unsupported_extension`
- `markdown_unsupported`
- `excluded_dir`
- `secret_like`
- `missing_file`
- `ok_code`
- `ok_test`
- `ok_structured`
- `ok_config`

Make `should_exclude_context_path(...)` return `not classify_context_path(...).allowed`, while preserving its public signature. The default should allow tests for the main context hooks, but callers that intentionally pass `include_tests=False` must keep that behavior until deliberately changed.

Add exclusions and tests for common generated/credential/noisy files:

- `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock`, `composer.lock`, `Cargo.lock`
- `service-account*.json`, `*-credentials.json`, `.npmrc`, `.pypirc`
- oversized structured files; use a conservative default such as 256 KiB for summary-eligible non-code files.

Add or expose a public helper for secret-like path checks so `post_edit.py` no longer imports private `_looks_secret`.

**Step 3: Update existing path-policy callers**
Update these code paths deliberately so the new classification cannot drift:

- `discover_related_candidates(...)`
- `_resolve_import_module(...)`
- `post_edit.extract_edited_files(...)`

Add regression tests proving related candidate discovery can include test neighbors when safe, and post-edit can extract diagnostics targets for test files while still excluding Markdown and secrets.

**Step 4: Verify**
Run:

```bash
uv run pytest -q tests/test_path_policy.py
```

Expected: pass.

---

### Task 2: File-type-specific context builders without Markdown

**Parallel:** no
**Blocked by:** Task 1
**Owned files:** `tldr/hooks/file_context.py`, `tldr/hooks/read.py`, `tldr/hooks/edit.py`, `tests/test_hooks_read.py`, `tests/test_hooks_edit.py`
**Invariants:** Markdown remains skipped; source-code nav-map/edit-structure behavior remains intact; context remains bounded.
**Out of scope:** Shell command parsing, post-edit diagnostics.

**Files:**
- Create: `tldr/hooks/file_context.py`
- Modify: `tldr/hooks/read.py`
- Modify: `tldr/hooks/edit.py`
- Modify: `tests/test_hooks_read.py`
- Modify: `tests/test_hooks_edit.py`

**Step 1: Add failing read tests**
Add tests proving:

- `.md` read returns `status == "skipped"` and `noop_reason == "markdown_unsupported"`.
- `offset/limit` read on a TypeScript file returns `ok` and context includes file structure.
- test file read returns `ok`.
- HTML/SQL/YAML/JSON/shell/config reads return `ok` with a structural label and bounded context.

Example skeleton:

```python
def test_read_markdown_stays_unsupported(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("# Title\n", encoding="utf-8")
    event = make_event(tmp_path, "Read", {"file_path": str(path)})

    result = build_read_response(event)

    assert result.status == "skipped"
    assert result.noop_reason == "markdown_unsupported"
```

**Step 2: Add shared file-kind summary builders**
Create `tldr/hooks/file_context.py` and implement reusable helpers. Task 3 must call these helpers rather than calling top-level `build_read_response(...)` or `build_pre_edit_response(...)`, because those functions are tool-specific and will reject Bash/pre-tool events. Implement:

- `format_html_summary(path, text, budget)` — title, headings, form tags, script/style counts, ids/classes sample.
- `format_sql_summary(path, text, budget)` — migration/object keywords, `CREATE/ALTER/DROP`, table/function names when easily extractable.
- `format_data_summary(path, text, budget)` — JSON top-level keys; YAML top-level keys using simple line parsing.
- `format_shell_summary(path, text, budget)` — shebang, function names, commands with simple regex.
- `format_config_summary(path, text, budget)` — first meaningful patterns for ignore/config files, bounded.

Do not add Markdown summary functions.

**Step 3: Add a reusable context entry point**
In `tldr/hooks/file_context.py`, expose a helper such as:

```python
def build_file_context_for_path(event: HookEvent, path: Path, *, mode: Literal["read", "edit", "shell"], budget: int) -> FileContextResult:
    ...
```

The result should include status/reason/context/context_kind/candidate metadata enough for `read.py`, `edit.py`, and `tool.py` to wrap it in `HookExecutionResult`.

Markdown must return an unsupported decision and no context.

**Step 4: Route read by file kind**
In `build_read_response(...)`:

- Use `classify_context_path` instead of a boolean bypass.
- If denied, return `skipped(reason=decision.reason, trigger_files=trigger)`.
- For code/test files, preserve `extract_file(...)` nav-map behavior.
- For structured/config files, build the matching compact summary and return `ok` with `context_kind` like `html_summary`, `sql_summary`, `data_summary`, `shell_summary`, `config_summary`.
- Keep related candidate discovery only for code/test files unless a safe adjacent-file policy is added later.

**Step 5: Route pre-edit by file kind**
In `build_pre_edit_response(...)`:

- Use `classify_context_path`.
- Markdown returns `markdown_unsupported`.
- Code/test uses existing edit structure.
- Structured/config files return a compact “before editing” summary using the same file-kind summary builders, with edit-specific guidance.

**Step 6: Verify**
Run:

```bash
uv run pytest -q tests/test_hooks_read.py tests/test_hooks_edit.py tests/test_path_policy.py
```

Expected: pass.

---

### Task 3: Shell command file-intent context for `pre-tool`

**Parallel:** no
**Blocked by:** Task 2
**Owned files:** `tldr/hooks/tool.py`, `tldr/hooks/file_context.py`, `tldr/hooks/runner.py`, `tldr/hook_installer.py`, `tests/test_hooks_tool.py`, `tests/test_hook_installer.py`, `tests/test_current_cli_hook_shapes.py`
**Invariants:** Existing destructive-command guard behavior must remain; Markdown file references are ignored/skipped; no shell command is executed by TLDR for context extraction.
**Out of scope:** Full shell parser, arbitrary shell execution, markdown context.

**Files:**
- Modify: `tldr/hooks/tool.py`
- Modify: `tldr/hooks/file_context.py` only if the shared helper needs a small shell-mode extension
- Modify: `tldr/hooks/runner.py` only if dispatch must return context from `pre-tool`
- Modify: `tldr/hook_installer.py`
- Create or modify: `tests/test_hooks_tool.py`
- Modify: `tests/test_hook_installer.py`
- Modify: `tests/test_current_cli_hook_shapes.py`

**Step 1: Add failing shell parser tests**
Add tests proving:

```python
def test_pre_tool_extracts_sed_file_context(tmp_path):
    path = tmp_path / "src" / "app.ts"
    path.parent.mkdir()
    path.write_text("export function main() { return 1 }\n", encoding="utf-8")
    event = make_event(tmp_path, "Bash", {"command": "sed -n '1,80p' src/app.ts"})

    result = build_pre_tool_response(event)

    assert result.status == "ok"
    assert "TLDR" in (result.additional_context or result.message or "")
    assert result.trigger_files == ["src/app.ts"]
```

Also test:

- `exec_command` as an accepted shell-like tool name.
- `nl -ba src/app.ts | sed -n '1,80p'`
- `rg -n "foo" src/app.ts tests/test_app.py`
- `git diff -- src/app.ts`
- heredoc/write command to `config/watch.yml`; if the target does not exist, return `skipped("missing_file")` with the target recorded, or emit only parent/path-kind guidance without reading content. Pick one behavior and test it.
- Markdown file refs are ignored or skipped with `markdown_unsupported` / `all_candidates_unsupported` and never produce context.
- quoted paths, nonexistent paths, URLs, grep patterns containing `/`, and globs. Globs must never be expanded.

**Step 2: Implement safe file extraction**
In `tldr/hooks/tool.py`, add a parser that extracts file path candidates from command strings without executing them. The accepted shell-like tool names must include `bash`, `execute`, `shell`, `command`, and `exec_command`:

- shell-like split via `shlex.split(..., posix=True)` with fallback whitespace split.
- recognize path tokens with supported extensions/config filenames, but only when they resolve inside the project and pass `classify_context_path`.
- recognize `git diff -- <paths>` and `rg/grep/sed/nl/cat/head/tail` path arguments.
- recognize redirection/heredoc targets after `>`, `>>`, `cat >`, and simple `tee` targets.
- de-duplicate candidates; cap at 5.
- never expand globs.
- never inspect heredoc body content.
- ignore URLs and option values unless the option is known to take a path.
- cap file reads and total bytes through the shared file-context helper.

**Step 3: Build pre-tool context**
For non-dangerous shell commands:

- Keep existing destructive guard behavior first.
- If safe file candidates exist, call `build_file_context_for_path(...)` from `tldr/hooks/file_context.py` depending on whether command looks read-only or write-like.
- Return `ok` with compact context and `context_kind="shell_file_context"`.
- If no candidates, return existing clean noop behavior.

**Step 4: Install Codex shell context safely, without broadening permission guards**
Current installer only adds Codex Bash `pre-tool` when `--enable-tool-guard` is used, and that same branch also installs `PermissionRequest` guard behavior. Split these concerns carefully:

- Default Codex `PreToolUse` may add a `Bash`/shell `pre-tool` hook only as **non-blocking context**.
- `PermissionRequest` destructive guard must stay behind `--enable-tool-guard`.
- Existing `--enable-tool-guard` behavior must remain compatible.
- Installer tests must use temporary config paths only; do **not** mutate real `~/.codex/hooks.json` or Claude settings during delegate execution.
- Add temp-config tests proving default Codex install adds shell context without unexpectedly adding/removing `PermissionRequest` guards.

For Claude, do **not** add Bash `pre-tool` by default in this implementation. Claude already has `rtk hook claude` on Bash; avoid altering that interaction. Leave Claude shell context behind existing opt-in guard behavior or document it as future work.

**Step 6: Verify**
Run:

```bash
uv run pytest -q tests/test_hooks_tool.py tests/test_hook_installer.py tests/test_current_cli_hook_shapes.py
```

Expected: pass.

---

### Task 4: Post-edit clean outcome semantics

**Parallel:** no
**Blocked by:** Task 1
**Owned files:** `tldr/hooks/post_edit.py`, `tests/test_hooks_post_edit.py`
**Invariants:** Diagnostics are still reported when present; absence of diagnostics should not look like a failed/useless hook.
**Out of scope:** Adding new diagnostics engines.

**Files:**
- Modify: `tldr/hooks/post_edit.py`
- Modify: `tests/test_hooks_post_edit.py`

**Step 1: Add failing tests**
Update post-edit tests so clean edits expect either:

- `status == "noop"` and `noop_reason == "clean_no_diagnostics"`, or
- a dedicated clean counter in rollups.

Preferred: return `noop(reason="clean_no_diagnostics", trigger_files=trigger)` because it separates clean checks from abstention.

**Step 2: Implement clean no-op**
In `build_post_edit_response(...)`, when edited files exist but no diagnostic messages exist, return `noop(reason="clean_no_diagnostics", trigger_files=trigger)` instead of `skipped(reason="no_diagnostics")`.

If no edited files can be extracted, return `skipped(reason="no_edit_targets")`.

**Step 3: Add Markdown and test-file post-edit regressions**
Add tests proving post-edit on Markdown returns a Markdown-specific unsupported skip/noop reason and no diagnostics context, while post-edit on safe test files is eligible for diagnostics.

**Step 4: Verify**
Run:

```bash
uv run pytest -q tests/test_hooks_post_edit.py
```

Expected: pass.

---

### Task 5: Telemetry/backfill skip reason reporting

**Parallel:** no
**Blocked by:** Tasks 1-4
**Owned files:** `scripts/tldr_outcome_model.py`, `scripts/backfill_tldr_outcomes.py`, `scripts/render_tldr_outcome_report.py`, `tests/test_backfill_tldr_outcomes.py`, `tests/test_render_tldr_outcome_report.py`, `docs/dev-notes/outcome-telemetry.md`
**Invariants:** Existing reports remain parseable; local-rich evidence remains opt-in; Markdown remains unsupported.
**Out of scope:** Reworking verdict heuristics beyond reporting clean checks and skip reasons.

**Files:**
- Modify: `scripts/tldr_outcome_model.py`
- Modify: `scripts/backfill_tldr_outcomes.py`
- Modify: `scripts/render_tldr_outcome_report.py`
- Modify: `tests/test_backfill_tldr_outcomes.py`
- Modify: `tests/test_render_tldr_outcome_report.py`
- Modify: `docs/dev-notes/outcome-telemetry.md`

**Step 1: Add clean-check and skip/noop reason counters to rollup**
Track `tldr_skip_reason_counts`, `tldr_noop_reason_counts`, and `tldr_clean_checks` in `SessionRollup`. Treat `clean_no_diagnostics` as a clean check, not an unhelpful skip.

**Step 2: Parse reason codes**
Make `ParsedTelemetry` include `noop_reason`. Record skip/noop reason counts and clean checks when matching telemetry to sessions.

**Step 3: Render report sections**
Add a report section like:

```markdown
## Skip / clean-check reasons

- Skips by reason: {...}
- Noops by reason: {...}
- Clean post-edit checks: N
```

**Step 4: Verify**
Run:

```bash
uv run pytest -q tests/test_backfill_tldr_outcomes.py tests/test_render_tldr_outcome_report.py tests/test_tldr_outcome_model.py
```

Expected: pass.

---

### Task 6: Documentation, smoke, and local installation readiness

**Parallel:** no
**Blocked by:** Tasks 1-5
**Owned files:** `README.md`, `docs/dev-notes/outcome-telemetry.md`, `tests/test_readme_examples.py`
**Invariants:** Docs must explicitly say Markdown is not supported by TLDR context hooks.
**Out of scope:** Pushing to remote.

**Files:**
- Modify: `README.md`
- Modify: `docs/dev-notes/outcome-telemetry.md`
- Modify: `tests/test_readme_examples.py`

**Step 1: Update docs**
Document:

- supported file kinds: code, tests, HTML, SQL, YAML/YML, JSON, shell/config.
- unsupported file kinds: Markdown/MDX, binary/media, secrets, generated deps.
- shell command support is best-effort and safe/static only.
- `clean_no_diagnostics` means successful clean post-edit check, not a failure.
- Delegate execution must not mutate real user hook configs; installer tests use temp config paths only.

**Step 2: Add README example test if needed**
Ensure README examples still pass.

**Step 3: Final verification**
Run focused and full checks:

```bash
uv run pytest -q \
  tests/test_path_policy.py \
  tests/test_hooks_read.py \
  tests/test_hooks_edit.py \
  tests/test_hooks_post_edit.py \
  tests/test_hooks_tool.py \
  tests/test_backfill_tldr_outcomes.py \
  tests/test_render_tldr_outcome_report.py \
  tests/test_tldr_outcome_model.py \
  tests/test_hook_installer.py \
  tests/test_current_cli_hook_shapes.py \
  tests/test_readme_examples.py

uv run ruff check tldr scripts tests
uv run pytest -q tests
```

Expected: all pass.

**Step 4: Manual live smoke after Codex review**
Codex orchestrator, not delegate, should run after reviewing the diff:

```bash
printf '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"tests/test_path_policy.py","offset":1,"limit":20},"cwd":"/Users/treygoff/Code/llm-tldr"}\n' \
  | TLDR_TELEMETRY=1 TLDR_TELEMETRY_MODE=local-rich TLDR_TELEMETRY_REDACT_PATHS=0 \
    uv run python -m tldr.cli hooks run pre-read --client codex
```

Expected: context emitted for test file line-specific read.

Also smoke Markdown:

```bash
printf '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"README.md"},"cwd":"/Users/treygoff/Code/llm-tldr"}\n' \
  | TLDR_TELEMETRY=1 TLDR_TELEMETRY_MODE=local-rich TLDR_TELEMETRY_REDACT_PATHS=0 \
    uv run python -m tldr.cli hooks run pre-read --client codex
```

Expected: `{}` and telemetry skip reason `markdown_unsupported`.

---

## Delegation prompt outline

After plan review and patching, hand this whole plan to Cursor Composer with:

```bash
delegate cursor work --prompt-file /tmp/tldr-skip-reduction-cursor.md --cwd /Users/treygoff/Code/llm-tldr
```

Prompt requirements:

- Execute the plan in order.
- Do not implement Markdown support.
- Do not mutate real user hook configs; installer tests must use temporary config paths only.
- Do not reinstall pipx or change global hook config.
- Keep changes scoped to the owned files unless tests reveal a necessary adjacent file; report any scope expansion.
- Run focused tests after each task and final full verification if feasible.
- Do not commit.
- Final response must list changed files and exact verification results.

## Acceptance criteria

- Markdown remains unsupported and tested.
- Test files and selected structured/config files produce useful compact context.
- Line-specific reads on eligible files no longer generic-bypass.
- Shell file-reference context exists at least for common read-only command patterns.
- Post-edit clean checks are separated from true skips.
- Backfill/render reports expose skip/noop reason breakdowns.
- Focused tests, ruff, and full tests pass or any residual failures are explicitly explained with evidence.
