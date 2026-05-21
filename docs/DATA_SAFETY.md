# Data Safety

InsPoly separates source code from local runtime data. The repository should contain the application, tests, and curated documentation, while live run artifacts and private configuration stay local.

## Tracked Source Files

The repository is intended to track:

- source code under `app/`;
- helper and audit scripts under `tools/`;
- tests under `tests/`;
- curated documentation under `docs/`;
- launcher scripts with relative paths;
- example runtime configuration without secrets.

## Local Runtime Data

The following paths are ignored by default:

- `.inspoly*/` SQLite databases and saved reports;
- `outputs/`, `archive_outputs/`, `event_forensic_outputs/`;
- `*_outputs/` generated diagnostic reports;
- profile or wallet reconstruction exports;
- `.inspoly_runtime.env`;
- `.env` files;
- zip archives;
- nested donor/reference repositories;
- local agent memory and operator notes.

These files can contain wallet addresses, local filesystem paths, analyst notes, raw payloads, cached evidence, API keys, or large generated data. Keep them out of normal source commits unless a small example is deliberately curated and reviewed.

## Secret Handling

Never commit:

- private keys;
- API keys;
- RPC URLs containing credentials;
- OpenAI API keys;
- wallet seed phrases;
- private user handles tied to a maintainer;
- local absolute paths that identify a machine or user.

Use `.inspoly_runtime.env` locally and keep it ignored.

## Safety Checklist

Before sharing work, run:

```bash
git status --short
git ls-files
git ls-files -z | xargs -0 rg -n "(ABSOLUTE_HOME_PATH|PRIVATE_ACCOUNT_NAME|PRIVATE_EMAIL_DOMAIN)"
git ls-files -z | xargs -0 rg -n "(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|-----BEGIN (RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----|PRIVATE_KEY\s*=\s*[^<\s#]|SECRET(_KEY)?\s*=\s*[^<\s#]|TOKEN\s*=\s*[^<\s#]|PASSWORD\s*=\s*[^<\s#]|OPENAI_API_KEY\s*=\s*[^<\s#])"
```

Replace the placeholders in the first scan with known maintainer-specific handles, emails, wallets, aliases, or machine paths. Review `git ls-files` manually. If a generated output directory appears, stop and fix `.gitignore`.

## Evidence Disclaimer

Wallet addresses and market events are public blockchain/Polymarket data, but raw investigative outputs can still create privacy, reputational, and context risks. Public examples should be small, curated, and documented.
