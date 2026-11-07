#!/usr/bin/env node
'use strict';

// stdio server: runs `uvx --from nz-openbank-mcp==<version> nz-openbank-mcp`.
require('../lib/launch.js').run('nz-openbank-mcp');
