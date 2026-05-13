# Security Policy

## Supported Versions

We actively patch security issues in the following versions of Synapse:

| Version | Supported |
|---------|-----------|
| 0.2.8   | ✅ |
| 0.2.7   | ✅ |
| 0.2.6   | ✅ |
| < 0.2.6 | ❌ — please upgrade |

## Reporting a Vulnerability

We take security seriously. If you discover a vulnerability in Synapse,
please follow these steps:

### 1. Do NOT open a public GitHub issue

Vulnerabilities should be reported privately so we have time to patch
before details are public.

### 2. Use GitHub Security Advisories

Open a private advisory at:

https://github.com/arajgor1/synapse/security/advisories/new

Or, if that's not available to you, email **aadityarajgor27@gmail.com**
with subject prefix `[SECURITY]`.

### 3. Include

- A description of the issue
- Steps to reproduce or proof-of-concept
- The version of Synapse affected
- Any suggested mitigation

## What to Expect

- **Acknowledgement** within 72 hours
- **Triage + severity assessment** within 7 days
- **Fix released** within 30 days for high/critical issues; we'll keep you
  posted on lower-severity items
- **Public disclosure** coordinated with the reporter

## Scope

In scope:
- The Python SDK (`synapse-protocol`)
- The TypeScript SDK
- The REST gateway and WebSocket server
- The MCP server (`synapse-mcp`)
- The Modal bench payloads
- The UI (`ui/` Next.js app)

Out of scope (report to the upstream project):
- Vulnerabilities in third-party framework SDKs we adapt (AutoGen,
  LangChain, CrewAI, smolagents, Agno, LlamaIndex, Pydantic AI, OpenAI
  Agents, Google ADK, Hermes, OpenClaw) — please report those to the
  upstream maintainers.
- Vulnerabilities in the LLM providers (Anthropic, OpenAI, Google) — report
  to those providers directly.

## Security Hygiene We Recommend

When deploying Synapse, please:

1. **Never commit API keys to the repo.** Use environment variables.
2. **Pin Synapse to a specific version** in `requirements.txt` /
   `pyproject.toml` rather than tracking `main`.
3. **Run the gateway behind authentication** if exposed to anything beyond
   localhost — the default v0.2.8 build does not enforce auth on
   `/api/sessions/*`.
4. **Encrypt Postgres at rest** if INTENTION envelopes contain sensitive
   scopes or action descriptions (they often do — they describe what your
   agents are about to do).

## Acknowledgements

We're grateful to security researchers who responsibly report issues.
Reporters who would like public acknowledgement will be credited in our
release notes.

Thank you for helping keep Synapse and its users safe.
