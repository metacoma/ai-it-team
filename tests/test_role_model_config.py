"""Tests for per-role model configuration via YAML config file.

Covers:
- _resolve_role_model() helper precedence (YAML > global > None)
- _load_role_model_config() discovery (flag > env > well-known paths)
- Error resilience (missing file, invalid YAML, empty roles)
- Backward compatibility (no YAML = current behavior)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from openhands_langgraph.cli import _load_role_model_config
from openhands_langgraph.nodes import _resolve_role_model
from openhands_langgraph.state import OpenHandsGraphState


# ---------------------------------------------------------------------------
# _resolve_role_model tests
# ---------------------------------------------------------------------------


class TestResolveRoleModel:
    """Unit tests for the _resolve_role_model helper."""

    def test_resolve_from_yaml_config(self):
        """YAML config present, role has model → returns YAML model."""
        state: OpenHandsGraphState = {
            "role_models": {"scout": "openai/qwen36-27b"},
            "model": "openai/coder",
        }
        result = _resolve_role_model("scout", state)
        assert result == "openai/qwen36-27b"

    def test_resolve_fallback_to_global(self):
        """Role not in YAML config → returns global model."""
        state: OpenHandsGraphState = {
            "role_models": {"scout": "openai/qwen36-27b"},
            "model": "openai/coder",
        }
        result = _resolve_role_model("coder", state)
        assert result == "openai/coder"

    def test_resolve_no_yaml_uses_global(self):
        """No role_models in state → returns global model."""
        state: OpenHandsGraphState = {
            "model": "openai/coder",
        }
        result = _resolve_role_model("scout", state)
        assert result == "openai/coder"

    def test_resolve_no_config_no_global(self):
        """No config, no global model → returns None."""
        state: OpenHandsGraphState = {}
        result = _resolve_role_model("scout", state)
        assert result is None

    def test_resolve_empty_yaml_value_fallback(self):
        """YAML value is empty string → falls back to global."""
        state: OpenHandsGraphState = {
            "role_models": {"scout": ""},
            "model": "openai/coder",
        }
        result = _resolve_role_model("scout", state)
        assert result == "openai/coder"

    def test_resolve_whitespace_yaml_value_fallback(self):
        """YAML value is whitespace → falls back to global."""
        state: OpenHandsGraphState = {
            "role_models": {"scout": "   "},
            "model": "openai/coder",
        }
        result = _resolve_role_model("scout", state)
        assert result == "openai/coder"

    def test_resolve_non_dict_role_models_ignores(self):
        """role_models is not a dict → falls back to global."""
        state: OpenHandsGraphState = {
            "role_models": "not-a-dict",
            "model": "openai/coder",
        }
        result = _resolve_role_model("scout", state)
        assert result == "openai/coder"

    def test_resolve_model_stripped(self):
        """YAML model value is stripped of whitespace."""
        state: OpenHandsGraphState = {
            "role_models": {"scout": "  openai/qwen36-27b  "},
        }
        result = _resolve_role_model("scout", state)
        assert result == "openai/qwen36-27b"

    def test_resolve_all_roles_mapping(self):
        """All 8 roles map correctly from YAML config."""
        state: OpenHandsGraphState = {
            "role_models": {
                "scout": "openai/qwen36-27b",
                "research": "openai/qwen36-27b",
                "senior_staff_engineer": "openai/qwen36-35b",
                "architect": "openai/qwen36-35b",
                "coder": "openai/qwen36-35b",
                "qa": "openai/qwen36-27b",
                "reviewer": "openai/qwen36-27b",
                "publisher": "openai/qwen36-35b",
            },
            "model": "openai/coder",
        }
        assert _resolve_role_model("scout", state) == "openai/qwen36-27b"
        assert _resolve_role_model("research", state) == "openai/qwen36-27b"
        assert _resolve_role_model("senior_staff_engineer", state) == "openai/qwen36-35b"
        assert _resolve_role_model("architect", state) == "openai/qwen36-35b"
        assert _resolve_role_model("coder", state) == "openai/qwen36-35b"
        assert _resolve_role_model("qa", state) == "openai/qwen36-27b"
        assert _resolve_role_model("reviewer", state) == "openai/qwen36-27b"
        assert _resolve_role_model("publisher", state) == "openai/qwen36-35b"


# ---------------------------------------------------------------------------
# _load_role_model_config tests
# ---------------------------------------------------------------------------


class TestLoadRoleModelConfig:
    """Unit tests for YAML config loading and discovery."""

    def test_load_config_explicit_path(self, tmp_path: Path):
        """Explicit --config flag with valid file → returns roles dict."""
        config_file = tmp_path / "custom-config.yaml"
        config_file.write_text(
            "roles:\n  scout: openai/qwen36-27b\n  coder: openai/qwen36-35b\n"
        )
        result = _load_role_model_config(str(config_file))
        assert result == {
            "scout": "openai/qwen36-27b",
            "coder": "openai/qwen36-35b",
        }

    def test_load_config_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """OPENHANDS_CONFIG env var → returns roles dict."""
        config_file = tmp_path / "env-config.yaml"
        config_file.write_text("roles:\n  scout: openai/qwen36-27b\n")
        monkeypatch.setenv("OPENHANDS_CONFIG", str(config_file))
        result = _load_role_model_config(None)
        assert result == {"scout": "openai/qwen36-27b"}

    def test_load_config_explicit_path_takes_precedence_over_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Explicit --config flag takes precedence over OPENHANDS_CONFIG env var."""
        env_file = tmp_path / "env.yaml"
        env_file.write_text("roles:\n  scout: openai/env-model\n")
        flag_file = tmp_path / "flag.yaml"
        flag_file.write_text("roles:\n  scout: openai/flag-model\n")
        monkeypatch.setenv("OPENHANDS_CONFIG", str(env_file))
        result = _load_role_model_config(str(flag_file))
        assert result == {"scout": "openai/flag-model"}

    def test_load_config_well_known_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """./.openhands-role-models.yaml exists → returns roles dict."""
        config_file = tmp_path / ".openhands-role-models.yaml"
        config_file.write_text("roles:\n  scout: openai/qwen36-27b\n")
        monkeypatch.chdir(tmp_path)
        result = _load_role_model_config(None)
        assert result == {"scout": "openai/qwen36-27b"}

    def test_load_config_well_known_config_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """./config.yaml fallback → returns roles dict."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("roles:\n  coder: openai/qwen36-35b\n")
        monkeypatch.chdir(tmp_path)
        result = _load_role_model_config(None)
        assert result == {"coder": "openai/qwen36-35b"}

    def test_load_config_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """No config file anywhere → returns None (no crash)."""
        monkeypatch.chdir(tmp_path)
        # Ensure no env var is set
        monkeypatch.delenv("OPENHANDS_CONFIG", raising=False)
        result = _load_role_model_config(None)
        assert result is None

    def test_load_config_invalid_yaml(self, tmp_path: Path):
        """Malformed YAML file → returns None (no crash)."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("roles:\n  scout: [invalid yaml\n")
        result = _load_role_model_config(str(config_file))
        assert result is None

    def test_load_config_no_roles_key(self, tmp_path: Path):
        """YAML without roles key → returns None."""
        config_file = tmp_path / "no-roles.yaml"
        config_file.write_text("other_key: value\n")
        result = _load_role_model_config(str(config_file))
        assert result is None

    def test_load_config_empty_roles(self, tmp_path: Path):
        """roles: {} → returns None."""
        config_file = tmp_path / "empty-roles.yaml"
        config_file.write_text("roles:\n")
        result = _load_role_model_config(str(config_file))
        assert result is None

    def test_load_config_roles_as_list_ignored(self, tmp_path: Path):
        """roles is a list (not dict) → returns None."""
        config_file = tmp_path / "list-roles.yaml"
        config_file.write_text("roles:\n  - scout\n  - coder\n")
        result = _load_role_model_config(str(config_file))
        assert result is None

    def test_load_config_non_string_values_converted(self, tmp_path: Path):
        """Non-string YAML values are converted to strings."""
        config_file = tmp_path / "non-string.yaml"
        config_file.write_text("roles:\n  scout: openai/qwen36-27b\n  coder: 123\n")
        result = _load_role_model_config(str(config_file))
        assert result == {"scout": "openai/qwen36-27b", "coder": "123"}

    def test_load_config_empty_value_skipped(self, tmp_path: Path):
        """Empty string values in roles are skipped."""
        config_file = tmp_path / "empty-val.yaml"
        config_file.write_text("roles:\n  scout: openai/qwen36-27b\n  coder:\n")
        result = _load_role_model_config(str(config_file))
        assert result == {"scout": "openai/qwen36-27b"}
        assert "coder" not in result


# ---------------------------------------------------------------------------
# Backward compatibility test
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Ensure existing behavior is unchanged without YAML config."""

    def test_backward_compat_no_yaml_uses_global(self):
        """No YAML config, model set → all roles use global model."""
        state: OpenHandsGraphState = {
            "model": "openai/coder",
            "role": "scout",
        }
        # Without role_models in state, every role resolves to global model
        for role in ["scout", "research", "senior_staff_engineer", "architect", "coder", "qa", "reviewer", "publisher"]:
            assert _resolve_role_model(role, state) == "openai/coder"

    def test_backward_compat_no_yaml_no_global_none(self):
        """No YAML config, no global model → all roles resolve to None."""
        state: OpenHandsGraphState = {
            "role": "scout",
        }
        for role in ["scout", "research", "senior_staff_engineer", "architect", "coder", "qa", "reviewer", "publisher"]:
            assert _resolve_role_model(role, state) is None
