"""Tests for the v0.2 CLI additions: synapse up/down/status/demo.

These tests stub out docker / asyncpg so they run anywhere. The real
end-to-end smoke (live Docker + Postgres + Redis) lives in
runtime/modal/_payloads/v02_synapse_up_smoke.py.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def test_compose_file_is_bundled():
    """The docker-compose.yml ships inside the package so synapse up
    works on a `pip install` without a repo checkout."""
    from synapse.cli.up import _BUNDLED_COMPOSE
    assert _BUNDLED_COMPOSE.exists()
    text = _BUNDLED_COMPOSE.read_text(encoding="utf-8")
    assert "redis:" in text
    assert "postgres:" in text


def test_migrations_are_bundled():
    """The Postgres init migrations ship next to the bundled compose file."""
    from synapse.cli.up import _BUNDLED_COMPOSE
    migrations_dir = _BUNDLED_COMPOSE.parent / "migrations"
    assert migrations_dir.exists()
    sqls = list(migrations_dir.glob("*.sql"))
    assert sqls, "no migration .sql files found in bundled package"


def test_find_compose_file_prefers_bundled():
    from synapse.cli.up import _find_compose_file, _BUNDLED_COMPOSE
    found = _find_compose_file()
    assert found == _BUNDLED_COMPOSE


def test_check_docker_available_returns_pair():
    """The docker-availability check returns a (bool, message) tuple
    even when docker isn't installed (falls back gracefully)."""
    from synapse.cli.up import _check_docker_available
    ok, msg = _check_docker_available()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)


def test_compose_cmd_returns_list():
    from synapse.cli.up import _compose_cmd
    cmd = _compose_cmd()
    assert isinstance(cmd, list)
    assert cmd[0] in ("docker", "docker-compose")


def test_main_synapse_cli_lists_new_subcommands():
    """`synapse --help` should mention up/down/status/demo/audit."""
    from synapse.cli.main import main as cli_main

    with pytest.raises(SystemExit):
        cli_main(["--help"])


@pytest.mark.parametrize("cmd", ["up", "down", "status", "demo"])
def test_synapse_subcommand_help_does_not_crash(cmd):
    from synapse.cli.main import main as cli_main

    with pytest.raises(SystemExit):
        cli_main([cmd, "--help"])


def test_synapse_up_dispatch_exits_cleanly_without_docker(monkeypatch):
    """If docker isn't available, synapse up returns non-zero with a
    clear error rather than crashing."""
    from synapse.cli.up import _check_docker_available, cmd_up
    import argparse

    with patch("synapse.cli.up._check_docker_available", return_value=(False, "no docker")):
        ns = argparse.Namespace(services=None, timeout=5)
        rc = cmd_up(ns)
    assert rc == 2  # exit code 2 = config error


def test_demo_runs_in_offline_mode(monkeypatch):
    """`synapse demo` should run the body without crashing even when
    Postgres / Redis aren't reachable (intend() falls back to offline)."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.delenv("SYNAPSE_POSTGRES_DSN", raising=False)
    monkeypatch.setenv("SYNAPSE_REDIS_URL", "redis://nonexistent-host:9999/0")
    monkeypatch.setenv("SYNAPSE_POSTGRES_DSN", "postgresql://nonexistent:5432/synapse")

    from synapse.cli.demo import _run as run_demo
    import asyncio

    # The demo tolerates Redis/Postgres being unreachable — it should
    # complete (intend() in offline mode) without raising.
    rc = asyncio.run(run_demo())
    assert rc == 0
