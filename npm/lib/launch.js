'use strict';

// Starts the Python package from PyPI with uvx, pinned to this npm package's
// version, so `npx nz-openbank-mcp@X.Y.Z` runs nz-openbank-mcp X.Y.Z.
// stdio is inherited because MCP clients speak JSON-RPC over it: nothing here
// may write to stdout. No shell is involved, so arguments pass through as-is.

const { spawn } = require('node:child_process');
const { EOL } = require('node:os');
const { version } = require('../package.json');

const PACKAGE = 'nz-openbank-mcp';
const UV_INSTALL = 'https://docs.astral.sh/uv/getting-started/installation/';
// Hosts stop servers with SIGTERM, which only reaches this process, so it is
// passed on. Ctrl+C reaches the whole process group (on Windows, every process
// on the console), so uvx already gets SIGINT: forwarding it would deliver it
// twice and turn a graceful shutdown into a forced one. The launcher only stays
// alive until uvx exits.
const FORWARDED_SIGNALS = ['SIGTERM', 'SIGHUP'];
const IGNORED_SIGNALS = ['SIGINT'];

function uvxArgs(entry, args) {
  return ['--from', `${PACKAGE}==${version}`, entry, ...args];
}

function run(entry, args = process.argv.slice(2)) {
  const child = spawn('uvx', uvxArgs(entry, args), { stdio: 'inherit', windowsHide: true });
  let startFailed = false;

  const forward = (signal) => {
    if (child.exitCode === null && child.signalCode === null) {
      child.kill(signal);
    }
  };
  const ignore = () => {};
  const stopForwarding = () => {
    for (const signal of FORWARDED_SIGNALS) {
      process.removeListener(signal, forward);
    }
    for (const signal of IGNORED_SIGNALS) {
      process.removeListener(signal, ignore);
    }
  };
  for (const signal of FORWARDED_SIGNALS) {
    process.on(signal, forward);
  }
  for (const signal of IGNORED_SIGNALS) {
    process.on(signal, ignore);
  }

  child.on('error', (error) => {
    startFailed = true;
    stopForwarding();
    if (error.code === 'ENOENT') {
      process.stderr.write(
        `${entry}: uvx was not found on PATH. This npm package starts the Python ` +
          `release from PyPI with uv. Install uv (${UV_INSTALL}), then try again.${EOL}`,
      );
      process.exitCode = 127;
    } else {
      process.stderr.write(`${entry}: could not start uvx: ${error.message}${EOL}`);
      process.exitCode = 1;
    }
  });

  child.on('exit', (code, signal) => {
    stopForwarding();
    if (startFailed) {
      return;
    }
    if (signal) {
      // End the same way the server did, so the host sees the same signal.
      process.kill(process.pid, signal);
      return;
    }
    process.exitCode = code === null ? 1 : code;
  });
}

module.exports = { run, uvxArgs };
