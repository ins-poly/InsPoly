# Contributing

InsPoly changes should be small, reviewable, and conservative. The project produces analyst leads from unstable public data sources, so preserving existing behavior matters.

## Pull Requests

- Keep PRs focused. Prefer separate PRs for CI, packaging, browser security, docs, schemas, scoring refactors, and validation corpus changes.
- Do not change scoring weights, gates, visibility, funding semantics, report schemas, storage schemas, or pagination completeness unless the PR explicitly targets that behavior and includes focused regression tests.
- Do not commit generated outputs, local databases, review packets, secrets, private notes, or raw validation dumps.
- Run the offline validation before opening a PR:

```bash
python3 -m compileall app tools tests
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tools/public_repo_checks.py --all
```

## Documentation

Keep public documentation concise and user-facing. Large dated research packets, agent-control files, validation dumps, and raw review artifacts should stay out of `main` unless they are deliberately curated.

## LLM And RPC Features

LLM review is advisory only and must not become production scoring. Live RPC and API drift checks should be bounded, documented, and kept out of PR CI unless they are explicitly designed as optional/manual jobs.
