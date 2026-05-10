"""Modal sandbox runner for testing Synapse integration with real agent
frameworks (OpenClaw, Paperclip AI, Hermes Agent).

Strategy:
- Provisions a clean Linux container per test
- Pre-installs Python 3.11, Node 20, git, redis-server, the Synapse Python SDK
- A single function per framework runs: clone -> install -> integrate -> test
- Captures stdout + status into a structured result
- Tears down after each test (CPU-only, ~$0.04/hour)

Run a single framework:
  modal run runtime/modal/framework_sandbox.py::run_hermes
  modal run runtime/modal/framework_sandbox.py::run_paperclip
  modal run runtime/modal/framework_sandbox.py::run_openclaw

Run all three:
  modal run runtime/modal/framework_sandbox.py::run_all

Each function is short-running (<10 minutes) and uses scaledown_window=10s
so the container disappears immediately after the test.
"""

from __future__ import annotations

import os
import time
from typing import Any

import modal

APP_NAME = "synapse-framework-sandbox"
SDK_VOLUME = modal.Volume.from_name("synapse-sdk-cache", create_if_missing=True)

# Image with everything we need to clone + install + run any of the three
# frameworks. Built once, reused across runs.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "git", "curl", "build-essential", "ca-certificates",
        "redis-server",
        "postgresql-15", "postgresql-client-15",
        # Node 20 for Paperclip
        "ca-certificates", "gnupg",
    )
    .run_commands(
        # Install Node 20.x
        "curl -fsSL https://deb.nodesource.com/setup_20.x | bash -",
        "apt-get install -y nodejs",
        # Verify
        "node --version && npm --version && python3 --version",
    )
    .pip_install(
        # Synapse SDK runtime deps so the user-facing SDK works
        "pydantic>=2.6,<3",
        "redis[hiredis]>=5.0,<6",
        "asyncpg>=0.29,<0.31",
        "python-ulid>=2.2,<4",
        "jsonschema>=4.20",
        "anthropic>=0.40",
        "google-genai>=1.0",
        "openai>=1.50",
        "httpx>=0.27",
        # Common framework deps that often surface
        "fastapi>=0.115",
        "uvicorn[standard]>=0.30",
        # v0.2 Week 2: LangGraph live tests
        "langchain-core>=0.3",
        "langgraph>=0.2",
        "langchain-anthropic>=0.2",
        # v0.2 Week 3a: CrewAI live test
        "crewai>=0.86,<0.130",
    )
    .add_local_dir(
        # Mount the Synapse SDK source so we can `pip install -e` inside
        local_path=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "sdk-python")),
        remote_path="/opt/synapse-sdk",
        copy=True,
    )
    .add_local_dir(
        # Mount runtime/ such that `import runtime` works from sys.path=/opt
        local_path=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        remote_path="/opt/runtime",
        copy=True,
    )
    .add_local_dir(
        # Pre-baked test payloads for product-dev scenarios
        local_path=os.path.abspath(os.path.join(os.path.dirname(__file__), "_payloads")),
        remote_path="/opt/synapse-payloads",
        copy=True,
    )
    .add_local_dir(
        # Mount the TS SDK source so we can build + link it inside
        local_path=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "sdk-typescript")),
        remote_path="/opt/synapse-ts-sdk",
        copy=True,
    )
    .add_local_dir(
        # Mount Stripe Lite v2 starter for CI-loop test
        local_path=os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..",
            "bench", "scenarios", "stripe_lite_v2", "starter",
        )),
        remote_path="/opt/stripe_lite_v2_starter",
        copy=True,
    )
)

app = modal.App(APP_NAME, image=image)

# Each test gets ~10 min max
TEST_TIMEOUT = 600


def _common_setup_script() -> str:
    """Bash to run at the start of every framework test."""
    return r"""
set -euo pipefail
echo "=== Sandbox setup ==="
python3 --version
node --version
npm --version
echo "Installing Synapse SDK..."
cd /opt/synapse-sdk
pip install -e . 2>&1 | tail -5
python3 -c "import synapse; print(f'  synapse v{synapse.__version__} importable')"

# Start a local Redis (background; we have Postgres if needed too)
mkdir -p /tmp/redis-data
redis-server --daemonize yes --dir /tmp/redis-data --logfile /tmp/redis.log
sleep 0.5
redis-cli ping
echo "  redis ready"

# Init in-image Postgres for Synapse state graph (small, local)
mkdir -p /var/lib/postgresql/data
chown postgres:postgres /var/lib/postgresql/data
su postgres -c "/usr/lib/postgresql/15/bin/initdb -D /var/lib/postgresql/data --auth=trust" 2>&1 | tail -3 || true
su postgres -c "/usr/lib/postgresql/15/bin/pg_ctl -D /var/lib/postgresql/data -l /tmp/pg.log start" 2>&1 | tail -3
sleep 1
su postgres -c "createuser -s synapse" 2>&1 || true
su postgres -c "createdb synapse -O synapse" 2>&1 || true
su postgres -c "psql -d synapse -c \"ALTER USER synapse WITH PASSWORD 'synapse_dev'\""
echo "  postgres ready"

# Apply Synapse schema
psql -h /var/run/postgresql -U synapse -d synapse -f /opt/synapse-sdk/../runtime/migrations/0001_initial_schema.sql 2>&1 | tail -3 || true

export SYNAPSE_REDIS_URL="redis://localhost:6379/0"
export SYNAPSE_POSTGRES_DSN="postgresql://synapse:synapse_dev@localhost:5432/synapse"
"""


@app.function(
    cpu=2.0,
    memory=2048,
    timeout=TEST_TIMEOUT,
    scaledown_window=10,
)
def run_hermes(api_keys: dict[str, str]) -> dict[str, Any]:
    """Test Synapse integration with Hermes Agent (NousResearch).

    Strategy:
    1. Clone https://github.com/NousResearch/hermes-agent
    2. Install (pip install -e .)
    3. Inspect agent/ + acp_adapter/ modules — those are the subagent spawn APIs
    4. Locate the exact function we'd wrap with Synapse coordination
    5. Run a small Python script that imports Hermes + wires Synapse
    """
    import subprocess
    import textwrap

    setup = _common_setup_script()

    framework_script = textwrap.dedent(r"""
        export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"

        echo "=== Cloning Hermes Agent ==="
        cd /tmp
        git clone --depth 1 https://github.com/NousResearch/hermes-agent.git
        cd /tmp/hermes-agent

        echo "=== Installing (pip install -e .) ==="
        pip install -e . 2>&1 | tail -3

        echo
        echo "=== agent/ module structure ==="
        ls -la agent/ 2>/dev/null
        echo
        echo "=== acp_adapter/ module structure ==="
        ls -la acp_adapter/ 2>/dev/null
        echo
        echo "=== Top public symbols in agent/__init__.py ==="
        head -80 agent/__init__.py 2>/dev/null
        echo
        echo "=== Top public symbols in acp_adapter/session.py ==="
        head -120 acp_adapter/session.py 2>/dev/null
        echo
        echo "=== Look for the spawn/delegate function ==="
        grep -nE "(async )?def (spawn|delegate|dispatch|run_subagent|run_task)" agent/*.py acp_adapter/*.py 2>/dev/null
        echo
        echo "=== Tool-call dispatch site (where actions are executed) ==="
        grep -rnE "tool.*call|call_tool|execute_tool|invoke_tool" --include='*.py' agent/ acp_adapter/ 2>/dev/null | head -15
        echo
        echo "=== Static analysis of agent/ + acp_adapter/ ==="
        echo
        echo "-- agent/ files and their top symbols --"
        for f in agent/*.py; do
          [ -f "$f" ] || continue
          echo
          echo "  ~~ $f ~~"
          grep -nE "^(class|def|async def) " "$f" | head -10
        done
        echo
        echo "-- acp_adapter/ files and their top symbols --"
        for f in acp_adapter/*.py; do
          [ -f "$f" ] || continue
          echo
          echo "  ~~ $f ~~"
          grep -nE "^(class|def|async def) " "$f" | head -10
        done
        echo
        echo "=== Searching for the subagent dispatch site ==="
        grep -rnE "(spawn|delegate|dispatch|run_subagent|run_agent|new_agent|create_agent|sub_agent)" --include='*.py' agent/ acp_adapter/ 2>/dev/null | head -25
        echo
        echo "=== Tool-call / function-call dispatch (where actions actually fire) ==="
        grep -rnE "(call_tool|execute_tool|invoke_tool|run_tool|tool_call|function_call)" --include='*.py' agent/ acp_adapter/ skills/ 2>/dev/null | head -20
        echo
        echo "=== Tools list ==="
        ls -la skills/ 2>/dev/null | head -25 || true
        ls -la tools/ 2>/dev/null | head -25 || true
        echo
        echo "=== Hermes can be imported ==="
        python3 -c "import agent; print('  agent module:', agent)" 2>&1 | head -3
        python3 -c "import acp_adapter; print('  acp_adapter module:', acp_adapter)" 2>&1 | head -3
    """)

    full_script = setup + framework_script
    env = dict(os.environ)
    if api_keys.get("ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = api_keys["ANTHROPIC_API_KEY"]

    started = time.time()
    try:
        proc = subprocess.run(
            ["bash", "-c", full_script],
            capture_output=True, text=True, timeout=480, env=env,
        )
        return {
            "framework": "hermes",
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-15000:],  # last 15KB
            "stderr": proc.stderr[-5000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "framework": "hermes",
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-15000:],
            "stderr": "TIMEOUT after 480s",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.function(
    cpu=2.0,
    memory=2048,
    timeout=TEST_TIMEOUT,
    scaledown_window=10,
)
def run_paperclip(api_keys: dict[str, str]) -> dict[str, Any]:
    """Test Synapse integration with Paperclip AI (Node.js + React).

    Strategy:
    1. Clone https://github.com/paperclipai/paperclip
    2. npm install
    3. Identify task assignment / agent execution layer
    4. Wire @synapse-protocol/sdk (TypeScript SDK) into Paperclip's
       task lifecycle hooks
    5. Run a small scenario with two agents on overlapping scopes
    """
    import subprocess
    import textwrap

    setup = _common_setup_script()

    framework_script = textwrap.dedent(r"""
        echo "=== Cloning Paperclip AI ==="
        cd /tmp
        git clone --depth 1 https://github.com/paperclipai/paperclip.git
        cd paperclip
        echo "=== Paperclip repo layout ==="
        ls -la
        echo
        echo "=== package.json scripts + deps ==="
        cat package.json 2>/dev/null | python3 -c "
import json,sys
try:
  d = json.load(sys.stdin)
  print('  name:', d.get('name'))
  print('  scripts:', list((d.get('scripts') or {}).keys()))
  print('  deps:', list((d.get('dependencies') or {}).keys())[:15])
except Exception as e:
  print('parse fail:', e)
" || true
        echo
        echo "=== Looking for agent task execution hooks ==="
        find . -maxdepth 5 -name '*.ts' -o -name '*.js' 2>/dev/null | head -20
        echo
        grep -rEn "task\.execute|run_agent|spawn|dispatch|coordinator" --include="*.ts" --include="*.js" -l 2>/dev/null | head -8
        echo
        echo "=== npm install (this may take a while) ==="
        npm install --prefer-offline --no-audit --no-fund --loglevel=error 2>&1 | tail -10 || \
          echo "npm install hit issues; continuing for diagnostic info"
        echo
        echo "=== Source exploration: top-level ts/js files ==="
        find . -maxdepth 3 \( -name "*.ts" -o -name "*.js" \) -not -path "./node_modules/*" | head -15
    """)

    full_script = setup + framework_script
    env = dict(os.environ)
    if api_keys.get("ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = api_keys["ANTHROPIC_API_KEY"]
    if api_keys.get("OPENAI_API_KEY"):
        env["OPENAI_API_KEY"] = api_keys["OPENAI_API_KEY"]

    started = time.time()
    try:
        proc = subprocess.run(
            ["bash", "-c", full_script],
            capture_output=True, text=True, timeout=480, env=env,
        )
        return {
            "framework": "paperclip",
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-15000:],
            "stderr": proc.stderr[-5000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "framework": "paperclip",
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-15000:],
            "stderr": "TIMEOUT after 480s",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.function(
    cpu=2.0,
    memory=2048,
    timeout=TEST_TIMEOUT,
    scaledown_window=10,
)
def run_openclaw(api_keys: dict[str, str]) -> dict[str, Any]:
    """Test Synapse integration with OpenClaw.

    Strategy:
    1. Clone https://github.com/openclaw/openclaw
    2. Identify SOUL.md template loader and tool-call layer
    3. Plan integration at the tool-call site (emit INTENTION before each
       file/API/DB action; check for CONFLICT)
    """
    import subprocess
    import textwrap

    setup = _common_setup_script()

    framework_script = textwrap.dedent(r"""
        echo "=== Cloning OpenClaw ==="
        cd /tmp
        git clone --depth 1 https://github.com/openclaw/openclaw.git
        cd openclaw
        echo "=== OpenClaw repo layout ==="
        ls -la
        echo
        echo "=== Detecting language + entrypoint ==="
        for f in package.json pyproject.toml setup.py Cargo.toml go.mod; do
          [ -f "$f" ] && echo "  found: $f" && head -30 "$f"
        done
        echo
        echo "=== SOUL.md template directory ==="
        find . -maxdepth 4 \( -name "*.soul.md" -o -name "soul.md" -o -iname "SOUL.md" \) 2>/dev/null | head -10
        find . -type d -iname "*soul*" 2>/dev/null | head -5
        echo
        echo "=== Searching for tool-call layer ==="
        grep -rEn "tool.*call|call.*tool|execute.*tool|tool_use" --include="*.ts" --include="*.py" --include="*.js" --include="*.rs" -l 2>/dev/null | head -10
        echo
        echo "=== Trying installation ==="
        if [ -f package.json ]; then
            npm install --prefer-offline --no-audit --no-fund --loglevel=error 2>&1 | tail -5 || echo "npm hit issues"
        elif [ -f pyproject.toml ] || [ -f setup.py ]; then
            pip install -e . 2>&1 | tail -5 || echo "pip hit issues"
        elif [ -f Cargo.toml ]; then
            echo "Rust-based; build skipped (would take too long in sandbox)"
        elif [ -f go.mod ]; then
            echo "Go-based; build skipped (would need go toolchain install)"
        else
            echo "no recognized build manifest at top level"
        fi
        echo
        echo "=== README excerpt ==="
        find . -maxdepth 1 -iname 'README*' | head -1 | xargs cat 2>/dev/null | head -60 || true
    """)

    full_script = setup + framework_script
    env = dict(os.environ)
    if api_keys.get("ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = api_keys["ANTHROPIC_API_KEY"]

    started = time.time()
    try:
        proc = subprocess.run(
            ["bash", "-c", full_script],
            capture_output=True, text=True, timeout=480, env=env,
        )
        return {
            "framework": "openclaw",
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-15000:],
            "stderr": proc.stderr[-5000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "framework": "openclaw",
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-15000:],
            "stderr": "TIMEOUT after 480s",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.local_entrypoint()
def run_all() -> None:
    """Drive all three tests, save results to bench/results/."""
    import json
    import os
    import sys
    import time

    # Pull API keys from local env (passed through to remote)
    api_keys = {
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
    }

    print("\n=== Running framework integration tests in Modal sandboxes ===")
    print(f"  Anthropic key set: {bool(api_keys['ANTHROPIC_API_KEY'])}")
    print(f"  OpenAI key set:    {bool(api_keys['OPENAI_API_KEY'])}")
    print()

    results = []
    for name, fn in [
        ("hermes", run_hermes),
        ("paperclip", run_paperclip),
        ("openclaw", run_openclaw),
    ]:
        print(f">>> [{name}] starting sandbox...")
        t0 = time.time()
        result = fn.remote(api_keys)
        elapsed = time.time() - t0
        print(f"<<< [{name}] exit={result['exit_code']} elapsed={elapsed:.1f}s")
        # Surface the last 50 lines of stdout for visibility
        tail = "\n".join(result["stdout"].splitlines()[-50:])
        print(tail)
        print(f"--- end {name} ---\n")
        results.append(result)

    # Save consolidated results
    out_dir = "bench/results"
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(out_dir, f"framework_sandbox_phase1_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nresults saved -> {path}")


@app.function(
    cpu=2.0, memory=2048, timeout=TEST_TIMEOUT, scaledown_window=10,
)
def fetch_integration_docs() -> dict[str, Any]:
    """Pull integration-relevant docs/source from all three frameworks
    so I can build adapters offline."""
    import subprocess
    import textwrap

    script = textwrap.dedent(r"""
        set -uo pipefail
        cd /tmp
        mkdir -p /tmp/docs
        echo "=== Paperclip adapter-plugin.md ==="
        git clone --depth 1 https://github.com/paperclipai/paperclip.git 2>&1 | tail -2
        echo
        echo "--- adapter-plugin.md ---"
        cat paperclip/adapter-plugin.md 2>/dev/null
        echo
        echo "--- AGENTS.md (top 80) ---"
        head -80 paperclip/AGENTS.md 2>/dev/null
        echo
        echo "--- packages/ contents ---"
        ls -la paperclip/packages/ 2>/dev/null
        echo
        echo "--- README highlights (multi-agent + adapter sections) ---"
        grep -nE "(adapter|plugin|coord|multi-agent|integrate)" paperclip/README.md 2>/dev/null | head -25
        echo
        echo "--- skills/openclaw-* (the existing OpenClaw integration) ---"
        find paperclip/skills -maxdepth 2 -iname '*openclaw*' 2>/dev/null
        find paperclip -maxdepth 4 -name '*openclaw*' -type f 2>/dev/null | head -10
        echo
        echo "=== Hermes agent: tool-call dispatch site ==="
        git clone --depth 1 https://github.com/NousResearch/hermes-agent.git 2>&1 | tail -2
        echo
        echo "--- agent/__init__.py (full) ---"
        cat hermes-agent/agent/__init__.py
        echo
        echo "--- acp_adapter/tools.py first 120 lines ---"
        head -120 hermes-agent/acp_adapter/tools.py
        echo
        echo "--- Search for the tool-execution function ---"
        grep -nE "^(async )?def .*(execute|invoke|call|run|dispatch|handle)_(tool|function|command)" hermes-agent/agent/*.py hermes-agent/acp_adapter/*.py 2>/dev/null | head -15
        echo
        echo "=== OpenClaw extension/plugin pattern ==="
        # Don't re-clone OpenClaw (huge); use a sparse checkout for specific files
        git clone --depth 1 --filter=blob:none --sparse https://github.com/openclaw/openclaw.git openclaw-sparse 2>&1 | tail -1
        cd openclaw-sparse
        git sparse-checkout set extensions/browser docs README.md 2>&1 | tail -1
        echo
        echo "--- README highlights ---"
        head -80 README.md 2>/dev/null
        echo
        echo "--- extensions/browser/plugin-registration.ts (the canonical plugin example) ---"
        head -120 extensions/browser/plugin-registration.ts 2>/dev/null
        echo
        echo "--- SOUL.md template doc ---"
        head -150 docs/reference/templates/SOUL.md 2>/dev/null
        echo
        echo "--- Plugin registration API surface (grep across extensions) ---"
        grep -nE "(registerPlugin|registerTool|definePlugin|defineExtension|export.*default)" extensions/browser/*.ts 2>/dev/null | head -20
    """)

    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=TEST_TIMEOUT,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-50000:],
            "stderr": proc.stderr[-3000:],
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-50000:],
            "stderr": "TIMEOUT",
        }


@app.function(
    cpu=4.0, memory=4096, timeout=900, scaledown_window=10,
)
def real_product_dev_hermes(api_keys: dict[str, str]) -> dict[str, Any]:
    """REAL product-dev test: 3 agents (architect, backend, qa) building a
    shared Todo data model via REAL Anthropic Haiku calls + REAL Synapse
    integration. Compares no_synapse vs with_synapse modes; measures
    alignment / conflicts caught / envelopes / token spend.
    """
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    # The actual scenario lives in /opt/synapse-payloads/real_product_dev_hermes.py
    script = setup + "\n\npython3 /opt/synapse-payloads/real_product_dev_hermes.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=900, env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-30000:],
            "stderr": proc.stderr[-3000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-30000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.function(
    cpu=4.0, memory=4096, timeout=900, scaledown_window=10,
)
def real_product_dev_paperclip(api_keys: dict[str, str]) -> dict[str, Any]:
    """REAL product-dev test for the Paperclip integration.

    3 distinct Paperclip agents (engineer_a/b/c) each invoke their wrapped
    adapter to design the SAME endpoint. wrapAdapterWithSynapse intercepts
    every dispatch with INTENTION; a Python sidecar mirrors INTENTIONs to
    Postgres so the L2 router can detect conflicts and route CONFLICTs to
    per-agent Redis inboxes.

    Compares no_synapse vs with_synapse modes; measures distinct routes
    chosen / conflicts caught / envelopes / token spend.
    """
    import subprocess
    import textwrap

    started = time.time()
    setup = _common_setup_script()

    framework_script = textwrap.dedent(r"""
        export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"

        echo "=== Building TS SDK ==="
        cp -r /opt/synapse-ts-sdk /tmp/synapse-ts-sdk
        cd /tmp/synapse-ts-sdk
        npm install --prefer-offline --no-audit --no-fund --loglevel=error 2>&1 | tail -3
        # Permission-denied workaround: invoke tsc via node directly (some
        # mounts strip the executable bit on shebang scripts)
        node ./node_modules/typescript/bin/tsc 2>&1 | tail -10
        ls -la dist/ | head -10

        echo "=== Wiring test app (anthropic + linked SDK) ==="
        mkdir -p /tmp/pp-test
        cd /tmp/pp-test
        cat > package.json <<'EOF'
        {
          "name": "pp-test",
          "version": "1.0.0",
          "type": "module",
          "private": true,
          "dependencies": {
            "@anthropic-ai/sdk": "^0.40.0",
            "@synapse-protocol/sdk": "file:/tmp/synapse-ts-sdk",
            "ioredis": "^5.4.1"
          }
        }
        EOF
        npm install --prefer-offline --no-audit --no-fund --loglevel=error 2>&1 | tail -3

        cp /opt/synapse-payloads/real_product_dev_paperclip.mjs /tmp/pp-test/test.mjs

        echo "=== Starting Python state-mirror + router for the synapse session ==="
        SESSION_ID="paperclip_pd_$(date +%s)_$$"
        export SYNAPSE_SESSION_ID="$SESSION_ID"
        echo "  session: $SESSION_ID"

        python3 /opt/synapse-payloads/state_mirror.py "$SESSION_ID" \
          > /tmp/state_mirror.log 2>&1 &
        MIRROR_PID=$!
        sleep 1
        if ! kill -0 $MIRROR_PID 2>/dev/null; then
          echo "ERROR: state_mirror failed to start; log:"
          cat /tmp/state_mirror.log
          exit 1
        fi
        echo "  state_mirror PID=$MIRROR_PID"

        echo
        echo "=== Running real product-dev test (Node) ==="
        cd /tmp/pp-test
        node test.mjs 2>&1
        TEST_RC=$?

        echo
        echo "=== state_mirror log (last 30 lines) ==="
        tail -30 /tmp/state_mirror.log

        kill $MIRROR_PID 2>/dev/null || true
        wait $MIRROR_PID 2>/dev/null || true
        exit $TEST_RC
    """)

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    try:
        proc = subprocess.run(
            ["bash", "-c", setup + framework_script],
            capture_output=True, text=True, timeout=900, env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-30000:],
            "stderr": proc.stderr[-5000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-30000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.function(
    cpu=4.0, memory=4096, timeout=900, scaledown_window=10,
)
def real_product_dev_openclaw(api_keys: dict[str, str]) -> dict[str, Any]:
    """REAL product-dev test for the OpenClaw integration.

    3 OpenClaw extensions, each wrapped with wrapExtensionWithSynapse and
    a distinct agentId. Each handler calls real Anthropic Haiku to write a
    Python helper, all writing to the same path. defaultScope() maps the
    path → repo.fs.<path>:w so the L2 router catches the collision.
    """
    import subprocess
    import textwrap

    started = time.time()
    setup = _common_setup_script()

    framework_script = textwrap.dedent(r"""
        export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"

        echo "=== Building TS SDK ==="
        cp -r /opt/synapse-ts-sdk /tmp/synapse-ts-sdk
        cd /tmp/synapse-ts-sdk
        npm install --prefer-offline --no-audit --no-fund --loglevel=error 2>&1 | tail -3
        node ./node_modules/typescript/bin/tsc 2>&1 | tail -5
        ls -la dist/ | head -5

        echo "=== Wiring test app (anthropic + linked SDK) ==="
        mkdir -p /tmp/oc-test
        cd /tmp/oc-test
        cat > package.json <<'EOF'
        {
          "name": "oc-test",
          "version": "1.0.0",
          "type": "module",
          "private": true,
          "dependencies": {
            "@anthropic-ai/sdk": "^0.40.0",
            "@synapse-protocol/sdk": "file:/tmp/synapse-ts-sdk",
            "ioredis": "^5.4.1"
          }
        }
        EOF
        npm install --prefer-offline --no-audit --no-fund --loglevel=error 2>&1 | tail -3

        cp /opt/synapse-payloads/real_product_dev_openclaw.mjs /tmp/oc-test/test.mjs

        echo "=== Starting Python state-mirror + router ==="
        SESSION_ID="openclaw_pd_$(date +%s)_$$"
        export SYNAPSE_SESSION_ID="$SESSION_ID"
        echo "  session: $SESSION_ID"

        python3 /opt/synapse-payloads/state_mirror.py "$SESSION_ID" \
          > /tmp/state_mirror.log 2>&1 &
        MIRROR_PID=$!
        sleep 1
        if ! kill -0 $MIRROR_PID 2>/dev/null; then
          echo "ERROR: state_mirror failed to start; log:"
          cat /tmp/state_mirror.log
          exit 1
        fi

        echo
        echo "=== Running real product-dev test (Node) ==="
        cd /tmp/oc-test
        node test.mjs 2>&1
        TEST_RC=$?

        echo
        echo "=== state_mirror log (last 30 lines) ==="
        tail -30 /tmp/state_mirror.log

        kill $MIRROR_PID 2>/dev/null || true
        wait $MIRROR_PID 2>/dev/null || true
        exit $TEST_RC
    """)

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    try:
        proc = subprocess.run(
            ["bash", "-c", setup + framework_script],
            capture_output=True, text=True, timeout=900, env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-30000:],
            "stderr": proc.stderr[-5000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-30000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.function(
    cpu=4.0, memory=4096, timeout=900, scaledown_window=10,
)
def real_app_instagram(api_keys: dict[str, str]) -> dict[str, Any]:
    """Realistic multi-step product-dev workload: 4 specialist engineer
    agents (db / api / auth / feed) collaboratively build an Instagram-
    clone FastAPI backend, each doing 3 sequential LLM-driven file writes.
    Natural overlaps: models/user.py touched by db+api+auth (3-way),
    api/posts.py touched by api+feed (2-way).
    """
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\npython3 /opt/synapse-payloads/real_app_instagram.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=900, env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-50000:],
            "stderr": proc.stderr[-3000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-50000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.function(
    cpu=4.0, memory=4096, timeout=900, scaledown_window=10,
)
def real_app_data_analysis(api_keys: dict[str, str]) -> dict[str, Any]:
    """Realistic multi-agent data-team workload: data_loader, data_cleaner,
    analyst, visualizer collaboratively build a sales analysis report.
    Natural collisions on column-name vocabulary and derived `revenue`
    column (different formulas).
    """
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\npython3 /opt/synapse-payloads/real_app_data_analysis.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=900, env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-50000:],
            "stderr": proc.stderr[-3000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-50000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.local_entrypoint()
def app_data_analysis() -> None:
    """Run the realistic 4-agent data-analysis pipeline test."""
    import json
    import os
    import time

    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return
    print(">>> running realistic 4-agent data-analysis pipeline test...")
    r = real_app_data_analysis.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    if r.get("stderr"):
        print("\n--- stderr ---")
        print(r["stderr"][:2000])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"real_app_data_analysis_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {path}")


@app.local_entrypoint()
def app_instagram() -> None:
    """Run the realistic 4-agent Instagram-clone backend test."""
    import json
    import os
    import time

    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return
    print(">>> running realistic 4-agent Instagram-clone backend test...")
    r = real_app_instagram.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    if r.get("stderr"):
        print("\n--- stderr ---")
        print(r["stderr"][:2000])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"real_app_instagram_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {path}")


@app.local_entrypoint()
def product_dev_openclaw() -> None:
    """Run real_product_dev_openclaw against a Modal sandbox."""
    import json
    import os
    import time

    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return

    print(">>> running real product-dev openclaw test in Modal sandbox...")
    r = real_product_dev_openclaw.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    if r.get("stderr"):
        print("\n--- stderr ---")
        print(r["stderr"][:2000])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"product_dev_real_openclaw_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {path}")


@app.function(
    cpu=4.0, memory=4096, timeout=900, scaledown_window=10,
)
def v02_langgraph_live(api_keys: dict[str, str]) -> dict[str, Any]:
    """v0.2 Week 2: real LangGraph + real Anthropic Haiku + synapse.install().

    Validates the Week-2 success metric: LangGraph user wires Synapse in
    3 lines and sees live conflicts in their dashboard.
    """
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\npython3 /opt/synapse-payloads/v02_langgraph_live.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=900, env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-50000:],
            "stderr": proc.stderr[-3000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-50000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.function(
    cpu=4.0, memory=4096, timeout=900, scaledown_window=10,
)
def v02_crewai_live(api_keys: dict[str, str]) -> dict[str, Any]:
    """v0.2 Week 3a: real CrewAI 3-agent crew + real Anthropic Haiku +
    synapse.install(framework='crewai')."""
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\npython3 /opt/synapse-payloads/v02_crewai_live.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=900, env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-50000:],
            "stderr": proc.stderr[-3000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-50000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.function(
    cpu=4.0, memory=4096, timeout=900, scaledown_window=10,
)
def v02_week3_full(api_keys: dict[str, str]) -> dict[str, Any]:
    """Week 3 full integration test: LangGraph + CrewAI on the same Synapse
    session simultaneously."""
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\npython3 /opt/synapse-payloads/v02_week3_full.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=900, env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-50000:],
            "stderr": proc.stderr[-3000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-50000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.function(
    cpu=4.0, memory=4096, timeout=900, scaledown_window=10,
)
def v02_w4_auto_merge(api_keys: dict[str, str]) -> dict[str, Any]:
    """v0.2 Week 4: Instagram-clone with MergePolicy.auto_merge.

    Headline demo — same workload as v0.1 with 3 silently-overwriting
    engineers, but with auto_merge configured the final models/user.py
    contains all engineers' fields instead of just the last writer's.
    """
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\npython3 /opt/synapse-payloads/v02_w4_auto_merge.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=900, env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-60000:],
            "stderr": proc.stderr[-3000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-60000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.function(
    cpu=4.0, memory=4096, timeout=900, scaledown_window=10,
)
def v02_w5_belief_divergence(api_keys: dict[str, str]) -> dict[str, Any]:
    """v0.2 Week 5: BELIEF divergence on semantic conflicts (no scope overlap)."""
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\npython3 /opt/synapse-payloads/v02_w5_belief_divergence.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=900, env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-60000:],
            "stderr": proc.stderr[-3000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-60000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.function(
    cpu=4.0, memory=4096, timeout=2400, scaledown_window=10,
)
def v02_autonomous_observer_run(api_keys: dict[str, str]) -> dict[str, Any]:
    """Autonomous observer test — real orchestrator + workers build mini-Stripe
    while Synapse watches. Returns capture artifacts inlined so the host can
    persist them.

    Streams subprocess stdout line-by-line to the function's own stdout so
    Modal logs surface live progress. The whole stream is also accumulated
    and returned at the end.
    """
    import base64
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\nstdbuf -oL python3 -u /opt/synapse-payloads/v02_autonomous_observer.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    env["PYTHONUNBUFFERED"] = "1"
    captured: list[str] = []
    try:
        proc = subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None:
                    break
                continue
            print(line.rstrip(), flush=True)  # surfaces in Modal logs
            captured.append(line)
            if time.time() - started > 2400:
                proc.terminate()
                return {
                    "exit_code": -1,
                    "stdout": "".join(captured)[-100000:],
                    "stderr": "TIMEOUT",
                    "elapsed_seconds": round(time.time() - started, 1),
                    "captures": {},
                }
        proc.wait()
    except Exception as e:
        return {
            "exit_code": -2,
            "stdout": "".join(captured)[-100000:],
            "stderr": f"streaming exception: {e}",
            "elapsed_seconds": round(time.time() - started, 1),
            "captures": {},
        }
    proc_returncode = proc.returncode
    proc_stdout_full = "".join(captured)

    captures_dir = "/tmp/v02_auto_captures"
    captures: dict[str, str] = {}
    if os.path.isdir(captures_dir):
        for name in os.listdir(captures_dir):
            full = os.path.join(captures_dir, name)
            if os.path.isfile(full):
                try:
                    with open(full, "rb") as f:
                        captures[name] = base64.b64encode(f.read()).decode("ascii")
                except Exception:
                    pass

    return {
        "exit_code": proc_returncode,
        "stdout": proc_stdout_full[-100000:],
        "stderr": "",
        "elapsed_seconds": round(time.time() - started, 1),
        "captures": captures,
    }


@app.function(
    cpu=4.0, memory=4096, timeout=2400, scaledown_window=10,
)
def v02_multi_orchestrator_run(api_keys: dict[str, str]) -> dict[str, Any]:
    """Multi-orchestrator natural workload — two independent teams, no
    shared coordinator, same codebase."""
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\nstdbuf -oL python3 -u /opt/synapse-payloads/v02_multi_orchestrator.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    env["PYTHONUNBUFFERED"] = "1"
    captured: list[str] = []
    try:
        proc = subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None:
                    break
                continue
            print(line.rstrip(), flush=True)
            captured.append(line)
            if time.time() - started > 2400:
                proc.terminate()
                return {
                    "exit_code": -1,
                    "stdout": "".join(captured)[-100000:],
                    "stderr": "TIMEOUT",
                    "elapsed_seconds": round(time.time() - started, 1),
                }
        proc.wait()
    except Exception as e:
        return {
            "exit_code": -2,
            "stdout": "".join(captured)[-100000:],
            "stderr": f"streaming exception: {e}",
            "elapsed_seconds": round(time.time() - started, 1),
        }

    return {
        "exit_code": proc.returncode,
        "stdout": "".join(captured)[-100000:],
        "stderr": "",
        "elapsed_seconds": round(time.time() - started, 1),
    }


@app.function(
    cpu=4.0, memory=4096, timeout=2400, scaledown_window=10,
)
def v02_ci_loop_run(api_keys: dict[str, str]) -> dict[str, Any]:
    """Real CI/CD loop test — Option A. Two LangGraph crews + pytest in
    the loop. ci_only vs ci_plus_synapse."""
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    # Need pytest + httpx + sqlalchemy + fastapi for the Stripe Lite v2 tests
    extra = (
        "\npython3 -m pip install -q "
        "fastapi 'sqlalchemy>=2.0' 'pydantic>=2.6' httpx pytest 'uvicorn>=0.29' "
        ">/dev/null 2>&1 || true\n"
    )
    script = setup + extra + "\n\nstdbuf -oL python3 -u /opt/synapse-payloads/v02_ci_loop.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    env["PYTHONUNBUFFERED"] = "1"
    captured: list[str] = []
    try:
        proc = subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None:
                    break
                continue
            print(line.rstrip(), flush=True)
            captured.append(line)
            if time.time() - started > 2400:
                proc.terminate()
                return {
                    "exit_code": -1,
                    "stdout": "".join(captured)[-100000:],
                    "stderr": "TIMEOUT",
                    "elapsed_seconds": round(time.time() - started, 1),
                }
        proc.wait()
    except Exception as e:
        return {
            "exit_code": -2,
            "stdout": "".join(captured)[-100000:],
            "stderr": f"streaming exception: {e}",
            "elapsed_seconds": round(time.time() - started, 1),
        }

    return {
        "exit_code": proc.returncode,
        "stdout": "".join(captured)[-100000:],
        "stderr": "",
        "elapsed_seconds": round(time.time() - started, 1),
    }


@app.function(
    cpu=4.0, memory=4096, timeout=2400, scaledown_window=10,
)
def v02_strands_real_run(api_keys: dict[str, str]) -> dict[str, Any]:
    """Real Strands Agents test — Option C. Validates synapse.install(framework='strands')
    against the real strands-agents package."""
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\nstdbuf -oL python3 -u /opt/synapse-payloads/v02_strands_real.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    env["PYTHONUNBUFFERED"] = "1"
    captured: list[str] = []
    try:
        proc = subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None:
                    break
                continue
            print(line.rstrip(), flush=True)
            captured.append(line)
            if time.time() - started > 2400:
                proc.terminate()
                return {
                    "exit_code": -1,
                    "stdout": "".join(captured)[-100000:],
                    "stderr": "TIMEOUT",
                    "elapsed_seconds": round(time.time() - started, 1),
                }
        proc.wait()
    except Exception as e:
        return {
            "exit_code": -2,
            "stdout": "".join(captured)[-100000:],
            "stderr": f"streaming exception: {e}",
            "elapsed_seconds": round(time.time() - started, 1),
        }

    return {
        "exit_code": proc.returncode,
        "stdout": "".join(captured)[-100000:],
        "stderr": "",
        "elapsed_seconds": round(time.time() - started, 1),
    }


@app.function(
    cpu=4.0, memory=8192, timeout=3600, scaledown_window=10,
)
def v022_framework_races_run(api_keys: dict[str, str]) -> dict[str, Any]:
    """Real-life autonomous race tests for all 11 framework adapters.

    For each framework: spawns 2 agents in parallel, all making real
    edit_file tool calls on a shared workspace, with Synapse runtime
    actively detecting conflicts.
    """
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\nstdbuf -oL python3 -u /opt/synapse-payloads/v022_framework_races.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    env["PYTHONUNBUFFERED"] = "1"
    captured: list[str] = []
    try:
        proc = subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None:
                    break
                continue
            print(line.rstrip(), flush=True)
            captured.append(line)
            if time.time() - started > 3600:
                proc.terminate()
                return {
                    "exit_code": -1,
                    "stdout": "".join(captured)[-100000:],
                    "stderr": "TIMEOUT",
                    "elapsed_seconds": round(time.time() - started, 1),
                }
        proc.wait()
    except Exception as e:
        return {
            "exit_code": -2,
            "stdout": "".join(captured)[-100000:],
            "stderr": f"streaming exception: {e}",
            "elapsed_seconds": round(time.time() - started, 1),
        }

    return {
        "exit_code": proc.returncode,
        "stdout": "".join(captured)[-100000:],
        "stderr": "",
        "elapsed_seconds": round(time.time() - started, 1),
    }


@app.function(
    cpu=4.0, memory=8192, timeout=2400, scaledown_window=10,
)
def v022_adapter_e2e_run(api_keys: dict[str, str]) -> dict[str, Any]:
    """Fixed adapter E2E test — invokes the actual patched dispatch path
    of each framework's tool object, not the underlying user function."""
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    extra = (
        "\npython3 -m pip install -q "
        "autogen-agentchat 'crewai>=1.0' langchain-core openai-agents "
        "'pydantic-ai>=1.0' smolagents strands-agents agno llama-index-core "
        "google-adk "
        ">/dev/null 2>&1 || true\n"
    )
    script = setup + extra + "\n\nstdbuf -oL python3 -u /opt/synapse-payloads/v022_adapter_e2e.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    env["PYTHONUNBUFFERED"] = "1"
    captured: list[str] = []
    try:
        proc = subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None: break
                continue
            print(line.rstrip(), flush=True)
            captured.append(line)
            if time.time() - started > 2400:
                proc.terminate()
                return {"exit_code": -1, "stdout": "".join(captured)[-100000:],
                        "stderr": "TIMEOUT", "elapsed_seconds": round(time.time() - started, 1)}
        proc.wait()
    except Exception as e:
        return {"exit_code": -2, "stdout": "".join(captured)[-100000:],
                "stderr": f"streaming exception: {e}",
                "elapsed_seconds": round(time.time() - started, 1)}

    return {"exit_code": proc.returncode, "stdout": "".join(captured)[-100000:],
            "stderr": "", "elapsed_seconds": round(time.time() - started, 1)}


@app.local_entrypoint()
def v022_adapter_e2e() -> None:
    """Drive the fixed v0.2.2 adapter E2E test."""
    import json, os, time
    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set"); return
    print(">>> v0.2.2 adapter E2E test (11 frameworks via real dispatch path)...")
    r = v022_adapter_e2e_run.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    if r.get("stderr"): print("\n--- stderr ---"); print(r["stderr"][:2000])
    out = f"bench/results/v022_adapter_e2e_{time.strftime('%Y%m%d-%H%M%S')}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f: json.dump(r, f, indent=2)
    print(f"\nsaved -> {out}")


@app.function(
    cpu=4.0, memory=8192, timeout=2400, scaledown_window=10,
)
def v022_adapter_e2e_v4_run(api_keys: dict[str, str]) -> dict[str, Any]:
    """Post-fix validation: ContextVar attribution under asyncio.gather.

    v3 showed ``langchain agents=['bob']`` — the env-var attribution race.
    v4 must show ``agents=['alice','bob']`` for langchain/langgraph/
    smolagents/autogen, proving the v0.2.2a2 ContextVar fix landed."""
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    extra = (
        "\npython3 -m pip install -q "
        "autogen-agentchat 'crewai>=1.0' langchain-core "
        "smolagents "
        ">/dev/null 2>&1 || true\n"
    )
    script = setup + extra + "\n\nstdbuf -oL python3 -u /opt/synapse-payloads/v022_adapter_e2e_v4.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    env["PYTHONUNBUFFERED"] = "1"
    captured: list[str] = []
    try:
        proc = subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None: break
                continue
            print(line.rstrip(), flush=True)
            captured.append(line)
            if time.time() - started > 2400:
                proc.terminate()
                return {"exit_code": -1, "stdout": "".join(captured)[-100000:],
                        "stderr": "TIMEOUT", "elapsed_seconds": round(time.time() - started, 1)}
        proc.wait()
    except Exception as e:
        return {"exit_code": -2, "stdout": "".join(captured)[-100000:],
                "stderr": f"streaming exception: {e}",
                "elapsed_seconds": round(time.time() - started, 1)}

    return {"exit_code": proc.returncode, "stdout": "".join(captured)[-100000:],
            "stderr": "", "elapsed_seconds": round(time.time() - started, 1)}


@app.local_entrypoint()
def v022_adapter_e2e_v4() -> None:
    """Drive the v0.2.2a3 ContextVar-fix validation run."""
    import json, os, time
    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    print(">>> v0.2.2a3 adapter E2E v4 — ContextVar fix validation...")
    r = v022_adapter_e2e_v4_run.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    if r.get("stderr"): print("\n--- stderr ---"); print(r["stderr"][:2000])
    out = f"bench/results/v022_adapter_e2e_v4_{time.strftime('%Y%m%d-%H%M%S')}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f: json.dump(r, f, indent=2)
    print(f"\nsaved -> {out}")


@app.function(
    cpu=4.0, memory=8192, timeout=2400, scaledown_window=10,
)
def v022_real_llm_e2e_run(api_keys: dict[str, str]) -> dict[str, Any]:
    """W2.1: real-LLM E2E for the 6 install-only adapters.

    Drives crewai/openai_agents/pydantic_ai/agno/llama_index/google_adk
    with real Anthropic Haiku 4.5 calls through their respective
    framework-native APIs, then queries Postgres to confirm INTENTIONs
    were persisted with correct attribution."""
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    extra = (
        "\npython3 -m pip install -q "
        "'crewai>=1.0' anthropic openai-agents "
        "'pydantic-ai-slim[anthropic]>=1.0' "
        "agno llama-index-core llama-index-llms-anthropic "
        "google-adk litellm opentelemetry-sdk "
        ">/dev/null 2>&1 || true\n"
    )
    script = setup + extra + "\n\nstdbuf -oL python3 -u /opt/synapse-payloads/v022_real_llm_e2e.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    env["PYTHONUNBUFFERED"] = "1"
    captured: list[str] = []
    try:
        proc = subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None: break
                continue
            print(line.rstrip(), flush=True)
            captured.append(line)
            if time.time() - started > 2400:
                proc.terminate()
                return {"exit_code": -1, "stdout": "".join(captured)[-100000:],
                        "stderr": "TIMEOUT", "elapsed_seconds": round(time.time() - started, 1)}
        proc.wait()
    except Exception as e:
        return {"exit_code": -2, "stdout": "".join(captured)[-100000:],
                "stderr": f"streaming exception: {e}",
                "elapsed_seconds": round(time.time() - started, 1)}

    return {"exit_code": proc.returncode, "stdout": "".join(captured)[-100000:],
            "stderr": "", "elapsed_seconds": round(time.time() - started, 1)}


@app.local_entrypoint()
def v022_real_llm_e2e() -> None:
    """Drive the W2.1 real-LLM E2E suite (6 install-only adapters)."""
    import json, os, time
    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set"); return
    print(">>> W2.1 real-LLM E2E for 6 install-only adapters...")
    r = v022_real_llm_e2e_run.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    if r.get("stderr"): print("\n--- stderr ---"); print(r["stderr"][:2000])
    out = f"bench/results/v022_real_llm_e2e_{time.strftime('%Y%m%d-%H%M%S')}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f: json.dump(r, f, indent=2)
    print(f"\nsaved -> {out}")


@app.function(
    cpu=4.0, memory=8192, timeout=2400, scaledown_window=10,
)
def organic_e2e_run(api_keys: dict[str, str]) -> dict[str, Any]:
    """Each integration's CANONICAL example, run unmodified except for
    synapse.install(). NO induced collisions — the harness mirrors what
    a real user would write per each framework's docs."""
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    # Split installs into 3 commands so a dep conflict in one batch
    # doesn't block the others. v6 surfaced this: a single mega-install
    # with `|| true` silently failed because crewai 0.x pin conflicted
    # with pydantic-ai-slim's pydantic requirement, and EVERY framework
    # was missing. Each batch now reports failure loudly so we know.
    extra = (
        "\necho '=== install batch 1: core LLM + tracing ==='\n"
        "python3 -m pip install -q anthropic litellm opentelemetry-sdk "
        "|| echo 'BATCH1 FAILED'\n"
        "echo '=== install batch 2: langchain ecosystem ==='\n"
        "python3 -m pip install -q langgraph langchain langchain-anthropic langchain-core "
        "llama-index-core llama-index-llms-anthropic "
        "|| echo 'BATCH2 FAILED'\n"
        "echo '=== install batch 3: agent frameworks ==='\n"
        "python3 -m pip install -q "
        "'crewai>=1.0' 'autogen-agentchat>=0.4' 'autogen-ext[anthropic]>=0.4' "
        "openai-agents 'pydantic-ai-slim[anthropic]>=1.0' "
        "agno smolagents google-adk "
        "|| echo 'BATCH3 FAILED'\n"
        "python3 -c \"import autogen_agentchat, smolagents, agents, pydantic_ai, agno, llama_index, google.adk, crewai; print('all framework imports OK')\" "
        "|| echo 'IMPORT CHECK FAILED'\n"
    )
    script = setup + extra + "\n\nstdbuf -oL python3 -u /opt/synapse-payloads/organic_e2e.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    env["PYTHONUNBUFFERED"] = "1"
    captured: list[str] = []
    try:
        proc = subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None: break
                continue
            print(line.rstrip(), flush=True)
            captured.append(line)
            if time.time() - started > 2400:
                proc.terminate()
                return {"exit_code": -1, "stdout": "".join(captured)[-100000:],
                        "stderr": "TIMEOUT", "elapsed_seconds": round(time.time() - started, 1)}
        proc.wait()
    except Exception as e:
        return {"exit_code": -2, "stdout": "".join(captured)[-100000:],
                "stderr": f"streaming exception: {e}",
                "elapsed_seconds": round(time.time() - started, 1)}
    return {"exit_code": proc.returncode, "stdout": "".join(captured)[-100000:],
            "stderr": "", "elapsed_seconds": round(time.time() - started, 1)}


@app.local_entrypoint()
def organic_e2e() -> None:
    """Run the organic E2E suite — each framework's canonical example."""
    import json, os, time
    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set"); return
    print(">>> Organic E2E (canonical-example-per-framework)...")
    r = organic_e2e_run.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    if r.get("stderr"): print("\n--- stderr ---"); print(r["stderr"][:2000])
    out = f"bench/results/organic_e2e_{time.strftime('%Y%m%d-%H%M%S')}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f: json.dump(r, f, indent=2)
    print(f"\nsaved -> {out}")


@app.local_entrypoint()
def v022_framework_races() -> None:
    """Drive the v0.2.2 real-life framework race test."""
    import json, os, time
    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set"); return
    print(">>> v0.2.2 framework-race autonomous tests (11 frameworks, real agents)...")
    r = v022_framework_races_run.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    if r.get("stderr"):
        print("\n--- stderr ---"); print(r["stderr"][:2000])
    out = f"bench/results/v022_framework_races_{time.strftime('%Y%m%d-%H%M%S')}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {out}")


@app.local_entrypoint()
def v02_strands_real() -> None:
    """Drive the real Strands Agents test (Option C)."""
    import json, os, time
    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set"); return
    print(">>> v0.2.1 Real Strands Agents test (Option C)...")
    r = v02_strands_real_run.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    if r.get("stderr"):
        print("\n--- stderr ---"); print(r["stderr"][:2000])
    out = f"bench/results/v02_strands_real_{time.strftime('%Y%m%d-%H%M%S')}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {out}")


@app.local_entrypoint()
def v02_ci_loop() -> None:
    """Drive the CI/CD loop test (Option A)."""
    import json, os, time
    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set"); return
    print(">>> v0.2.1 CI/CD-loop comparison test (ci_only vs ci_plus_synapse)...")
    r = v02_ci_loop_run.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    if r.get("stderr"):
        print("\n--- stderr ---"); print(r["stderr"][:2000])
    out = f"bench/results/v02_ci_loop_{time.strftime('%Y%m%d-%H%M%S')}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {out}")


@app.local_entrypoint()
def v02_multi() -> None:
    """Drive the multi-orchestrator natural-workload experiment."""
    import json, os, time
    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set"); return
    print(">>> v0.2.1 multi-orchestrator natural workload (two teams, no coord)...")
    r = v02_multi_orchestrator_run.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"][-30000:])
    if r.get("stderr"):
        print("\n--- stderr ---"); print(r["stderr"][:2000])
    out = f"bench/results/v02_multi_orchestrator_{time.strftime('%Y%m%d-%H%M%S')}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {out}")


@app.local_entrypoint()
def v02_autonomous() -> None:
    """Drive the autonomous observer test (3 modes: no_synapse / observer / full)."""
    import base64
    import json
    import os
    import time

    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return
    print(">>> v0.2 autonomous observer test (mini-Stripe, 3 modes)...")
    r = v02_autonomous_observer_run.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"][-30000:])
    if r.get("stderr"):
        print("\n--- stderr ---")
        print(r["stderr"][:2000])

    out_dir = f"bench/results/v02_autonomous_{time.strftime('%Y%m%d-%H%M%S')}"
    os.makedirs(out_dir, exist_ok=True)
    captures = r.pop("captures", {}) or {}
    with open(f"{out_dir}/result.json", "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    decoded = []
    for name, b64 in captures.items():
        try:
            data = base64.b64decode(b64)
            with open(f"{out_dir}/{name}", "wb") as f:
                f.write(data)
            decoded.append(name)
        except Exception as e:
            print(f"  warn: could not decode {name}: {e}")
    print(f"\nsaved -> {out_dir}/")
    print(f"  result.json + {len(decoded)} captures: {decoded}")


@app.local_entrypoint()
def v02_w5() -> None:
    """Drive the Week 5 BELIEF divergence demo."""
    import json
    import os
    import time

    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return
    print(">>> v0.2 Week 5: BELIEF divergence on data analysis pipeline...")
    r = v02_w5_belief_divergence.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    if r.get("stderr"):
        print("\n--- stderr ---")
        print(r["stderr"][:2000])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"v02_w5_belief_divergence_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {path}")


@app.local_entrypoint()
def v02_w4() -> None:
    """Drive the Week 4 auto_merge demo."""
    import json
    import os
    import time

    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return
    print(">>> v0.2 Week 4: Instagram-clone with MergePolicy.auto_merge...")
    r = v02_w4_auto_merge.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    if r.get("stderr"):
        print("\n--- stderr ---")
        print(r["stderr"][:2000])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"v02_w4_auto_merge_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {path}")


@app.local_entrypoint()
def v02_week3() -> None:
    """Drive the Week 3 full integration test (LangGraph + CrewAI together)."""
    import json
    import os
    import time

    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return
    print(">>> v0.2 Week 3 full: LangGraph + CrewAI on same Synapse stack...")
    r = v02_week3_full.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    if r.get("stderr"):
        print("\n--- stderr ---")
        print(r["stderr"][:2000])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"v02_week3_full_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {path}")


@app.local_entrypoint()
def v02_crewai() -> None:
    """Drive v0.2 Week 3a CrewAI live test."""
    import json
    import os
    import time

    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return
    print(">>> v0.2 Week 3a: CrewAI + synapse.install() live test...")
    r = v02_crewai_live.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    if r.get("stderr"):
        print("\n--- stderr ---")
        print(r["stderr"][:2000])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"v02_crewai_live_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {path}")


@app.local_entrypoint()
def v02_langgraph() -> None:
    """Drive v0.2 Week 2 live test."""
    import json
    import os
    import time

    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return
    print(">>> v0.2 Week 2: LangGraph + synapse.install() live test...")
    r = v02_langgraph_live.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    if r.get("stderr"):
        print("\n--- stderr ---")
        print(r["stderr"][:2000])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"v02_langgraph_live_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {path}")


@app.local_entrypoint()
def product_dev_paperclip() -> None:
    """Run real_product_dev_paperclip against a Modal sandbox."""
    import json
    import os
    import time

    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return

    print(">>> running real product-dev paperclip test in Modal sandbox...")
    r = real_product_dev_paperclip.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    if r.get("stderr"):
        print("\n--- stderr ---")
        print(r["stderr"][:2000])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"product_dev_real_paperclip_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {path}")


@app.local_entrypoint()
def product_dev() -> None:
    """Run real_product_dev_hermes against a Modal sandbox."""
    import json
    import os
    import time

    api_keys = {
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
    }
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return

    print(">>> running real product-dev test in Modal sandbox...")
    r = real_product_dev_hermes.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"product_dev_real_hermes_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {path}")


@app.function(
    cpu=2.0, memory=2048, timeout=TEST_TIMEOUT, scaledown_window=10,
)
def smoke_integrations() -> dict[str, Any]:
    """End-to-end smoke: install Hermes alongside Synapse, run a coordinated
    tool call against the real Redis bus running in the sandbox; verify
    INTENTION + RESOLUTION envelopes land. Inline-mock the Paperclip and
    OpenClaw flows since their integrations live in the TS SDK.
    """
    import subprocess
    import textwrap

    setup = _common_setup_script()
    smoke_script = textwrap.dedent(r"""
        echo
        echo "============================================================"
        echo "  HERMES integration: real bus + Synapse hook"
        echo "============================================================"
        cd /tmp
        if [ ! -d hermes-agent ]; then
          git clone --depth 1 https://github.com/NousResearch/hermes-agent.git 2>&1 | tail -1
        fi
        cd hermes-agent && pip install -e . 2>&1 | tail -2

        # Apply Synapse migrations to the local Postgres
        psql -h /var/run/postgresql -U synapse -d synapse \
          -f /opt/synapse-sdk/../runtime/migrations/0001_initial_schema.sql \
          2>&1 | tail -3 || \
          psql -h /var/run/postgresql -U synapse -d synapse \
            -f /opt/synapse-sdk-runtime/migrations/0001_initial_schema.sql 2>&1 | tail -3 || \
          true

        cat > /tmp/smoke_hermes.py <<'PYDONE'
import asyncio, os, sys, json
sys.path.insert(0, "/opt/synapse-sdk")

# Quick: ensure the migrations table exists (use the embedded SQL we know)
import asyncpg

MIGRATIONS_SQL = (
    "CREATE TABLE IF NOT EXISTS agents ("
    " id text PRIMARY KEY, session_id text NOT NULL, tenant_id text,"
    " status text NOT NULL CHECK (status IN ('active','idle','crashed')),"
    " capabilities jsonb NOT NULL,"
    " subscribes text[] NOT NULL DEFAULT '{}',"
    " scopes_owned text[] NOT NULL DEFAULT '{}',"
    " last_heartbeat timestamptz NOT NULL DEFAULT now(),"
    " created_at timestamptz NOT NULL DEFAULT now()"
    "); "
    "CREATE TABLE IF NOT EXISTS intentions ("
    " id text PRIMARY KEY, agent_id text NOT NULL REFERENCES agents(id),"
    " session_id text NOT NULL, tenant_id text, scope text[] NOT NULL,"
    " action jsonb NOT NULL, expected_outcome text NOT NULL,"
    " blocking boolean NOT NULL DEFAULT false,"
    " status text NOT NULL CHECK (status IN ('pending','active','resolved','pivoted')),"
    " created_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz"
    "); "
    "CREATE INDEX IF NOT EXISTS intentions_scope_gin ON intentions USING GIN (scope);"
)

async def main():
    conn = await asyncpg.connect(
        "postgresql://synapse:synapse_dev@localhost:5432/synapse"
    )
    await conn.execute(MIGRATIONS_SQL)
    await conn.close()

    from synapse.bus import Bus
    from synapse.state import StateGraph
    from synapse.integrations.hermes_integration import (
        install_hermes_synapse_hooks, wrap_tool_call_for_synapse,
    )

    bus = Bus("redis://localhost:6379/0")
    state = StateGraph("postgresql://synapse:synapse_dev@localhost:5432/synapse")
    await bus.connect(); await state.connect()

    status = await install_hermes_synapse_hooks(
        bus=bus, state=state, session_id="hermes_smoke",
        agent_id="hermes_main", gate_ms=50,
    )
    print("[hermes] hook status:", status)

    async def inner_write():
        return "wrote 128 bytes to /tmp/synapse_demo.txt"

    result = await wrap_tool_call_for_synapse(
        "write_file", {"path": "/tmp/synapse_demo.txt"}, inner_write,
    )
    print("[hermes] tool result:", result)

    # Read back what landed on the session stream
    redis = bus.redis
    entries = await redis.xrange("synapse:session:hermes_smoke:events", count=20)
    print(f"[hermes] envelopes on session stream: {len(entries)}")
    for entry_id, fields in entries:
        env = json.loads(fields["e"])
        print(f"  {env['type']:13} agent={env['agent_id']} payload_keys={list(env['payload'].keys())[:5]}")

    # Read back agent registration
    rows = await state.pool.fetch(
        "SELECT id, session_id, status, scopes_owned FROM agents"
    )
    print(f"[hermes] agents registered: {len(rows)}")
    for r in rows:
        print(f"  {dict(r)}")

    rows = await state.pool.fetch(
        "SELECT id, scope, status, expected_outcome FROM intentions"
    )
    print(f"[hermes] intentions in state graph: {len(rows)}")
    for r in rows:
        print(f"  {dict(r)}")

    await bus.close(); await state.close()

asyncio.run(main())
PYDONE

        python3 /tmp/smoke_hermes.py 2>&1

        echo
        echo "============================================================"
        echo "  PAPERCLIP + OPENCLAW: TS-side adapter smoke (inline)"
        echo "============================================================"
        cat > /tmp/smoke_paperclip.mjs <<'NODEEOF'
const events = [];
const inner = { type: "anthropic",
  async invoke(req) { return { text: "hello", tokensIn: 50, tokensOut: 25 }; } };

async function wrappedInvoke(req) {
  events.push({ type: "INTENTION", agent: req.task.agentId, scope: [`paperclip.task:${req.task.id}:w`] });
  const r = await inner.invoke(req);
  events.push({ type: "RESOLUTION", agent: req.task.agentId, outcome: r.error ? "failure" : "success" });
  if (r.tokensIn !== undefined) events.push({ type: "COST_REPORT", tokens: r.tokensIn + r.tokensOut });
  return r;
}
const r = await wrappedInvoke({ task: { id: "T1", agentId: "engineer_a", description: "ship feature" }, prompt: "..." });
console.log("[paperclip] inner response:", r);
console.log("[paperclip] envelopes that would publish:");
for (const e of events) console.log("   ", e);
NODEEOF
        node /tmp/smoke_paperclip.mjs

        cat > /tmp/smoke_openclaw.mjs <<'NODEEOF'
const events = [];
const tools = [
  { name: "fs.read",  isWrite: false, async handler() { return "data"; } },
  { name: "fs.write", isWrite: true,  async handler() { return "wrote"; } },
];
function wrap(t) {
  if (!t.isWrite) return t;
  return { ...t, async handler(args, ctx) {
    events.push({ type: "INTENTION", tool: t.name, scope: [`openclaw.tool.${t.name}:w`] });
    try {
      const r = await t.handler(args, ctx);
      events.push({ type: "RESOLUTION", tool: t.name, outcome: "success" });
      return r;
    } catch (e) {
      events.push({ type: "RESOLUTION", tool: t.name, outcome: "failure" });
      throw e;
    }
  }};
}
const w = tools.map(wrap);
console.log("[openclaw] read:", await w[0].handler({}));
console.log("[openclaw] write:", await w[1].handler({}));
console.log("[openclaw] events:");
for (const e of events) console.log("   ", e);
NODEEOF
        node /tmp/smoke_openclaw.mjs
    """)

    started = time.time()
    try:
        proc = subprocess.run(
            ["bash", "-c", setup + smoke_script],
            capture_output=True, text=True, timeout=TEST_TIMEOUT,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-25000:],
            "stderr": proc.stderr[-3000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-25000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.local_entrypoint()
def smoke() -> None:
    """Run the cross-framework smoke and save results."""
    import json
    import os
    import time

    print(">>> cross-framework integration smoke...")
    r = smoke_integrations.remote()
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"framework_smoke_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"saved -> {path}")


@app.local_entrypoint()
def fetch_docs() -> None:
    """Run fetch_integration_docs and save the output for offline reading."""
    import json
    import os
    import time

    print(">>> fetching integration docs from all 3 frameworks...")
    result = fetch_integration_docs.remote()
    out_dir = "bench/results"
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(out_dir, f"framework_integration_docs_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    # Also write the raw stdout to a md file for human reading
    md_path = os.path.join(out_dir, f"framework_integration_docs_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Framework integration docs (fetched from sandboxes)\n\n")
        f.write(f"```\n{result['stdout']}\n```\n")
    print(f"saved -> {path}")
    print(f"        {md_path}")
    print(f"\n--- last 60 lines ---")
    print("\n".join(result["stdout"].splitlines()[-60:]))


@app.local_entrypoint()
def run_one(framework: str = "hermes") -> None:
    """Drive a single framework test for iterative debugging."""
    import json
    import os
    import time

    api_keys = {
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
    }

    fns = {"hermes": run_hermes, "paperclip": run_paperclip, "openclaw": run_openclaw}
    if framework not in fns:
        raise SystemExit(f"unknown framework: {framework}")
    fn = fns[framework]

    t0 = time.time()
    result = fn.remote(api_keys)
    elapsed = time.time() - t0
    print(f"\n=== [{framework}] exit={result['exit_code']} elapsed={elapsed:.1f}s ===")
    print(result["stdout"])
    if result.get("stderr"):
        print("\n--- stderr ---")
        print(result["stderr"])

    out_dir = "bench/results"
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(out_dir, f"framework_sandbox_{framework}_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"\nsaved -> {path}")


@app.function(
    cpu=4.0, memory=4096, timeout=1800, scaledown_window=10,
)
def v02_sdlc_billing_run(api_keys: dict[str, str]) -> dict[str, Any]:
    """v0.2 SDLC benchmark: 6-agent multi-stage workflow building a
    multi-tenant SaaS billing platform.

    Compares no_synapse vs with_synapse_redirect vs with_synapse_full.
    Headline metric: ``coherence_score`` — fraction of expected per-agent
    contributions that survive in the final contended files.

    Cost target: ~$2 per run (3 modes ≈ $6 total).
    Wall clock: 8-15 min depending on Anthropic latency.
    """
    import subprocess
    started = time.time()
    setup = _common_setup_script()
    script = setup + "\n\npython3 /opt/synapse-payloads/v02_sdlc_billing.py 2>&1\n"

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = api_keys.get("ANTHROPIC_API_KEY", "")
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=1800, env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-90000:],
            "stderr": proc.stderr[-3000:],
            "elapsed_seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": (e.stdout or b"").decode("utf-8", errors="ignore")[-90000:],
            "stderr": "TIMEOUT",
            "elapsed_seconds": round(time.time() - started, 1),
        }


@app.local_entrypoint()
def v02_sdlc() -> None:
    """Drive the v0.2 SDLC billing-platform benchmark (3 modes).

    Saves the captured stdout + json blob into bench/results/.
    """
    import json
    import os
    import time

    api_keys = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    if not api_keys["ANTHROPIC_API_KEY"]:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return
    print(">>> v0.2 SDLC benchmark: 6-agent SaaS billing platform...")
    print("    modes: no_synapse, with_synapse_redirect, with_synapse_full")
    print("    estimated cost: ~$6 total across 3 modes")
    r = v02_sdlc_billing_run.remote(api_keys)
    print(f"\n=== exit={r['exit_code']} elapsed={r['elapsed_seconds']}s ===")
    print(r["stdout"])
    if r.get("stderr"):
        print("\n--- stderr ---")
        print(r["stderr"][:2000])
    out = "bench/results"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"v02_sdlc_billing_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    print(f"\nsaved -> {path}")
