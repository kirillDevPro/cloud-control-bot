# Contributing to Cloud Control Bot

Thanks for your interest in improving Cloud Control Bot! This guide covers how to set up a
development environment, the checks your change must pass, and the conventions the codebase
follows.

> **License note.** This project is source-available under the
> [PolyForm Noncommercial License 1.0.0](LICENSE) — **not** an OSI open-source license. By
> contributing, you agree that your contributions are licensed to the project under those same
> terms.

## Ways to contribute

- **Report a bug** — open an issue using the *Bug report* template.
- **Request a feature** — open an issue using the *Feature request* template.
- **Send a pull request** — fix a bug, add a provider, add a locale, or improve the docs.
- **Report a security issue** — please do **not** open a public issue; follow
  [SECURITY.md](SECURITY.md).

## Development setup

Requires **Python 3.12+** (CI runs on 3.12 and 3.13).

```bash
git clone https://github.com/kirillDevPro/cloud-control-bot.git
cd cloud-control-bot

python -m venv venv
# Linux/macOS:
source venv/bin/activate
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt -r requirements-dev.txt
```

You do **not** need real provider credentials or a Telegram token to develop and run the
checks below — they are static (lint, type-check, locale parity). You only need them to run
the bot end to end.

## Checks your change must pass

CI runs these on every push and pull request, across Linux and Windows on Python 3.12 and
3.13. Run them locally before opening a PR — the config lives in `pyproject.toml`:

```bash
ruff check src main.py scripts/check_i18n_locales.py     # lint
mypy src main.py scripts/check_i18n_locales.py           # type-check
python scripts/check_i18n_locales.py                     # EN/RU/UK/ES locale parity
```

The i18n parity check fails on any missing or empty key, plural-form-count drift, or
placeholder mismatch between locales.

## Conventions

- **English everywhere in code** — identifiers, docstrings (args/returns/raises), and comments.
- **Never hard-code a user-facing string.** All UI text goes through the i18n catalog in
  `src/bot/i18n/locales/`. English (`en.py`) is the source of truth; `ru`, `uk`, and `es` are
  translations of it. Adding a message means adding the key to **every** locale, or the parity
  check fails.
- **Commit messages** follow Conventional Commits: `type(scope): subject`, where `type` is one
  of `feat`, `fix`, `refactor`, `docs`, `test`, `chore` — e.g.
  `feat(balance): runtime-configurable alert threshold`.
- Keep changes focused; one logical change per pull request.

## Adding a new provider

1. Create a subclass of `BaseProvider, RetryMixin, HttpClientMixin` in `src/providers/`.
2. Implement `get_servers()`, `start_server()`, `stop_server()`, `reboot_server()`,
   `shutdown_server()`, and optionally `get_balance()`.
3. Add the type to the `ProviderType` enum (`src/models/provider.py`) and register it in
   `ProviderFactory` (`src/providers/factory.py`).
4. Add the env-var pattern to `src/config/provider_discovery.py`.

## Adding or updating a locale

Locales live in `src/bot/i18n/locales/<lang>.py`. Mirror the keys in `en.py` exactly — same
keys, same placeholders, same plural forms — then run `python scripts/check_i18n_locales.py`
to confirm parity.

## Opening a pull request

1. Fork the repo and create a branch off `main` (e.g. `feat/digitalocean-provider`).
2. Make your change and run the three checks above.
3. Open the PR against `main`; the template will prompt you for a summary and a checklist.
4. CI must be green before the PR can be merged.
