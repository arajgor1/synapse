"""``synapse up / down / status`` — one-command local stack lifecycle.

Wraps ``docker compose`` with friendlier output and sane defaults so a
stranger can go from ``pip install synapse-protocol`` to a running
multi-agent stack in under 5 minutes.

Default services brought up:
  - Redis (message bus, port 6379)
  - Postgres (state graph, port 5432, auto-applies v0.1 migrations)
  - Synapse Router (L1 + L2 conflict detection)
  - Synapse Coordinator (belief divergence + cost telemetry)
  - Synapse Gateway (FastAPI WebSocket + REST)
  - Synapse UI (Next.js dashboard, port 3000)

Power users can pass ``--services redis postgres`` to bring up only the
infrastructure (everything else runs in-process from their app).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


# Where to look for the docker-compose stack. We bundle a copy with the
# package install so users don't need a repo checkout. The runtime image
# also reads from this path.
_BUNDLED_COMPOSE = Path(__file__).resolve().parent / "_data" / "docker-compose.yml"

# Repo-checkout fallback so people who cloned the repo can use synapse up
# from anywhere inside the tree.
def _find_compose_file() -> Optional[Path]:
    if _BUNDLED_COMPOSE.exists():
        return _BUNDLED_COMPOSE
    cwd = Path.cwd()
    for parent in (cwd, *cwd.parents):
        candidate = parent / "docker-compose.yml"
        if candidate.exists():
            return candidate
    return None


def _check_docker_available() -> tuple[bool, str]:
    """Verify docker + compose are present. Returns (ok, error_message)."""
    if shutil.which("docker") is None:
        return False, (
            "docker not found in PATH. Install Docker Desktop "
            "(https://www.docker.com/products/docker-desktop) and try again."
        )
    # Test the daemon is reachable
    try:
        proc = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return False, (
                "docker is installed but the daemon isn't responding. "
                "Start Docker Desktop and try again."
            )
    except Exception as e:
        return False, f"docker info failed: {e}"

    # Test `docker compose` (modern) or `docker-compose` (legacy)
    proc = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, text=True, timeout=10,
    )
    if proc.returncode == 0:
        return True, ""
    if shutil.which("docker-compose"):
        return True, ""
    return False, (
        "docker compose plugin not found. Install Docker Compose v2 "
        "(it ships with modern Docker Desktop)."
    )


def _compose_cmd() -> list[str]:
    proc = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, text=True, timeout=10,
    )
    if proc.returncode == 0:
        return ["docker", "compose"]
    return ["docker-compose"]


def cmd_up(args: argparse.Namespace) -> int:
    ok, err = _check_docker_available()
    if not ok:
        print(f"error: {err}", file=sys.stderr)
        return 2

    compose = _find_compose_file()
    if compose is None:
        print(
            "error: no docker-compose.yml found. Synapse needs one to bring up "
            "Redis + Postgres. Either:\n"
            "  - run from inside a synapse repo checkout (https://github.com/arajgor1/synapse), or\n"
            "  - copy docker-compose.yml from the repo to your working directory.",
            file=sys.stderr,
        )
        return 2

    print(f"synapse up — using {compose}")

    cmd = _compose_cmd() + ["-f", str(compose)]
    services = args.services if args.services else []

    print("  starting services...")
    proc = subprocess.run(
        cmd + ["up", "-d", *services], capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print("error: docker compose up failed:", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    print("  waiting for services to be healthy...")
    deadline = time.time() + args.timeout
    healthy = False
    while time.time() < deadline:
        ps = subprocess.run(
            cmd + ["-f", str(compose)] if False else cmd + ["ps", "--format", "json"],
            capture_output=True, text=True,
        )
        # Simple wait: just sleep a bit and check Redis/Postgres reachability via TCP
        try:
            import socket
            for port, name in [(6379, "redis"), (5432, "postgres")]:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(("127.0.0.1", port))
                s.close()
            healthy = True
            break
        except Exception:
            time.sleep(1)
            continue

    if not healthy:
        print(
            f"warning: services started but health check timed out after {args.timeout}s. "
            "Check `synapse status` for details.",
            file=sys.stderr,
        )
        return 1

    print()
    print("  Synapse stack is up:")
    print("    redis      → localhost:6379")
    print("    postgres   → localhost:5432  (user=synapse, db=synapse)")
    print()
    print("  Next steps:")
    print("    export SYNAPSE_REDIS_URL='redis://localhost:6379/0'")
    print("    export SYNAPSE_POSTGRES_DSN='postgresql://synapse:synapse_dev@localhost:5432/synapse'")
    print()
    print("  Now in your code:")
    print("    import synapse")
    print("    synapse.set_llm(synapse.from_anthropic())")
    print("    synapse.install(framework='langgraph')   # or crewai/autogen/etc.")
    print()
    print("  Stop the stack with:  synapse down")
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    compose = _find_compose_file()
    if compose is None:
        print("error: no docker-compose.yml found.", file=sys.stderr)
        return 2

    cmd = _compose_cmd() + ["-f", str(compose)]
    print("synapse down — stopping services...")
    flags = ["down"]
    if args.volumes:
        flags.append("-v")
    proc = subprocess.run(cmd + flags, capture_output=False, text=True)
    return proc.returncode


def cmd_status(args: argparse.Namespace) -> int:
    compose = _find_compose_file()
    if compose is None:
        print("error: no docker-compose.yml found.", file=sys.stderr)
        return 2

    cmd = _compose_cmd() + ["-f", str(compose), "ps"]
    proc = subprocess.run(cmd, capture_output=False, text=True)
    if proc.returncode != 0:
        return proc.returncode

    # Extra: show env vars users probably want set
    print()
    print("Environment:")
    print(f"  SYNAPSE_REDIS_URL    = {os.environ.get('SYNAPSE_REDIS_URL', '(unset — try redis://localhost:6379/0)')}")
    print(f"  SYNAPSE_POSTGRES_DSN = {os.environ.get('SYNAPSE_POSTGRES_DSN', '(unset — try postgresql://synapse:synapse_dev@localhost:5432/synapse)')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="synapse up",
        description="Bring up the local Synapse stack (Redis + Postgres + optional services).",
    )
    p.add_argument(
        "--services", nargs="+", default=None,
        help="Subset of services to start (default: all). Common: redis postgres.",
    )
    p.add_argument(
        "--timeout", type=int, default=30,
        help="Health-check timeout in seconds (default: 30)",
    )
    args = p.parse_args(argv)
    return cmd_up(args)
