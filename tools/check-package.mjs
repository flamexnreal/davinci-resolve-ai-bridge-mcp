#!/usr/bin/env node
// Validate the actual npm payload without publishing or running the installer.
import { execFileSync } from 'node:child_process';
import { readFileSync, mkdtempSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const packageJson = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const directory = mkdtempSync(join(tmpdir(), 'resolve-package-'));
try {
  const [packed] = JSON.parse(execFileSync(npm, ['pack', '--json', '--ignore-scripts', '--pack-destination', directory], { cwd: root, encoding: 'utf8', shell: process.platform === 'win32' }));
  const files = new Set(packed.files.map(file => file.path));
  for (const required of ['requirements.txt', 'install.py', 'bridge/operations.py', 'bridge/server.py', 'bin/cli.js', 'agent/ResolveConsole.py']) {
    if (!files.has(required)) throw new Error(`Missing required npm file: ${required}`);
  }
  if (files.has('dist/index.html') || Object.keys(packageJson.dependencies || {}).length) throw new Error('Website assets/dependencies leaked into CLI package.');
  // Read the manifest from the real archive too; listing alone can hide stale payloads.
  const manifest = JSON.parse(execFileSync('tar', ['-xOf', join(directory, packed.filename), 'package/package.json'], { encoding: 'utf8' }));
  if (manifest.version !== packageJson.version) throw new Error('Packed version mismatch.');
  console.log(`Package verified: ${packed.entryCount} files, ${packed.unpackedSize} unpacked bytes. Nothing published.`);
} finally { rmSync(directory, { recursive: true, force: true }); }
