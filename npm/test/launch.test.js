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
const { findUvx, forwardedSignals, uvxArgs } = require('../lib/launch.js');

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
  '    trap \'echo got-int > "$FAKE_UVX_MARK"; exit 0\' INT',
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

// stdin is a pipe, as when an MCP host starts the server.
function launch(bin, args, options) {
  return spawn(process.execPath, [path.join(BIN, `${bin}.js`), ...args], {
    cwd: options.cwd,
    env: envWith(options.path, options.env),
    stdio: ['pipe', 'pipe', 'pipe'],
  });
}

// A uvx that would run if found: the fake script, or node.exe as uvx.exe.
function plantUvx(dir) {
  if (POSIX) {
    fs.writeFileSync(path.join(dir, 'uvx'), FAKE_UVX);
    fs.chmodSync(path.join(dir, 'uvx'), 0o755);
  } else {
    fs.copyFileSync(process.execPath, path.join(dir, 'uvx.exe'));
  }
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

test('findUvx takes the first absolute PATH entry that has uvx, quoted or not', () => {
  const empty = tempDir();
  const first = tempDir();
  const second = tempDir();
  plantUvx(first);
  plantUvx(second);
  const name = POSIX ? 'uvx' : 'uvx.exe';
  const quoted = ['', '.', empty, `"${first}"`, second].join(path.delimiter);
  assert.equal(findUvx(quoted), path.join(first, name));
  assert.equal(findUvx(''), null);
});

test('which signals are passed on, by platform and terminal', () => {
  // MCP host (stdin a pipe) on Linux or macOS: everything.
  assert.deepEqual(forwardedSignals(false, 'linux'), ['SIGTERM', 'SIGHUP', 'SIGINT']);
  // Terminal: Ctrl+C already reached uvx through the process group.
  assert.deepEqual(forwardedSignals(true, 'darwin'), ['SIGTERM', 'SIGHUP']);
  // Windows: SIGINT only comes from the console, and SIGHUP cannot be sent.
  assert.deepEqual(forwardedSignals(false, 'win32'), ['SIGTERM']);
  assert.deepEqual(forwardedSignals(true, 'win32'), ['SIGTERM']);
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

// With stdin a pipe (an MCP host), SIGTERM and SIGINT sent to the launcher
// alone both reach the server. In a terminal, SIGINT is left to the process
// group; that case needs a real terminal and is not tested here.
for (const signal of ['SIGTERM', 'SIGINT']) {
  test(`${signal} sent to the launcher is passed on`, { skip: !POSIX }, async () => {
    const dir = fakeUvxDir();
    const mark = path.join(dir, 'mark');
    const child = launch('nz-openbank-mcp', [], {
      path: `${dir}${path.delimiter}${systemPath()}`,
      env: { FAKE_UVX_ARGS: path.join(dir, 'args'), FAKE_UVX_MODE: 'wait', FAKE_UVX_MARK: mark },
    });
    const done = finished(child);
    await waitForFile(`${mark}.ready`);
    child.kill(signal);
    const result = await done;
    assert.equal(fs.readFileSync(mark, 'utf8').trim(), signal === 'SIGTERM' ? 'got-term' : 'got-int');
    assert.equal(result.code, 0);
  });
}

test('uvx in the working directory or a relative PATH entry is not used', async () => {
  const cwd = tempDir();
  plantUvx(cwd);
  const child = launch('nz-openbank-mcp', [], {
    cwd,
    path: ['.', 'relative', tempDir()].join(path.delimiter),
    env: {},
  });
  child.stdin.end();
  const result = await finished(child);
  assert.equal(result.code, 127);
  assert.match(result.stderr, /uvx was not found on PATH/);
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
