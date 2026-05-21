from __future__ import annotations

import re
import shlex
from pathlib import Path

from tldr.hooks.file_context import build_file_context_for_path
from tldr.hooks.outcome import HookExecutionResult, event_relative_path, noop, ok, skipped
from tldr.hooks.path_policy import (
    CONFIG_FILENAMES,
    STRUCTURED_EXTENSIONS,
    classify_context_path,
    resolve_event_path,
)
from tldr.hooks.permission import check_destructive_command
from tldr.hooks.runtime import HookEvent, HookResponse

GUARDED_TOOLS = {"bash", "execute", "shell", "command", "exec_command"}
PATH_OPTIONS = frozenset(
    {
        "-f",
        "--file",
        "--files",
        "--path",
        "--paths",
        "--include",
        "--exclude",
        "--glob",
    }
)
PATH_COMMANDS = frozenset(
    {
        "sed",
        "nl",
        "cat",
        "head",
        "tail",
        "rg",
        "grep",
        "git",
        "tee",
        "python",
        "pytest",
        "uv",
    }
)
WRITE_REDIRECT_MARKERS = (">", ">>")
MAX_SHELL_CANDIDATES = 5
SUPPORTED_PATH_SUFFIXES = STRUCTURED_EXTENSIONS | {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".php",
    ".kt",
    ".swift",
    ".cs",
    ".scala",
    ".c",
    ".h",
    ".cpp",
    ".cc",
    ".cxx",
    ".hpp",
    ".lua",
    ".luau",
    ".md",
    ".mdx",
}


def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _looks_like_path_token(token: str) -> bool:
    if not token or token.startswith("-"):
        return False
    if "://" in token or token.startswith("http"):
        return False
    if any(char in token for char in "*?[]"):
        return False
    if "/" not in token and "." not in token and token not in CONFIG_FILENAMES:
        return False
    return True


def _resolve_command_path(event: HookEvent, token: str) -> Path | None:
    if not _looks_like_path_token(token):
        return None
    path = resolve_event_path(event, token)
    if path is None:
        return None
    suffix = path.suffix.lower()
    if path.name in CONFIG_FILENAMES or suffix in SUPPORTED_PATH_SUFFIXES:
        return path
    return None


def extract_shell_file_candidates(event: HookEvent, command: str) -> list[Path]:
    tokens = _split_command(command)
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None or path in seen:
            return
        seen.add(path)
        candidates.append(path)

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "git" and i + 1 < len(tokens) and tokens[i + 1] == "diff":
            j = i + 2
            if j < len(tokens) and tokens[j] == "--":
                for path_token in tokens[j + 1 :]:
                    add(_resolve_command_path(event, path_token))
            else:
                while j < len(tokens):
                    raw = tokens[j]
                    if raw == "--":
                        for path_token in tokens[j + 1 :]:
                            add(_resolve_command_path(event, path_token))
                        break
                    if not raw.startswith("-"):
                        add(_resolve_command_path(event, raw))
                    j += 1
            i += 1
            continue

        if token in {"sed", "nl", "cat", "head", "tail", "rg", "grep"}:
            j = i + 1
            while j < len(tokens):
                part = tokens[j]
                if part.startswith("-"):
                    if part in PATH_OPTIONS and j + 1 < len(tokens):
                        add(_resolve_command_path(event, tokens[j + 1]))
                        j += 2
                        continue
                    j += 1
                    continue
                add(_resolve_command_path(event, part))
                j += 1
            i = j
            continue

        if token in {"python", "pytest", "uv"}:
            j = i + 1
            while j < len(tokens):
                part = tokens[j]
                if part.startswith("-"):
                    j += 1
                    continue
                add(_resolve_command_path(event, part))
                j += 1
            i = j
            continue

        if token in WRITE_REDIRECT_MARKERS or (token == ">" and i > 0 and tokens[i - 1] == "cat"):
            if i + 1 < len(tokens):
                add(_resolve_command_path(event, tokens[i + 1]))
            i += 1
            continue

        if token == "tee" and i + 1 < len(tokens):
            add(_resolve_command_path(event, tokens[i + 1]))
            i += 2
            continue

        if _looks_like_path_token(token):
            add(_resolve_command_path(event, token))

        i += 1

    heredoc_targets = re.findall(
        r"(?:cat|tee)\s+>\s*([^\s;|&]+)|(?:>>?)\s*([^\s;|&]+)",
        command,
    )
    for groups in heredoc_targets:
        for raw in groups:
            if raw:
                add(_resolve_command_path(event, raw.strip()))

    return candidates[:MAX_SHELL_CANDIDATES]


def _command_looks_write_like(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in (">>", " >", " tee ", "apply_patch", " sed -i"))


def build_pre_tool_response(event: HookEvent, budget: int = 1200) -> HookExecutionResult:
    """Destructive command guard and compact shell file-intent context."""
    if (event.tool_name or "").lower() not in GUARDED_TOOLS:
        return noop("wrong_tool")

    command = ""
    tool_input = event.tool_input
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command") or tool_input.get("cmd") or "")

    if not command:
        return noop("no_command")

    reason = check_destructive_command(command, project=event.cwd)
    if reason is not None:
        return ok(
            HookResponse(
                permission_decision="deny",
                reason=reason,
                suppress_output=True,
            ),
        )

    candidates = extract_shell_file_candidates(event, command)
    if not candidates:
        return noop("clean")

    contexts: list[str] = []
    trigger_files: list[str] = []
    skipped_reasons: list[str] = []

    for path in candidates:
        rel = event_relative_path(event, path)
        if rel:
            trigger_files.append(rel)
        decision = classify_context_path(event.cwd, path)
        if not decision.allowed:
            skipped_reasons.append(decision.reason)
        if decision.reason == "markdown_unsupported":
            continue
        if not path.exists():
            if decision.reason == "missing_file" and rel:
                contexts.append(
                    f"[TLDR shell target: {rel}]\n- file does not exist yet; verify path before writing"
                )
            continue
        if not decision.allowed:
            continue
        file_result = build_file_context_for_path(
            event,
            path,
            mode="read" if not _command_looks_write_like(command) else "edit",
            budget=budget,
        )
        if file_result.status == "ok" and file_result.context:
            contexts.append(file_result.context)

    if (
        trigger_files
        and skipped_reasons
        and len(skipped_reasons) == len(candidates)
        and all(reason == "markdown_unsupported" for reason in skipped_reasons)
    ):
        return skipped(reason="markdown_unsupported", trigger_files=trigger_files)

    if not contexts:
        return noop("clean")

    combined = "\n\n".join(contexts)
    message = f"TLDR shell file context:\n{combined}"
    return ok(
        HookResponse(message=message, additional_context=message, suppress_output=False),
        trigger_files=trigger_files,
        context_kind="shell_file_context",
    )
