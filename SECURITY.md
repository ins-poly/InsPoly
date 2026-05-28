# Security Policy

InsPoly is a local-first analyst toolkit. It is not a hosted service and it is not a compliance, trading, or accusation system.

## Data Handling

- Do not commit API keys, RPC URLs with credentials, private notes, SQLite databases, generated reports, or raw review packets.
- Local browser UIs bind to `127.0.0.1` and protect `/api/*` routes with a per-session token.
- Optional LLM review sends selected case-packet context to the configured external provider. Keep it disabled unless that data transfer is acceptable for your environment.
- Funding traces are disabled by default. Enable live Polygon RPC only with explicit local configuration.

## Reporting Issues

Please open a GitHub issue for security concerns that do not expose private data. If a report includes sensitive keys, wallet notes, local paths, or unpublished evidence, redact it before sharing.

Include:

- affected command or UI mode;
- operating system and Python version;
- whether live RPC or LLM review was enabled;
- minimal steps to reproduce without private data.
