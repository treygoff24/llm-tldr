from __future__ import annotations

from tldr.hooks.runtime import parse_hook_event
from tldr.hooks.tool import build_pre_tool_response, extract_shell_file_candidates


def make_event(tmp_path, tool_name: str, tool_input: dict):
    return parse_hook_event(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "cwd": str(tmp_path),
        },
        client="codex",
    )


def test_pre_tool_extracts_sed_file_context(tmp_path):
    path = tmp_path / "src" / "app.ts"
    path.parent.mkdir(parents=True)
    path.write_text("export function main() { return 1 }\n", encoding="utf-8")
    event = make_event(tmp_path, "Bash", {"command": "sed -n '1,80p' src/app.ts"})

    result = build_pre_tool_response(event)

    assert result.status == "ok"
    assert "TLDR" in (result.additional_context or result.message or "")
    assert result.trigger_files == ["src/app.ts"]


def test_exec_command_is_shell_like(tmp_path):
    path = tmp_path / "src" / "app.ts"
    path.parent.mkdir(parents=True)
    path.write_text("export function main() { return 1 }\n", encoding="utf-8")
    event = make_event(tmp_path, "exec_command", {"command": "nl -ba src/app.ts"})

    result = build_pre_tool_response(event)

    assert result.status == "ok"
    assert "src/app.ts" in result.trigger_files


def test_rg_multiple_paths(tmp_path):
    app = tmp_path / "src" / "app.ts"
    test_file = tmp_path / "tests" / "test_app.py"
    app.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    app.write_text("export const foo = 1\n", encoding="utf-8")
    test_file.write_text("def test_foo():\n    assert True\n", encoding="utf-8")
    event = make_event(
        tmp_path,
        "Bash",
        {"command": 'rg -n "foo" src/app.ts tests/test_app.py'},
    )

    result = build_pre_tool_response(event)

    assert result.status == "ok"
    assert set(result.trigger_files) == {"src/app.ts", "tests/test_app.py"}


def test_git_diff_paths(tmp_path):
    path = tmp_path / "src" / "app.ts"
    path.parent.mkdir(parents=True)
    path.write_text("export function main() { return 1 }\n", encoding="utf-8")
    event = make_event(tmp_path, "Bash", {"command": "git diff -- src/app.ts"})

    result = build_pre_tool_response(event)

    assert result.status == "ok"
    assert result.trigger_files == ["src/app.ts"]


def test_markdown_reference_skipped(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n", encoding="utf-8")
    event = make_event(tmp_path, "Bash", {"command": "sed -n '1,10p' README.md"})

    result = build_pre_tool_response(event)

    assert result.status == "skipped"
    assert result.noop_reason == "markdown_unsupported"


def test_missing_redirect_target_reports_missing_file(tmp_path):
    event = make_event(tmp_path, "Bash", {"command": "cat > config/watch.yml <<'EOF'\nkey: value\nEOF"})

    result = build_pre_tool_response(event)

    assert result.status == "ok"
    assert result.trigger_files == ["config/watch.yml"]
    assert "does not exist" in (result.additional_context or "")


def test_glob_tokens_are_not_expanded(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    event = make_event(tmp_path, "Bash", {"command": "rg foo *.py"})

    candidates = extract_shell_file_candidates(event, event.tool_input["command"])

    assert candidates == []


def test_destructive_command_still_denied(tmp_path):
    event = make_event(tmp_path, "Bash", {"command": "rm -rf /"})

    result = build_pre_tool_response(event)

    assert result.permission_decision == "deny"
