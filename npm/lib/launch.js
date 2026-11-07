'use strict';

// Starts the Python package from PyPI with uvx, pinned to this npm package's
// version, so `npx nz-openbank-mcp@X.Y.Z` runs nz-openbank-mcp X.Y.Z.
// stdio is inherited because MCP clients speak JSON-RPC over it: nothing here
// may write to stdout. No shell is involved, so arguments pass through as-is.

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { isatty } = require('node:tty');
const { version } = require('../package.json');

const PACKAGE = 'nz-openbank-mcp';
const UV_INSTALL = 'https://docs.astral.sh/uv/getting-started/installation/';
const WINDOWS = process.platform === 'win32';

function uvxArgs(entry, args) {
  return ['--from', `${PACKAGE}==${version}`, entry, ...args];
}

// uvx from an absolute PATH directory. Searched here rather than by spawn,
// because Windows would look in the current directory first.
function findUvx(pathValue) {
  const name = WINDOWS ? 'uvx.exe' : 'uvx';
  for (const entry of pathValue.split(path.delimiter)) {
    const dir = entry.startsWith('"') && entry.endsWith('"') ? entry.slice(1, -1) : entry;
    if (!path.isAbsolute(dir)) {
      continue;
    }
    const candidate = path.join(dir, name);
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
      if (fs.statSync(candidate).isFile()) {
        return candidate;
      }
    } catch {
      // Not in this directory.
    }
  }
  return null;
}

// Hosts stop servers with SIGTERM (or SIGINT), sent to this process only, so
// those are passed on. In a terminal, Ctrl+C already reaches uvx through the
// process group (on Windows, every process on the console), so SIGINT is not
// passed on there: a second one would turn a graceful shutdown into a forced
// one. Windows cannot send SIGHUP to a child.
function forwardedSignals(interactive) {
  const signals = ['SIGTERM'];
  if (!WINDOWS) {
    signals.push('SIGHUP');
  }
  if (!interactive) {
    signals.push('SIGINT');
  }
  return signals;
}

function run(entry, args = process.argv.slice(2)) {
  const uvx = findUvx(process.env.PATH || '');
  if (uvx === null) {
    process.stderr.write(
      `${entry}: uvx was not found on PATH. This npm package starts the Python ` +
        `release from PyPI with uv. Install uv (${UV_INSTALL}), then try again.${os.EOL}`,
    );
    process.exitCode = 127;
    return;
  }

  let child;
  try {
    child = spawn(uvx, uvxArgs(entry, args), { stdio: 'inherit', windowsHide: true });
  } catch (error) {
    process.stderr.write(`${entry}: could not start uvx: ${error.message}${os.EOL}`);
    process.exitCode = 1;
    return;
  }

  let started = false;
  const interactive = isatty(0);
  const forwarded = forwardedSignals(interactive);
  const ignored = interactive ? ['SIGINT'] : [];
  const forward = (signal) => {
    if (child.exitCode === null && child.signalCode === null) {
      try {
        child.kill(signal);
      } catch {
        // Already gone; the exit event reports how it ended.
      }
    }
  };
  const ignore = () => {};
  const stopHandling = () => {
    for (const signal of forwarded) {
      process.removeListener(signal, forward);
    }
    for (const signal of ignored) {
      process.removeListener(signal, ignore);
    }
  };
  for (const signal of forwarded) {
    process.on(signal, forward);
  }
  for (const signal of ignored) {
    process.on(signal, ignore);
  }

  child.on('spawn', () => {
    started = true;
  });

  child.on('error', (error) => {
    // After the start, an error is a failed kill(); the exit event follows.
    if (started) {
      return;
    }
    stopHandling();
    process.stderr.write(`${entry}: could not start uvx: ${error.message}${os.EOL}`);
    process.exitCode = 1;
  });

  child.on('exit', (code, signal) => {
    stopHandling();
    if (signal) {
      // End the same way the server did. If this process ignores that signal
      // (Node ignores SIGPIPE), the shell convention 128 + n still reports it.
      process.exitCode = 128 + (os.constants.signals[signal] || 0);
      process.kill(process.pid, signal);
      return;
    }
    process.exitCode = code === null ? 1 : code;
  });
}

module.exports = { findUvx, run, uvxArgs };
