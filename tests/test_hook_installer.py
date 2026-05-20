import json

import pytest

from tldr.hook_installer import install_hooks


@pytest.fixture
def fake_tldr(tmp_path):
    executable = tmp_path / "bin" / "tldr"
    executable.parent.mkdir()
    executable.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"hooks\" ]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    executable.chmod(0o755)
    return executable


def test_dry_run_does_not_write(tmp_path, fake_tldr):
    config = tmp_path / "settings.json"

    result = install_hooks("claude", config_path=str(config), dry_run=True, tldr_path=str(fake_tldr))

    assert result.changed
    assert not config.exists()


def test_merge_preserves_existing_hooks(tmp_path, fake_tldr):
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Read",
                            "hooks": [{"type": "command", "command": "other-tool", "timeout": 1}],
                        }
                    ]
                }
            }
        )
    )

    install_hooks("claude", config_path=str(config), tldr_path=str(fake_tldr))
    data = json.loads(config.read_text())
    hooks = data["hooks"]["PreToolUse"][0]["hooks"]

    assert any(hook["command"] == "other-tool" for hook in hooks)
    assert any("hooks run pre-read" in hook["command"] for hook in hooks)


def test_rerunning_installer_is_idempotent(tmp_path, fake_tldr):
    config = tmp_path / "settings.json"

    first = install_hooks("codex", config_path=str(config), tldr_path=str(fake_tldr))
    second = install_hooks("codex", config_path=str(config), tldr_path=str(fake_tldr))

    assert first.changed
    assert not second.changed
    assert second.actions == []


def test_backup_created_on_write(tmp_path, fake_tldr):
    config = tmp_path / "settings.json"
    config.write_text("{}\n")

    result = install_hooks("claude", config_path=str(config), tldr_path=str(fake_tldr))

    assert result.backup_path is not None
    assert result.backup_path.exists()


def test_codex_output_has_top_level_hooks(tmp_path, fake_tldr):
    config = tmp_path / "hooks.json"

    install_hooks("codex", config_path=str(config), tldr_path=str(fake_tldr))
    data = json.loads(config.read_text())

    assert "hooks" in data
    assert "PreToolUse" in data["hooks"]


def test_codex_installer_uses_latest_supported_matchers(tmp_path, fake_tldr):
    config = tmp_path / "hooks.json"

    install_hooks("codex", config_path=str(config), tldr_path=str(fake_tldr))
    data = json.loads(config.read_text())
    serialized = json.dumps(data)

    assert "hooks run pre-read" not in serialized
    assert data["hooks"]["SessionStart"][0]["matcher"] == "startup|resume|clear"
    assert data["hooks"]["PreToolUse"][0]["matcher"] == "apply_patch|Edit|Write"
    assert data["hooks"]["PostToolUse"][0]["matcher"] == "apply_patch|Edit|Write"


def test_codex_installer_removes_stale_tldr_read_and_old_matcher_groups(tmp_path, fake_tldr):
    config = tmp_path / "hooks.json"
    config.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": ".*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/bin/echo hooks run session-start --client codex",
                                }
                            ],
                        }
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "^Read$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/bin/echo hooks run pre-read --client codex",
                                }
                            ],
                        },
                        {
                            "matcher": "^(Edit|Write|MultiEdit|Update)$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/bin/echo hooks run pre-edit --client codex",
                                }
                            ],
                        },
                    ],
                    "PostToolUse": [
                        {
                            "matcher": "^(Edit|Write|MultiEdit|Update)$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/bin/echo hooks run post-edit --client codex",
                                }
                            ],
                        }
                    ],
                }
            }
        )
    )

    install_hooks("codex", config_path=str(config), tldr_path=str(fake_tldr))
    data = json.loads(config.read_text())
    serialized = json.dumps(data)
    matchers = {
        event: [group.get("matcher") for group in groups]
        for event, groups in data["hooks"].items()
    }

    assert "hooks run pre-read" not in serialized
    assert ".*" not in matchers["SessionStart"]
    assert "^Read$" not in matchers["PreToolUse"]
    assert "^(Edit|Write|MultiEdit|Update)$" not in matchers["PreToolUse"]
    assert "^(Edit|Write|MultiEdit|Update)$" not in matchers["PostToolUse"]
    assert data["hooks"]["SessionStart"][0]["matcher"] == "startup|resume|clear"
    assert data["hooks"]["PreToolUse"][0]["matcher"] == "apply_patch|Edit|Write"
    assert data["hooks"]["PostToolUse"][0]["matcher"] == "apply_patch|Edit|Write"


def test_claude_output_has_hooks_key(tmp_path, fake_tldr):
    config = tmp_path / "settings.json"

    install_hooks("claude", config_path=str(config), tldr_path=str(fake_tldr))

    assert "hooks" in json.loads(config.read_text())


def test_existing_legacy_read_hook_is_replaced(tmp_path, fake_tldr):
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Read",
                            "hooks": [{"type": "command", "command": "~/.claude-shared/hooks/tldr-read.mjs"}],
                        }
                    ]
                }
            }
        )
    )

    result = install_hooks("claude", config_path=str(config), dry_run=True, tldr_path=str(fake_tldr))

    assert any("legacy TLDR hook" in action for action in result.actions)
    assert "tldr-read.mjs" not in json.dumps(result.config)


def test_existing_legacy_diagnostics_hook_is_replaced(tmp_path, fake_tldr):
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [
                        {
                            "matcher": "Edit|Write|MultiEdit|Update",
                            "hooks": [{"type": "command", "command": "post-edit-diagnostics.mjs"}],
                        }
                    ]
                }
            }
        )
    )

    result = install_hooks("claude", config_path=str(config), dry_run=True, tldr_path=str(fake_tldr))

    assert "post-edit-diagnostics.mjs" not in json.dumps(result.config)


def test_unrelated_settings_keys_remain_unchanged(tmp_path, fake_tldr):
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"permissions": {"allow": ["Read"]}, "statusLine": "ok"}))

    install_hooks("claude", config_path=str(config), tldr_path=str(fake_tldr))
    data = json.loads(config.read_text())

    assert data["permissions"] == {"allow": ["Read"]}
    assert data["statusLine"] == "ok"


def test_installed_hook_commands_use_absolute_paths(tmp_path):
    config = tmp_path / "hooks.json"
    fake = tmp_path / "bin" / "tldr"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"hooks\" ]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    fake.chmod(0o755)

    result = install_hooks("codex", config_path=str(config), tldr_path=str(fake))
    payload = json.dumps(result.config)

    assert str(fake.resolve()) in payload


def test_installer_rejects_tldr_without_hooks(tmp_path):
    config = tmp_path / "hooks.json"
    fake = tmp_path / "bin" / "tldr"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\nexit 2\n")
    fake.chmod(0o755)

    with pytest.raises(RuntimeError, match="does not support 'tldr hooks'"):
        install_hooks("codex", config_path=str(config), tldr_path=str(fake))

    assert not config.exists()


def test_installer_prefers_current_python_module_over_stale_path_tldr(tmp_path, monkeypatch):
    config = tmp_path / "hooks.json"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    python = bin_dir / "python"
    python.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-m\" ] && [ \"$2\" = \"tldr.cli\" ] && [ \"$3\" = \"hooks\" ]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    python.chmod(0o755)

    stale_global = bin_dir / "global-tldr"
    stale_global.write_text("#!/bin/sh\nexit 2\n")
    stale_global.chmod(0o755)

    monkeypatch.setattr("tldr.hook_installer.sys.executable", str(python))
    monkeypatch.setattr("tldr.hook_installer.shutil.which", lambda name: str(stale_global) if name == "tldr" else None)

    result = install_hooks("codex", config_path=str(config))
    payload = json.dumps(result.config)

    assert f"{python} -m tldr.cli hooks run" in payload
    assert str(stale_global) not in payload
