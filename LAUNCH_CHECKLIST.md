# Synapse v0.2.8 — Launch Checklist

Everything that's built; everything that's left. Updated 2026-05-12.

---

## ⚙️ Code state — all done

- [x] **374 tests passing** (371 base + 3 new OpenAI THOUGHT regression tests)
- [x] **10 Python framework adapters + 1 Node (OpenClaw)** — all verified through real LLM-driven dispatch with INTENTIONs persisted to Postgres in Modal sandbox
- [x] **Convergence bench**: 10/10 V1_PASS **deterministic** — v26 ↔ v27 reproduced byte-for-byte (23 intents / 9 THOUGHTs, same agent counts per role)
- [x] **Cross-vendor cooperative-build proof**: v32 bundle in `bench/results/v32_app_bundle/` — 10 vendor agents → 1 working Flask app, `GET /todos → 200` locally
- [x] **OpenAI THOUGHT-capture parity with Anthropic** (v0.2.8 fix in `synapse/llm_thoughts.py`): PSEUDO_THOUGHT fallback captures `message.content` when no native `reasoning` field is present
- [x] **HuggingFace deep NLA module** (`synapse.llm_nla_hf`) — logits + attention + hidden-states capture for self-hosted LLMs (lazy import; torch optional)
- [x] **L2 router gate-window** drains inbox on empty fast-path (v0.2.7 fix verified deterministic in v27)
- [x] **Per-task ContextVar agent attribution** (v0.2.2 fix) — race-free under `asyncio.gather`
- [x] **6 trace-format importers** (OpenInference, LangSmith, Bedrock, Vertex, Azure, JSONL) all auto-detected
- [x] **REST API + MCP server** (`synapse-mcp`) — 5 tools exposed to external agents
- [x] **7 IDE/CLI plugins** (Cursor, Codex CLI, VS Code, Claude Code, Aider, Continue, Cline) in `launch/ide-plugins/`
- [x] **Streaming WebSocket server** (`python -m synapse.streaming.server`)
- [x] **UI**: cross-vendor cooperative-build page at `/builds/v32` — works offline (reads `bench/results/v32_app_bundle/` directly, no gateway needed)
- [x] **PyPI wheel built** (`sdk-python/dist/*.whl` — needs republish for 0.2.8)
- [x] **README**: rewritten for v0.2.8 — cooperative-build hero, accurate badges, honest positioning vs knowledge-graph frameworks
- [x] **Public benchmark doc**: full v21–v32 history in `bench/PUBLIC_BENCHMARK.md` Phase 10
- [x] **27 unreleased commits** committed locally and ready to push

---

## 🔑 What's left — YOUR token-gated work

### Tier 1 — Day-of-launch must-haves (~30 min total)

#### [ ] Push to GitHub
```bash
cd /c/C3/synapse
git push origin main
git push origin v0.2.8       # after tagging below
```
No tokens needed — `origin` is already `https://github.com/arajgor1/synapse`.
**Until this runs, none of the work above is visible to anyone.**

#### [ ] Tag v0.2.8 + create GitHub release
```bash
git tag -a v0.2.8 -m "v0.2.8: cross-vendor cooperative app build"
git push origin v0.2.8
```
Then on GitHub:
- https://github.com/arajgor1/synapse/releases/new
- Tag: `v0.2.8`
- Title: `v0.2.8 — Cross-vendor cooperative app build`
- Body: paste `launch/RELEASE_NOTES_v0.2.8.md` (drafted in this commit)

#### [ ] PyPI publish
```bash
cd /c/C3/synapse/sdk-python
# bump version in pyproject.toml to 0.2.8 first
python -m build
twine upload dist/synapse_protocol-0.2.8*
```
Needs: PyPI token.
After: `pip install --upgrade synapse-protocol` gives users v0.2.8.

#### [ ] npm publish (TS SDK)
```bash
cd /c/C3/synapse/sdk-typescript
npm version 0.2.8
npm publish --access public
```
Needs: npm account.

### Tier 2 — Launch-day collateral (~3 hours)

#### [ ] Record demo GIF
- Open `/builds/v32` on `localhost:3000` (run `npm run dev` in `ui/`)
- Record 30s: scroll verdict band → click a vendor card → preview file → scroll envelope timeline → click copy on reproduce block
- Save to `launch/demos/v32_cooperative_build.gif`
- Reference from README hero

#### [ ] Blog post
- Skeleton drafted in `launch/BLOG_v0.2.8.md`
- Topic: "10 vendor SDKs cooperated to build a Flask app. The app actually runs."
- ~800-1200 words. Include the v32 reproduce command. Link the bundle.

#### [ ] HN Show post
- Draft in `launch/HN_v0.2.8.md`
- Title: `Show HN: Synapse — audit layer for agentic teams across vendors`
- Post at 9-10am ET on a Tuesday or Wednesday
- Be ready to answer comments for the first 2 hours

#### [ ] Twitter / X thread
- Draft in `launch/TWITTER_v0.2.8.md`
- 5-7 tweets, lead with the screenshot, end with the repo link

#### [ ] Reddit r/MachineLearning + r/LocalLLaMA
- Same content as HN
- Draft in `launch/REDDIT_v0.2.8.md`

### Tier 3 — Community infrastructure (Semantica-style polish, ~1 day)

These differentiate a "looks serious" launch from a "thrown over the wall" launch.

#### [ ] Discord server
- Create at https://discord.com/developers/applications
- Channels: `#general`, `#bugs`, `#showcase`, `#release-notes`
- Add invite badge to README (placeholder slot already in header)

#### [ ] X / Twitter account
- `@SynapseProtocol` or `@BuildSynapse` (Semantica is `@BuildSemantica`)
- Pin the launch thread

#### [ ] Logo
- Currently using `🧬` emoji as a placeholder
- Get a proper SVG: dark + light variant
- Drop into root + README

#### [ ] Multi-language README translations
- Semantica uses `readme-i18n.com`. Link form: `https://readme-i18n.com/arajgor1/synapse?lang=de`
- One badge per language

#### [ ] Pepy.tech download badge
- Auto-activates once PyPI volume crosses ~50
- Badge URL: `https://static.pepy.tech/badge/synapse-protocol`

---

## 🩹 Known carry-forward (v0.2.9 candidates)

Be upfront in launch — readers find these in `PUBLIC_BENCHMARK.md` anyway.

1. **3 of 10 OpenAI adapters dispatch tools with empty content** (langgraph, smolagents, agno under gpt-4o-mini). Fallback rescues the artifact but no INTENT registered. LLM-behavior issue, not adapter bug. Workaround: Anthropic route (v27 was 10/10 with all intents).
2. **L2 router gate-window — Redis ZADD-based active-scope tracking** would tighten inter-process ordering. Existing tests pass; optional.
3. **HuggingFace deep NLA exercised under torch** — module shipped but not run in Modal yet (image lacks torch by design — opt-in).
4. **Replay over WebRTC** — UI does static replay; live replay over WS works only when gateway is up.

---

## 🚦 Launch trigger

Once all Tier 1 boxes are checked **and** at least the HN draft is ready, hit publish in this order:

1. `git push origin main v0.2.8`
2. Create GitHub release with release notes
3. `twine upload` to PyPI
4. `npm publish`
5. Post blog
6. Post HN at 9-10am ET (best window)
7. Post Twitter thread immediately after HN
8. Cross-post to Reddit 2 hours later (avoid spam-detection)
9. Monitor inbox + comments for 24 hours

---

## Cumulative spend across all v0.2.x iterations: ~$48 Modal+LLM.
