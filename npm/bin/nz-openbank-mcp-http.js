#!/usr/bin/env node
'use strict';

// HTTP server: runs `uvx --from nz-openbank-mcp==<version> nz-openbank-mcp-http`.
require('../lib/launch.js').run('nz-openbank-mcp-http');
