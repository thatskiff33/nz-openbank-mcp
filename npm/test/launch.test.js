'use strict';

// The launcher must run the pinned PyPI release through uvx with the caller's
// arguments, stdio and exit status intact. A fake uvx stands in for uv: a shell
// script on Linux and macOS, and a renamed copy of node.exe on Windows (which
// rejects uvx's --from option, proving it was found and its status passed on).

const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

const { version } = require('../package.json');
const { uvxArgs } = require('../lib/launch.js');

const BIN = path.join(__dirname, '..', 'bin');
const POSIX = process.platform !== 'win32';
const NL = '\n';

const FAKE_UVX = [
  '#!/bin/sh',
  'printf "%s\\n" "$@" > "$FAKE_UVX_ARGS"',
  'case "$FAKE_UVX_MODE" in',
  '  echo) cat ;;',
  '  exit) exit "$FAKE_UVX_CODE" ;;',
  '  selfkill) kill -TERM $$ ;;',
  '  wait)',
  '    trap \'echo got-term > "$FAKE_UVX_MARK"; exit 0\' TERM',
  '    echo ready > "$FAKE_UVX_MARK.ready"',
  '    while :; do sleep 1 & wait $!; done ;;',
  'esac',
  '',
].join(NL);

function tempDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'nz-openbank-mcp-npm-'));
}

function fakeUvxDir() {
  const dir = tempDir();
  const uvx = path.join(dir, 'uvx');
  fs.writeFileSync(uvx, FAKE_UVX);
  fs.chmodSync(uvx, 0o755);
  return dir;
}

// The environment with PATH replaced, whatever its case (Windows uses Path).
function envWith(pathValue, extra) {
  const env = { ...process.env, ...extra };
  for (const key of Object.keys(env)) {
    if (key.toUpperCase() === 'PATH') {
      delete env[key];
    }
  }
  env.PATH = pathValue;
  return env;
}

function systemPath() {
  return process.env.PATH || process.env.Path || '';
}

function launch(bin, args, options) {
  return spawn(process.execPath, [path.join(BIN, `${bin}.js`), ...args], {
    env: envWith(options.path, options.env),
    stdio: ['pipe', 'pipe', 'pipe'],
  });
}

function finished(child) {
  return new Promise((resolve) => {
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
    });
    child.on('close', (code, signal) => resolve({ code, signal, stdout, stderr }));
  });
}

async function waitForFile(file) {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (fs.existsSync(file)) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`${file} never appeared`);
}

function argsSeen(file) {
  return fs.readFileSync(file, 'utf8').split(NL).slice(0, -1);
}

test('uvx arguments pin the PyPI release of this version', () => {
  assert.deepEqual(uvxArgs('nz-openbank-mcp', ['--x']), [
    '--from',
    `nz-openbank-mcp==${version}`,
    'nz-openbank-mcp',
    '--x',
  ]);
});

test('passes the pinned release and the arguments unchanged', { skip: !POSIX }, async () => {
  const dir = fakeUvxDir();
  const argsFile = path.join(dir, 'args');
  const child = launch('nz-openbank-mcp', ['a b', '--flag', '$HOME', ''], {
    path: `${dir}${path.delimiter}${systemPath()}`,
    env: { FAKE_UVX_ARGS: argsFile, FAKE_UVX_MODE: 'exit', FAKE_UVX_CODE: '0' },
  });
  child.stdin.end();
  const result = await finished(child);
  assert.equal(result.code, 0);
  assert.deepEqual(argsSeen(argsFile), [
    '--from',
    `nz-openbank-mcp==${version}`,
    'nz-openbank-mcp',
    'a b',
    '--flag',
    '$HOME',
    '',
  ]);
});

test('the HTTP bin starts the HTTP entrypoint', { skip: !POSIX }, async () => {
  const dir = fakeUvxDir();
  const argsFile = path.join(dir, 'args');
  const child = launch('nz-openbank-mcp-http', [], {
    path: `${dir}${path.delimiter}${systemPath()}`,
    env: { FAKE_UVX_ARGS: argsFile, FAKE_UVX_MODE: 'exit', FAKE_UVX_CODE: '0' },
  });
  child.stdin.end();
  await finished(child);
  assert.deepEqual(argsSeen(argsFile), [
    '--from',
    `nz-openbank-mcp==${version}`,
    'nz-openbank-mcp-http',
  ]);
});

test('stdin and stdout pass straight through', { skip: !POSIX }, async () => {
  const dir = fakeUvxDir();
  const child = launch('nz-openbank-mcp', [], {
    path: `${dir}${path.delimiter}${systemPath()}`,
    env: { FAKE_UVX_ARGS: path.join(dir, 'args'), FAKE_UVX_MODE: 'echo' },
  });
  const message = '{"jsonrpc":"2.0","id":1,"method":"ping"}' + NL;
  child.stdin.end(message);
  const result = await finished(child);
  assert.equal(result.code, 0);
  assert.equal(result.stdout, message);
  assert.equal(result.stderr, '');
});

test('the exit status of uvx is the exit status of the launcher', { skip: !POSIX }, async () => {
  const dir = fakeUvxDir();
  const child = launch('nz-openbank-mcp', [], {
    path: `${dir}${path.delimiter}${systemPath()}`,
    env: { FAKE_UVX_ARGS: path.join(dir, 'args'), FAKE_UVX_MODE: 'exit', FAKE_UVX_CODE: '7' },
  });
  child.stdin.end();
  assert.equal((await finished(child)).code, 7);
});

test('a server killed by a signal ends the launcher with it', { skip: !POSIX }, async () => {
  const dir = fakeUvxDir();
  const child = launch('nz-openbank-mcp', [], {
    path: `${dir}${path.delimiter}${systemPath()}`,
    env: { FAKE_UVX_ARGS: path.join(dir, 'args'), FAKE_UVX_MODE: 'selfkill' },
  });
  child.stdin.end();
  const result = await finished(child);
  assert.equal(result.signal, 'SIGTERM');
});

test('SIGTERM is passed on and SIGINT is left to the process group', { skip: !POSIX }, async () => {
  const dir = fakeUvxDir();
  const mark = path.join(dir, 'mark');
  const child = launch('nz-openbank-mcp', [], {
    path: `${dir}${path.delimiter}${systemPath()}`,
    env: { FAKE_UVX_ARGS: path.join(dir, 'args'), FAKE_UVX_MODE: 'wait', FAKE_UVX_MARK: mark },
  });
  const done = finished(child);
  await waitForFile(`${mark}.ready`);

  // SIGINT to the launcher alone: neither it nor the server stops.
  child.kill('SIGINT');
  await new Promise((resolve) => setTimeout(resolve, 300));
  assert.equal(child.exitCode, null);
  assert.equal(fs.existsSync(mark), false);

  child.kill('SIGTERM');
  const result = await done;
  assert.equal(fs.readFileSync(mark, 'utf8').trim(), 'got-term');
  assert.equal(result.code, 0);
});

test('a missing uvx explains how to install uv and writes nothing to stdout', async () => {
  const child = launch('nz-openbank-mcp', [], { path: tempDir(), env: {} });
  child.stdin.end();
  const result = await finished(child);
  assert.equal(result.code, 127);
  assert.equal(result.stdout, '');
  assert.match(result.stderr, /uvx was not found on PATH/);
  assert.match(result.stderr, /docs\.astral\.sh\/uv/);
});

test('Windows finds uvx.exe on PATH and passes on its status', { skip: POSIX }, async () => {
  const dir = tempDir();
  fs.copyFileSync(process.execPath, path.join(dir, 'uvx.exe'));
  const child = launch('nz-openbank-mcp', [], { path: dir, env: {} });
  child.stdin.end();
  const result = await finished(child);
  // node.exe as uvx.exe: "bad option: --from", exit status 9.
  assert.equal(result.code, 9);
  assert.match(result.stderr, /--from/);
});
