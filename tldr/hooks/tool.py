from __future__ import annotations

from tldr.hooks.outcome import HookExecutionResult, noop, ok
from tldr.hooks.permission import check_destructive_command
from tldr.hooks.runtime import HookEvent, HookResponse


def build_pre_tool_response(event: HookEvent) -> HookExecutionResult:
    """High-confidence destructive command guard for pre-tool (Bash/Execute) events."""
    # Only guard shell/execute tool invocations
    guarded_tools = {"bash", "execute", "shell", "command"}
    if (event.tool_name or "").lower() not in guarded_tools:
        return noop("wrong_tool")

    command = ""
    tool_input = event.tool_input
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command") or tool_input.get("cmd") or "")

    if not command:
        return noop("no_command")

    reason = check_destructive_command(command, project=event.cwd)
    if reason is None:
        return noop("clean")

    return ok(
        HookResponse(
            permission_decision="deny",
            reason=reason,
            suppress_output=True,
        ),
    )
