# Maintainer handoff

The current local changes are **unreleased**. Version/tag selection belongs to the maintainer at publication time. README.md, RELEASE_NOTES.md and docs/TESTING.md describe current behavior; earlier project notes are not current implementation instructions.

## Architecture

- `bridge/operations.py`: single standard-library implementation of Resolve operations, including source audio/image handling and review workflows.
- `bridge/server.py`: MCP schemas, results and native image content.
- `bridge/client.py` / `bridge/transport.py`: authenticated Console queue and transport selection.
- `bridge/direct.py`: isolated native-library probing; preserve crash containment.
- `agent/ResolveConsole.py`: worker inside Resolve Free; validates each request token.
- `install.py`: private runtime, optional FFmpeg, client configuration backups/merges and menu setup.
- `bin/cli.js`: cross-platform Python discovery; install by default, explicit `--serve` for MCP.
- `tests/`: regression checks using mocks and synthetic media; no live editing.

The unused standalone audio_analysis.py and frame_capture.py implementations have been removed. Website libraries are development dependencies; npm ships the bridge rather than the built website.

## Current changes

Packaging and configuration safety, unique clip IDs, boundary/timecode fixes, checkpointed splits, graph-preserving owned speed nodes, source image/audio fixes, preview/compare tools, project health, capability reporting, review markers and bounded dialogue-cut application. The README details limitations and upgrade behavior.

## Before publishing

Read docs/RELEASING.md. Choose and synchronize the version; keep a clear distinction between passing automated checks and manual Resolve Free integration results. Do not upload runtime tokens, private client configs, decoder paths or generated media. No automatic publish workflow is configured.
