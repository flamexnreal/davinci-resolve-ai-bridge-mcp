# Release procedure

Publishing is a separate maintainer action. Local tests, installation and package checks never publish.

1. Review the complete diff and run the checks in TESTING.md. Complete the manual Resolve Free checklist before claiming live compatibility.
2. Choose the next unused version after checking npm and GitHub tags. Keep `package.json`, `package-lock.json`, `pyproject.toml` and `bridge/operations.py:AGENT_VERSION` synchronized. The installer imports that constant; it has no separate version to bump.
3. Turn the top **Unreleased** section in RELEASE_NOTES.md into the selected release/version/date. Keep the documented limitations and validation evidence.
4. Run `npm ci`, `npm run build`, `python3 -m unittest discover -s tests -v`, and `node tools/check-package.mjs`. Inspect the actual tarball via the check. The npm payload must contain requirements.txt and every bridge/agent file it needs.
5. Review `git diff --check` and `git status`. Exclude private tokens, installed runtimes, temporary audio/images, dependency folders and local configuration backups.
6. Commit the reviewed files. Push without force. Create the selected annotated tag and GitHub release with the prepared description.
7. Publish the tested npm package with the account's normal authentication/2FA flow. Do not print credentials or tokens. `scripts/release.sh VERSION` is an explicit npm-publishing helper; it does not commit/tag/push or create a GitHub release.
8. Verify the public GitHub tag/release and `npm view davinci-resolve-ai-bridge-mcp version`. Confirm a fresh npm download contains requirements.txt and that the installed `--serve` command starts an MCP server, not the installer.

Do not represent source decoding as the processed Resolve viewer/Fairlight mix. Do not claim Studio-only AI features or broad live-platform validation based solely on mocks.
