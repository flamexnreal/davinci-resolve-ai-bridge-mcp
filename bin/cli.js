#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { homedir } from 'node:os';
import { existsSync } from 'node:fs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
let command;
let childArgs;
if (args[0] === '--serve') {
  const home = process.env.RESOLVE_AI_BRIDGE_HOME || join(homedir(), '.resolve-ai-bridge');
  command = join(home, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const server = join(home, 'bridge', 'server.py');
  if (!existsSync(command) || !existsSync(server)) {
    console.error('Resolve AI Bridge is not installed. Run npx davinci-resolve-ai-bridge-mcp first.');
    process.exit(1);
  }
  childArgs = [server, ...args.slice(1)];
} else {
  const candidates = process.platform === 'win32' ? [['py', '-3'], ['python'], ['python3']] : [['python3'], ['python']];
  const selected = candidates.find(([exe, ...prefix]) => {
    const check = spawnSync(exe, [...prefix, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'], { stdio: 'ignore', timeout: 10000 });
    return check.status === 0;
  });
  if (!selected) {
    console.error('Python 3.10+ is required. Install it from https://www.python.org/downloads/ and retry.');
    process.exit(1);
  }
  [command, ...childArgs] = selected;
  childArgs.push(join(root, 'install.py'), ...args);
}
const child = spawn(command, childArgs, { stdio: 'inherit' });
child.on('error', (error) => { console.error(`Could not start Resolve AI Bridge: ${error.message}`); process.exit(1); });
child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
