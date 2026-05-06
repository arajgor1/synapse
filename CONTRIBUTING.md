# Contributing to Synapse

The protocol is the artifact that matters most. Implementation choices are negotiable; protocol semantics are not, except via explicit ADR.

## Before opening a PR

1. **Protocol changes** require an ADR in `spec/adr/`. Open an issue first to discuss.
2. **Adapter additions** require: implementation, capability declaration, passing the standardized adapter test suite, and benchmark output.
3. **Router/coordinator changes** require: a measurable target (latency or cost) and a benchmark showing the change moves the metric.
4. **SDK changes** require: backward compatibility within a minor version. Breaking changes need a major version bump.

## Local development

```bash
# Bring up Redis + Postgres
docker compose up -d

# Run the protocol schema validator
python -m synapse.spec.validate

# Run tests
pytest
```

## Repository conventions

- Schemas are JSON Schema 2020-12.
- Python is type-checked with mypy strict mode.
- Adapters live in `adapters/{tier}/` and follow the structure of the reference Anthropic adapter.
- All ADRs are numbered sequentially (`ADR-0001`, `ADR-0002`, ...).

## How to propose a new message type

1. Open an issue describing the gap and the use case.
2. Write a draft schema as `x-YOUR_TYPE.schema.json` (the `x-` prefix marks it experimental).
3. Implement adapter behavior in at least one reference adapter.
4. Run a real coordination scenario that uses it.
5. If accepted, propose promotion to standard via ADR and version bump.

Experimental types may be removed without a deprecation window. Standard types follow the versioning rules in `spec/README.md`.

## License

By contributing, you agree your contributions are licensed under Apache 2.0.
