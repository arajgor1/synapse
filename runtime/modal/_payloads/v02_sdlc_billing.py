"""v0.2 SDLC benchmark: 6-agent multi-stage workflow building a
multi-tenant SaaS billing platform (mini-Stripe / mini-Lago).

Compares three modes:

  1. no_synapse              : agents run fire-and-forget, no coordination.
                               Expect:  silent overwrites on User/Subscription
                                        models, .env naming chaos, semantic
                                        divergence on pricing model.

  2. with_synapse_redirect   : MergePolicy.redirect + scope-overlap detection.
                               Expect:  CONFLICTs raised on contended files,
                                        agents see policy_rationale, but final
                                        files still reflect last-writer-wins
                                        (no auto-merge).

  3. with_synapse_full       : MergePolicy.auto_merge
                                + emit_beliefs_from_tool_results=True
                                + critical_scopes=["billing.*", "*.stripe*"].
                               Expect:  contended files merged via BYO-LLM
                                        so all engineers' fields survive,
                                        BELIEF divergences caught on
                                        pricing_model + tax_calculation +
                                        currency_handling, billing.* scopes
                                        protected with hard ABORT on collision.

Workflow (4 stages, 6 agents):

  Stage 1 (sequential, 1 agent)
    product_manager:    requirements.md

  Stage 2 (sequential, 1 agent, sees Stage 1)
    architect:          ARCHITECTURE.md
                        models/User.js (skeleton)
                        models/Tenant.js (skeleton)
                        models/Subscription.js (skeleton)
                        models/Invoice.js (skeleton)
                        models/UsageRecord.js (skeleton)

  Stage 3 (PARALLEL, 3 agents — natural collisions)
    backend_engineer:   models/User.js (auth fields)            <- 3-way
                        models/Subscription.js (core fields)    <- 3-way
                        routes/auth.js
                        routes/tenants.js
                        routes/billing.js
                        routes/usage.js
                        services/email.js
                        .env.example                            <- 4-way
    frontend_engineer:  dashboard/App.tsx
                        dashboard/pages/Subscriptions.tsx
                        dashboard/pages/Invoices.tsx
                        .env.example                            <- 4-way
    integrations_eng:   services/stripe.js
                        webhooks/stripe.js
                        models/User.js (stripe_customer_id)     <- 3-way
                        models/Subscription.js (stripe_sub_id)  <- 3-way
                        .env.example                            <- 4-way

  Stage 4 (PARALLEL, 2 agents)
    qa_engineer:        tests/auth.test.js
                        tests/billing.test.js
                        tests/stripe-webhook.test.js
                        models/User.js (test fixture fields)    <- 3-way
                        models/Subscription.js (test fixtures)  <- 3-way
    devops_engineer:    Dockerfile
                        .github/workflows/ci.yml
                        .env.example                            <- 4-way

Real conflicts planted:
  - models/User.js          : 3-way (backend + integrations + qa)
  - models/Subscription.js  : 3-way (backend + integrations + qa)
  - .env.example            : 4-way semantic conflict on naming
                              (STRIPE_KEY vs STRIPE_API_KEY vs STRIPE_SECRET)

BELIEF divergences (semantic, no scope overlap on these):
  - pricing_model        : per_seat (PM) vs usage_based (architect)
                                       vs hybrid (backend_engineer)
  - tax_calculation      : included (frontend) vs added_at_checkout (backend)
                                                vs stripe_tax_api (integrations)
  - currency_handling    : USD_only (PM) vs multi_currency (architect)

Cap per LLM call at 600 tokens. Real Anthropic Haiku.

Estimated cost:
  ~30 file-write LLM calls per mode * 600 tokens out * $1/1M (haiku)
  = ~$0.018 output + ~$0.006 input per mode = ~$0.05 per mode "naively".
  In practice Haiku-4.5 is ~$1/M in / ~$5/M out, plus auto_merge in mode 3
  adds ~5-10 extra LLM calls (BYO-LLM merges) at ~1500 tokens each.
  Realistic budget: ~$0.50 mode 1, ~$0.60 mode 2, ~$0.90 mode 3 = ~$2 total.
  Stay under $2/run; 3 modes ≈ $6 ceiling.
"""
import os
os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "false"

import asyncio
import json
import logging
import re
import sys
import time
import uuid

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logging.getLogger("synapse.policies.builtin").setLevel(logging.INFO)
logging.getLogger("synapse.beliefs").setLevel(logging.INFO)

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"

MIGRATIONS_SQL = (
    "CREATE TABLE IF NOT EXISTS agents ("
    " id text PRIMARY KEY, session_id text NOT NULL, tenant_id text,"
    " status text NOT NULL CHECK (status IN ('active','idle','crashed')),"
    " capabilities jsonb NOT NULL,"
    " subscribes text[] NOT NULL DEFAULT '{}',"
    " scopes_owned text[] NOT NULL DEFAULT '{}',"
    " last_heartbeat timestamptz NOT NULL DEFAULT now(),"
    " created_at timestamptz NOT NULL DEFAULT now()"
    ");"
    " CREATE TABLE IF NOT EXISTS intentions ("
    " id text PRIMARY KEY, agent_id text NOT NULL REFERENCES agents(id),"
    " session_id text NOT NULL, tenant_id text, scope text[] NOT NULL,"
    " action jsonb NOT NULL, expected_outcome text NOT NULL,"
    " blocking boolean NOT NULL DEFAULT false,"
    " status text NOT NULL CHECK (status IN ('pending','active','resolved','pivoted')),"
    " created_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz"
    ");"
    " CREATE INDEX IF NOT EXISTS intentions_scope_gin ON intentions USING GIN (scope);"
    " CREATE TABLE IF NOT EXISTS beliefs ("
    " agent_id text NOT NULL, session_id text NOT NULL, tenant_id text,"
    " key text NOT NULL, value jsonb NOT NULL,"
    " confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),"
    " source text NOT NULL CHECK (source IN ('observed','inferred','assumed')),"
    " evidence text, updated_at timestamptz NOT NULL DEFAULT now(),"
    " PRIMARY KEY (agent_id, key)"
    ");"
)


# -----------------------------------------------------------------------------
# Workflow plan
# -----------------------------------------------------------------------------
# Each step is (relative_path, prompt, optional_state_diff_extras).
# Prompts deliberately steer agents toward DIFFERENT design decisions on the
# same file, so collisions on User.js / Subscription.js / .env.example are
# real (not contrived diffs).
#
# state_diff_extras is a dict of belief-like keys we surface in
# handle.set_state_diff so the BELIEF auto-extractor sees them. This is the
# canonical v0.2-w5 path.

STAGE_1 = {
    "product_manager": [
        ("requirements.md",
         "Write a PRODUCT REQUIREMENTS doc for a multi-tenant SaaS billing "
         "platform (mini-Stripe). Sections: Goals, User Personas, Core Features "
         "(auth, tenants, subscriptions, invoicing, usage metering, Stripe "
         "integration, admin dashboard), Pricing Model: PER-SEAT only ($10/seat/"
         "month), Currency: USD ONLY for v1, Tax: included in displayed price. "
         "Output ONLY the markdown, no fences. ~30 lines.",
         {
             "pricing_model": "per_seat",
             "currency_handling": "USD_only",
             "tax_calculation": "included",
         }),
    ],
}

STAGE_2 = {
    "architect": [
        ("ARCHITECTURE.md",
         "Write a one-page ARCHITECTURE.md for a multi-tenant SaaS billing "
         "platform. Cover: Service topology (Express API, Postgres, Redis, "
         "React admin SPA), Data model overview, Multi-tenancy strategy "
         "(row-level tenant_id), Stripe integration approach, Pricing: "
         "USAGE-BASED metering with monthly aggregation, Currency: MULTI-"
         "CURRENCY (USD, EUR, GBP), Tax: stripe_tax_api integration. Output "
         "ONLY the markdown, no fences. ~25 lines.",
         {
             "pricing_model": "usage_based",
             "currency_handling": "multi_currency",
             "tax_calculation": "stripe_tax_api",
         }),
        ("models/User.js",
         "Write a Sequelize User model SKELETON for a multi-tenant billing "
         "platform. Fields: id (UUID PK), email (unique), tenant_id (FK), "
         "created_at. Use sequelize.define. Output ONLY the JS module + "
         "imports, no markdown.",
         None),
        ("models/Tenant.js",
         "Write a Sequelize Tenant model. Fields: id (UUID PK), name, "
         "plan_id, created_at. Output ONLY the JS module, no markdown.",
         None),
        ("models/Subscription.js",
         "Write a Sequelize Subscription model SKELETON. Fields: id (UUID), "
         "tenant_id (FK), plan_id, status (active/canceled), current_period_end, "
         "created_at. Output ONLY the JS module, no markdown.",
         None),
        ("models/Invoice.js",
         "Write a Sequelize Invoice model. Fields: id, tenant_id, "
         "subscription_id, amount_cents, currency, status (draft/paid/void), "
         "due_at, created_at. Output ONLY the JS module, no markdown.",
         None),
        ("models/UsageRecord.js",
         "Write a Sequelize UsageRecord model. Fields: id, tenant_id, metric, "
         "quantity, recorded_at. Output ONLY the JS module, no markdown.",
         None),
    ],
}

STAGE_3 = {
    "backend_engineer": [
        ("models/User.js",
         "Write a Sequelize User model with AUTH FIELDS for a billing platform. "
         "Fields: id (UUID PK), email (unique), password_hash (str), "
         "last_login (DateTime nullable), tenant_id, created_at. Output ONLY "
         "the JS module + imports, no markdown.",
         None),
        ("models/Subscription.js",
         "Write a Sequelize Subscription model with CORE BILLING FIELDS. "
         "Fields: id, tenant_id, plan_id, status, billing_cycle (monthly/"
         "annual), seat_count (int), current_period_end, created_at. Output "
         "ONLY the JS module, no markdown.",
         {
             "pricing_model": "hybrid",
             "tax_calculation": "added_at_checkout",
         }),
        ("routes/auth.js",
         "Write an Express router for auth: POST /login, POST /signup, POST /"
         "logout. Use bcrypt + JWT. Output ONLY the JS module, no markdown.",
         None),
        ("routes/tenants.js",
         "Write an Express router for tenants: GET /tenants/:id, POST /"
         "tenants, PATCH /tenants/:id. Output ONLY the JS module, no markdown.",
         None),
        ("routes/billing.js",
         "Write an Express router for billing: GET /billing/subscriptions, "
         "POST /billing/subscriptions, GET /billing/invoices. Output ONLY the "
         "JS module, no markdown.",
         None),
        ("routes/usage.js",
         "Write an Express router for usage: POST /usage/record, GET /usage/"
         "current. Output ONLY the JS module, no markdown.",
         None),
        ("services/email.js",
         "Write a Node email service with sendInvoiceEmail(invoice) and "
         "sendWelcomeEmail(user) functions using nodemailer. Output ONLY the "
         "JS module, no markdown.",
         None),
        (".env.example",
         "Write a .env.example for an Express+Postgres billing app. Include "
         "DATABASE_URL, JWT_SECRET, STRIPE_KEY (this is the convention this "
         "team uses for the Stripe API key), REDIS_URL, PORT. Output ONLY "
         "key=value lines, no markdown.",
         None),
    ],
    "frontend_engineer": [
        ("dashboard/App.tsx",
         "Write a React App.tsx for the billing admin dashboard. Use react-"
         "router-dom. Routes: /, /subscriptions, /invoices. Output ONLY the "
         "TSX, no markdown.",
         {
             "tax_calculation": "included",
         }),
        ("dashboard/pages/Subscriptions.tsx",
         "Write a React Subscriptions.tsx page that fetches GET /billing/"
         "subscriptions and renders a table. Output ONLY the TSX, no markdown.",
         None),
        ("dashboard/pages/Invoices.tsx",
         "Write a React Invoices.tsx page that fetches GET /billing/invoices "
         "and renders a table with amount + status. Output ONLY the TSX, no "
         "markdown.",
         None),
        (".env.example",
         "Write a .env.example for a React frontend dashboard. Include "
         "VITE_API_URL, VITE_STRIPE_PUBLIC_KEY, VITE_STRIPE_API_KEY (this is "
         "the convention used here for the publishable key). Output ONLY "
         "key=value lines, no markdown.",
         None),
    ],
    "integrations_engineer": [
        ("services/stripe.js",
         "Write a Node Stripe service module wrapping the stripe SDK. "
         "Functions: createCustomer(email), createSubscription(customerId, "
         "priceId), cancelSubscription(subId). Output ONLY the JS module, no "
         "markdown.",
         None),
        ("webhooks/stripe.js",
         "Write an Express handler for Stripe webhooks at POST /webhooks/"
         "stripe. Verify signature, handle invoice.paid + customer."
         "subscription.deleted events. Output ONLY the JS module, no markdown.",
         None),
        ("models/User.js",
         "Write a Sequelize User model with STRIPE INTEGRATION fields. "
         "Fields: id (UUID PK), email (unique), tenant_id, stripe_customer_id "
         "(str unique nullable), created_at. Output ONLY the JS module, no "
         "markdown.",
         None),
        ("models/Subscription.js",
         "Write a Sequelize Subscription model with STRIPE FIELDS. Fields: "
         "id, tenant_id, stripe_subscription_id (str unique), stripe_price_id, "
         "status, current_period_end, created_at. Output ONLY the JS module, "
         "no markdown.",
         {
             "tax_calculation": "stripe_tax_api",
         }),
        (".env.example",
         "Write a .env.example for the Stripe integration. Include "
         "STRIPE_SECRET (this team uses STRIPE_SECRET as the env var name "
         "for the secret key, never STRIPE_KEY or STRIPE_API_KEY), "
         "STRIPE_WEBHOOK_SECRET, STRIPE_PUBLISHABLE_KEY. Output ONLY key=value "
         "lines, no markdown.",
         None),
    ],
}

STAGE_4 = {
    "qa_engineer": [
        ("tests/auth.test.js",
         "Write Jest tests for the auth router: signup creates user, login "
         "returns JWT, invalid password is rejected. Output ONLY the JS test "
         "file, no markdown.",
         None),
        ("tests/billing.test.js",
         "Write Jest tests for the billing router: list subscriptions for "
         "tenant, create subscription, list invoices. Output ONLY the JS, no "
         "markdown.",
         None),
        ("tests/stripe-webhook.test.js",
         "Write Jest tests for the Stripe webhook: signature verification "
         "rejects bad sig, invoice.paid marks invoice paid. Output ONLY the "
         "JS, no markdown.",
         None),
        ("models/User.js",
         "Write a Sequelize User model with TEST FIXTURE fields for QA. "
         "Fields: id (UUID PK), email, tenant_id, is_test_fixture (bool, "
         "default false), fixture_seed (str nullable), created_at. Output "
         "ONLY the JS module, no markdown.",
         None),
        ("models/Subscription.js",
         "Write a Sequelize Subscription model with TEST FIXTURE fields. "
         "Fields: id, tenant_id, plan_id, status, is_test_fixture (bool "
         "default false), fixture_scenario (str nullable), created_at. "
         "Output ONLY the JS module, no markdown.",
         None),
    ],
    "devops_engineer": [
        ("Dockerfile",
         "Write a production Dockerfile for a Node 20 Express app. Multi-"
         "stage: builder + runtime. Expose 3000, run as non-root. Output "
         "ONLY the Dockerfile, no markdown.",
         None),
        (".github/workflows/ci.yml",
         "Write a GitHub Actions CI workflow. Triggers: push to main, PRs. "
         "Steps: checkout, setup-node@v4, npm ci, npm test, docker build. "
         "Output ONLY the YAML, no markdown.",
         None),
        (".env.example",
         "Write a deployment-ready .env.example combining all required env "
         "vars: DATABASE_URL, REDIS_URL, JWT_SECRET, STRIPE_API_KEY (this is "
         "the canonical name for the Stripe secret in production), "
         "STRIPE_WEBHOOK_SECRET, NODE_ENV, PORT. Output ONLY key=value lines, "
         "no markdown.",
         None),
    ],
}


# -----------------------------------------------------------------------------
# Marker grammar — what each agent SHOULD have contributed to a contended file.
# Used to compute the coherence_score after the run.
#
# The score is (markers actually present in final file) / (markers expected).
# In no_synapse mode we expect ~33% (last writer wins on 3-way collisions).
# In with_synapse_full + auto_merge we target >80%.
# -----------------------------------------------------------------------------
MARKERS = {
    "models/User.js": {
        "architect.skeleton":             r"sequelize\.define|DataTypes",
        "backend.password_hash":          r"password_hash",
        "backend.last_login":             r"last_login",
        "integrations.stripe_customer":   r"stripe_customer_id",
        "qa.is_test_fixture":             r"is_test_fixture",
    },
    "models/Subscription.js": {
        "architect.skeleton":             r"current_period_end",
        "backend.billing_cycle":          r"billing_cycle",
        "backend.seat_count":             r"seat_count",
        "integrations.stripe_sub_id":     r"stripe_subscription_id",
        "qa.fixture_scenario":            r"fixture_scenario|is_test_fixture",
    },
    ".env.example": {
        "backend.STRIPE_KEY":             r"^STRIPE_KEY=",
        "frontend.VITE_STRIPE":           r"VITE_STRIPE",
        "integrations.STRIPE_SECRET":     r"^STRIPE_SECRET=",
        "devops.STRIPE_API_KEY":          r"^STRIPE_API_KEY=",
        "common.DATABASE_URL":            r"DATABASE_URL",
    },
}


def scope_for(path: str) -> list[str]:
    # Drop directory separators into dots so glob matchers behave.
    flat = path.replace("/", ".").replace("\\", ".")
    return [f"repo.fs.{flat}:w"]


async def apply_migrations() -> None:
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


async def llm_write(ant, prompt: str, max_tokens: int = 600):
    msg = await ant.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    content = msg.content[0].text if msg.content else ""
    return content, msg.usage.input_tokens, msg.usage.output_tokens


async def agent_step(
    *, agent_id: str, session_id: str, repo_root: str,
    rel_path: str, prompt: str, state_diff_extras: dict | None,
    ant, mode: str,
):
    """Run a single agent step: real LLM + write through synapse.intend.

    Returns dict with tokens, merged flag, conflicts seen, beliefs, etc.
    """
    import synapse

    write_path = os.path.join(repo_root, rel_path)
    content, t_in, t_out = await llm_write(ant, prompt)

    if mode == "no_synapse":
        os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
        existed = os.path.exists(write_path)
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {
            "agent_id": agent_id,
            "path": rel_path,
            "tokens_in": t_in,
            "tokens_out": t_out,
            "wrote_bytes": len(content),
            "overwrote_existing": existed,
            "merged": False,
            "saw_conflicts": False,
            "policy_rationale": None,
            "beliefs_emitted": [],
            "divergences": [],
        }

    # Synapse-managed path
    policy = (
        synapse.MergePolicy.auto_merge if mode == "with_synapse_full"
        else synapse.MergePolicy.redirect
    )

    proposed = {
        "path": rel_path, "content": content, "tool": "write_file",
    }

    final_content = content
    merged_flag = False
    saw_conflicts = False
    rationale = None
    beliefs = []
    divs = []
    aborted = False
    abort_reason = None

    try:
        async with synapse.intend(
            scope=scope_for(rel_path),
            agent=agent_id,
            session=session_id,
            expected_outcome=f"{agent_id} writes {rel_path}",
            blocking=True,
            gate_ms=400,
            merge_policy=policy,
            proposed_action=proposed,
        ) as i:
            saw_conflicts = i.has_conflicts
            rationale = i.policy_rationale

            if i.merged_action and "content" in i.merged_action:
                final_content = i.merged_action["content"]
                merged_flag = True

            os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
            with open(write_path, "w", encoding="utf-8") as f:
                f.write(final_content)

            sd = {
                "content": final_content[:2000],
                "wrote_bytes": len(final_content),
                "path": rel_path,
            }
            if state_diff_extras:
                # Surface domain beliefs (pricing_model, tax_calculation, ...)
                # so the BELIEF extractor + divergence detector see them.
                sd.update(state_diff_extras)
            i.set_state_diff(sd)

            beliefs = list(i.beliefs_emitted)
            divs = list(i.divergences)

    except synapse.SynapseConflict as e:
        # critical_scopes triggered an ABORT — do not write the file.
        aborted = True
        abort_reason = str(e)

    return {
        "agent_id": agent_id,
        "path": rel_path,
        "tokens_in": t_in,
        "tokens_out": t_out,
        "wrote_bytes": len(final_content) if not aborted else 0,
        "merged": merged_flag,
        "saw_conflicts": saw_conflicts,
        "policy_rationale": rationale,
        "beliefs_emitted": beliefs,
        "divergences": divs,
        "aborted": aborted,
        "abort_reason": abort_reason,
    }


async def run_agent_plan(*, agent_id, plan, session_id, repo_root, ant, mode):
    """Run one agent's full plan sequentially within that agent."""
    out = []
    for entry in plan:
        rel_path, prompt, *rest = entry
        extras = rest[0] if rest else None
        try:
            r = await agent_step(
                agent_id=agent_id,
                session_id=session_id,
                repo_root=repo_root,
                rel_path=rel_path,
                prompt=prompt,
                state_diff_extras=extras,
                ant=ant,
                mode=mode,
            )
        except Exception as e:
            r = {
                "agent_id": agent_id, "path": rel_path,
                "error": str(e),
            }
        out.append(r)
        # Tiny gap so the gate window can drain when running parallel.
        await asyncio.sleep(0.1)
    return out


def _read_or_blank(p: str) -> str:
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def coherence_for_file(path_full: str, marker_map: dict) -> tuple[int, int, dict]:
    """Returns (markers_present, markers_total, breakdown)."""
    txt = _read_or_blank(path_full)
    breakdown = {}
    present = 0
    for name, pat in marker_map.items():
        ok = bool(re.search(pat, txt, flags=re.MULTILINE))
        breakdown[name] = ok
        if ok:
            present += 1
    return present, len(marker_map), breakdown


async def run(mode: str) -> dict:
    print(f"\n=== mode: {mode} ===")
    session_id = f"v02_sdlc_{mode}_{uuid.uuid4().hex[:6]}"
    repo_root = f"/tmp/sdlc_billing_{mode}_{uuid.uuid4().hex[:4]}"
    os.makedirs(repo_root, exist_ok=True)

    from anthropic import AsyncAnthropic
    ant = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    bus = state = router_task = router = None

    if mode != "no_synapse":
        import synapse
        synapse.set_llm(synapse.from_anthropic(ant, model="claude-haiku-4-5-20251001"))
        install_kwargs = dict(
            bus_url=REDIS_URL,
            state_dsn=PG_DSN,
            session_id=session_id,
            merge_policy=(
                synapse.MergePolicy.auto_merge
                if mode == "with_synapse_full"
                else synapse.MergePolicy.redirect
            ),
        )
        if mode == "with_synapse_full":
            install_kwargs["emit_beliefs_from_tool_results"] = True
            # Critical scopes that must never be silently overwritten.
            # Match the dotted scope format produced by scope_for().
            install_kwargs["critical_scopes"] = [
                "repo.fs.routes.billing.*",
                "repo.fs.webhooks.stripe.*",
            ]
        result = synapse.install(**install_kwargs)
        print(f"  synapse.install -> {result}")

        from synapse.bus import Bus
        from synapse.state import StateGraph
        from runtime.router.worker import Router

        bus = Bus(REDIS_URL)
        state = StateGraph(PG_DSN)
        await bus.connect()
        await state.connect()
        router = Router(bus, state, session_id, consumer="v02_sdlc_router")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)
    else:
        try:
            from synapse.intend import _runtime
            _runtime.clear()
        except Exception:
            pass

    started = time.time()
    all_results: list[dict] = []

    # Stage 1 — sequential, single agent
    print("  -- Stage 1: requirements --")
    for aid, plan in STAGE_1.items():
        rs = await run_agent_plan(
            agent_id=aid, plan=plan, session_id=session_id,
            repo_root=repo_root, ant=ant, mode=mode,
        )
        all_results.extend(rs)

    # Stage 2 — sequential, single agent (architect sees PM)
    print("  -- Stage 2: architecture --")
    for aid, plan in STAGE_2.items():
        rs = await run_agent_plan(
            agent_id=aid, plan=plan, session_id=session_id,
            repo_root=repo_root, ant=ant, mode=mode,
        )
        all_results.extend(rs)

    # Stage 3 — PARALLEL: 3 implementation engineers
    print("  -- Stage 3: implementation (parallel x3) --")
    s3 = await asyncio.gather(*[
        run_agent_plan(
            agent_id=aid, plan=plan, session_id=session_id,
            repo_root=repo_root, ant=ant, mode=mode,
        )
        for aid, plan in STAGE_3.items()
    ], return_exceptions=True)
    for r in s3:
        if isinstance(r, list):
            all_results.extend(r)
        else:
            all_results.append({"error": str(r)})

    # Let coordinator drain (intentionally — auto_merge needs prior writers
    # resolved before next agent fires).
    await asyncio.sleep(0.5)

    # Stage 4 — PARALLEL: QA + DevOps
    print("  -- Stage 4: QA + DevOps (parallel x2) --")
    s4 = await asyncio.gather(*[
        run_agent_plan(
            agent_id=aid, plan=plan, session_id=session_id,
            repo_root=repo_root, ant=ant, mode=mode,
        )
        for aid, plan in STAGE_4.items()
    ], return_exceptions=True)
    for r in s4:
        if isinstance(r, list):
            all_results.extend(r)
        else:
            all_results.append({"error": str(r)})

    elapsed = time.time() - started
    await asyncio.sleep(0.8)

    if router_task is not None and router is not None:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()

    # ---- Inspect bus + PG ----
    intent_rows = []
    agent_rows = []
    belief_rows = []
    stream_count = 0
    inbox_envelopes: list[dict] = []
    conflict_count_total = 0
    conflict_scope_overlap = 0
    conflict_stale_base = 0
    final_divergences = []

    if mode != "no_synapse" and state is not None and bus is not None:
        intent_rows = await state.pool.fetch(
            "SELECT id, agent_id, scope, status FROM intentions WHERE session_id=$1 ORDER BY created_at",
            session_id,
        )
        agent_rows = await state.pool.fetch(
            "SELECT id FROM agents WHERE session_id=$1", session_id,
        )
        belief_rows = await state.pool.fetch(
            "SELECT agent_id, key, value, confidence, source FROM beliefs WHERE session_id=$1",
            session_id,
        )

        redis = bus.redis
        stream_entries = await redis.xrange(
            f"synapse:session:{session_id}:events", count=500,
        )
        stream_count = len(stream_entries)
        for r in agent_rows:
            entries = await redis.xrange(
                f"synapse:agent:{r['id']}:inbox", count=100,
            )
            for _eid, fields in entries:
                try:
                    env = json.loads(fields["e"])
                    inbox_envelopes.append(env)
                    if env["type"] == "CONFLICT":
                        conflict_count_total += 1
                        kind = (env.get("payload") or {}).get("kind", "")
                        if kind == "scope_overlap":
                            conflict_scope_overlap += 1
                        elif kind == "stale_base_overwrite":
                            conflict_stale_base += 1
                except Exception:
                    pass

        try:
            import synapse
            final_divergences = [
                d.to_dict()
                for d in await synapse.list_divergences(session_id=session_id)
            ]
        except Exception as e:
            print(f"  list_divergences failed: {e}")

    if bus is not None:
        await bus.close()
    if state is not None:
        await state.close()

    # ---- File-level analysis ----
    file_writes: dict[str, list[str]] = {}
    for r in all_results:
        if not isinstance(r, dict) or "path" not in r or "agent_id" not in r:
            continue
        if r.get("aborted"):
            continue
        file_writes.setdefault(r["path"], []).append(r["agent_id"])

    contended = {p: aids for p, aids in file_writes.items() if len(aids) > 1}

    coherence_breakdown = {}
    markers_present_total = 0
    markers_expected_total = 0
    for path, mmap in MARKERS.items():
        present, total, br = coherence_for_file(
            os.path.join(repo_root, path), mmap,
        )
        coherence_breakdown[path] = {
            "present": present, "total": total, "markers": br,
        }
        markers_present_total += present
        markers_expected_total += total

    coherence_score = (
        markers_present_total / markers_expected_total
        if markers_expected_total else 0.0
    )

    # ---- Tokens ----
    tokens_in = sum(r.get("tokens_in", 0) for r in all_results if isinstance(r, dict))
    tokens_out = sum(r.get("tokens_out", 0) for r in all_results if isinstance(r, dict))
    auto_merges = sum(1 for r in all_results if isinstance(r, dict) and r.get("merged"))
    aborts = sum(1 for r in all_results if isinstance(r, dict) and r.get("aborted"))
    live_divergences_during = sum(
        len(r.get("divergences", [])) for r in all_results if isinstance(r, dict)
    )
    beliefs_emitted_during = sum(
        len(r.get("beliefs_emitted", [])) for r in all_results if isinstance(r, dict)
    )

    # ---- Print summary ----
    print(f"  elapsed:                    {elapsed:.1f}s")
    print(f"  total file-write steps:     {len([r for r in all_results if isinstance(r, dict) and 'path' in r])}")
    print(f"  unique files written:       {len(file_writes)}")
    print(f"  contended files:            {len(contended)}  -> {list(contended)}")
    for p, aids in contended.items():
        print(f"      {p:30s} <- {aids}")
    print(f"  tokens in/out:              {tokens_in}/{tokens_out}")
    print(f"  envelopes on stream:        {stream_count}")
    print(f"  intentions persisted (PG):  {len(intent_rows)}")
    print(f"  agents persisted (PG):      {len(agent_rows)}")
    print(f"  beliefs in PG:              {len(belief_rows)}")
    print(f"  CONFLICTs total:            {conflict_count_total}  "
          f"(scope_overlap={conflict_scope_overlap}, stale_base={conflict_stale_base})")
    print(f"  auto-merges performed:      {auto_merges}")
    print(f"  critical-scope aborts:      {aborts}")
    print(f"  live divergences (during):  {live_divergences_during}")
    print(f"  final divergences:          {len(final_divergences)}")
    for d in final_divergences:
        print(f"    {d.get('key')!r}: {len(d.get('distinct_values', []))} distinct "
              f"across {len(d.get('agents_involved', []))} agents (sev={d.get('severity', 0):.2f})")
    print(f"  markers surviving:          {markers_present_total}/{markers_expected_total} "
          f"(coherence={coherence_score:.2f})")
    for path, b in coherence_breakdown.items():
        print(f"    {path}: {b['present']}/{b['total']}")
        for k, ok in b["markers"].items():
            print(f"      {'+' if ok else '-'} {k}")

    return {
        "mode": mode,
        "session_id": session_id,
        "elapsed_seconds": round(elapsed, 2),
        "total_steps": len([r for r in all_results
                            if isinstance(r, dict) and 'path' in r]),
        "unique_files": len(file_writes),
        "contended_files": contended,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "envelopes_on_stream": stream_count,
        "intentions_persisted": len(intent_rows),
        "agents_persisted": len(agent_rows),
        "beliefs_persisted": len(belief_rows),
        "belief_rows": [dict(r) for r in belief_rows],
        "conflicts_total": conflict_count_total,
        "conflicts_scope_overlap": conflict_scope_overlap,
        "conflicts_stale_base_overwrite": conflict_stale_base,
        "auto_merges": auto_merges,
        "critical_scope_aborts": aborts,
        "live_divergences_during": live_divergences_during,
        "beliefs_emitted_during": beliefs_emitted_during,
        "final_divergences": final_divergences,
        "coherence_score": round(coherence_score, 3),
        "markers_present": markers_present_total,
        "markers_expected": markers_expected_total,
        "coherence_breakdown": coherence_breakdown,
        "agent_results": all_results,
    }


async def main():
    print("=== v0.2 SDLC benchmark: 6-agent multi-tenant SaaS billing platform ===")
    await apply_migrations()

    no_syn = await run("no_synapse")
    redirect = await run("with_synapse_redirect")
    full = await run("with_synapse_full")

    print("\n--- summary ---")
    for m, r in [("no_synapse", no_syn),
                 ("with_synapse_redirect", redirect),
                 ("with_synapse_full", full)]:
        print(f"  {m:25s}  coherence={r['coherence_score']:.2f}  "
              f"contended={len(r['contended_files'])}  "
              f"conflicts={r['conflicts_total']}  "
              f"merges={r['auto_merges']}  "
              f"divergences={len(r['final_divergences'])}  "
              f"tokens={r['tokens_in']}/{r['tokens_out']}  "
              f"elapsed={r['elapsed_seconds']}s")

    return {
        "no_synapse": no_syn,
        "with_synapse_redirect": redirect,
        "with_synapse_full": full,
    }


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n--- result.json (trimmed) ---")
    trimmed = {}
    for k, v in result.items():
        c = dict(v)
        # Trim heavy nested fields for the printed JSON
        if "agent_results" in c:
            c["agent_results"] = [
                {kk: vv for kk, vv in r.items()
                 if kk not in ("policy_rationale",)}
                if isinstance(r, dict) else r
                for r in c["agent_results"]
            ]
        trimmed[k] = c
    print(json.dumps(trimmed, indent=2, default=str)[:12000])
