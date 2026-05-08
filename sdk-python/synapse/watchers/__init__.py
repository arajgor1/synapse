"""File-system watchers — IDE / CLI agent integration path.

When an agent runs through Cursor / Claude Code CLI / Codex / VS Code
Copilot / Aider, it doesn't call ``synapse.intend()`` directly.
But every tool call eventually shows up as a filesystem write.

This module watches a working directory and emits Synapse INTENTION
envelopes on every file write, attributing the writer based on a
`SYNAPSE_AGENT_ID` env var (set by the wrapper script invoking the
IDE/CLI agent).

Reduced fidelity vs SDK-native integration (we see writes post-fact,
not intent mid-thinking) but covers the largest user segment that has
no other path.
"""
from .fs_watcher import watch_directory, FSWatcher

__all__ = ["watch_directory", "FSWatcher"]
