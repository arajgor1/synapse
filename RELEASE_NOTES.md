# Release Notes

For per-version release notes, see [`CHANGELOG.md`](CHANGELOG.md).

## Latest release — v0.2.8

**Cross-vendor cooperative app build.** Ten different framework agents
collaborated on one Synapse session and built a Flask Todo app that
actually runs.

- `GET /todos → 200` (Flask test_client, reproducible locally)
- Bundle committed at [`bench/results/v32_app_bundle/`](bench/results/v32_app_bundle/)
- 374 tests passing
- 10/10 framework adapters PASS deterministically (v26 ↔ v27 byte-for-byte
  reproducible)
- OpenAI THOUGHT-capture parity with Anthropic landed
- HuggingFace deep NLA module (logits + attention + hidden-states) shipped

[Full release notes on GitHub →](https://github.com/arajgor1/synapse/releases/tag/v0.2.8)

## Past releases

See [`CHANGELOG.md`](CHANGELOG.md) for all release notes from v0.2.0 onward.

## How releases work

- **Cadence**: roughly weekly during the v0.2.x → v0.3.0 push.
- **Versioning**: [Semantic Versioning](https://semver.org/). Bug fixes are
  patch (0.2.x → 0.2.x+1). New adapters and protocol additions are minor
  (0.2.x → 0.3.0). Breaking protocol changes are major (0.x.x → 1.0.0).
- **Tags**: every release is tagged on GitHub:
  https://github.com/arajgor1/synapse/tags
- **PyPI**: `synapse-protocol` on https://pypi.org/project/synapse-protocol/
- **npm** (TypeScript SDK): coming soon

## Reproducing a release

Every release tag is a verified snapshot. To reproduce v0.2.8:

```bash
git clone https://github.com/arajgor1/synapse
cd synapse
git checkout v0.2.8
pip install -e ./sdk-python
python -m pytest sdk-python/tests/ -q
```

To reproduce the cross-vendor cooperative-build claim specifically:

```bash
pip install flask
cd bench/results/v32_app_bundle
python -c "import main; print(main.app.test_client().get('/todos').status_code)"
# → 200
```
