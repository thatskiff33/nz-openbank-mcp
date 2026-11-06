# Privacy Policy

`nz-openbank-mcp` is open-source software you run yourself. The maintainers
operate no service for it, receive none of your data, and cannot see how you
use it.

## What the software handles

- **Akahu tokens.** Your App Token and User Token, supplied by your MCP client
  or host environment. They are sent only to the Akahu API
  (`api.akahu.io`) and are never logged.
- **Account and transaction data.** Fetched from Akahu when a tool is called
  and returned to your MCP client. The server does not store it. Account
  numbers are shown in full unless `AKAHU_MASK_ACCOUNTS=true`, which masks
  them to the bank code, the last four digits and the suffix. Transaction
  descriptions are passed through as the bank supplied them and can include
  account numbers.
- **HTTP mode only.** When you self-host the HTTP server with OAuth, Google
  confirms who is signing in, and the server keeps encrypted OAuth state
  (client registrations, pending codes and Google tokens) in its state
  directory on your host until it expires.

## Who else sees data

- **Akahu** receives your tokens and the account and date filters of each
  request. See the [Akahu privacy notice](https://www.akahu.nz/privacy-notice).
- **Your AI provider.** Whatever a tool returns becomes part of your
  conversation and is sent to the company behind your MCP client or model
  (for example Anthropic, OpenAI, Cursor or xAI). Their privacy policy and
  retention apply. Only ask about data you are comfortable sharing with them.
- **Google**, in self-hosted OAuth mode only, for sign-in.

## Logs

The server logs request methods, paths (which include Akahu account and
transaction ids) and status codes. It does not log tokens, balances or
transaction contents. Logs stay wherever your MCP client or host writes them.

## Not financial advice

Answers come from your AI assistant, which can be wrong. Check important
figures against your bank before acting on them.

## Contact

Questions about this policy: open a
[discussion](https://github.com/thatskiff33/nz-openbank-mcp/discussions).
Security problems: follow
[SECURITY.md](https://github.com/thatskiff33/nz-openbank-mcp/blob/main/SECURITY.md).
