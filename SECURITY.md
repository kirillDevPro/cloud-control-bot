# Security Policy

## Supported versions

This project is distributed as source. Only the latest `main` branch is supported —
please run the current code before reporting an issue.

## Reporting a vulnerability

Please report security issues **privately**, not via public issues or pull requests.

- Use GitHub's [private vulnerability reporting](https://github.com/kirillDevPro/cloud-ping-monitor/security/advisories/new)
  (the **Report a vulnerability** button on the repository's *Security* tab), or
- open a minimal public issue asking for a private contact channel — without any
  sensitive details.

Please include what you can reproduce: affected version/commit, steps, and impact.
You can expect an initial response within a few days.

## Scope & operator responsibilities

This bot stores **cloud-provider API keys** (Hetzner / Vultr / AWS) and can
**power-manage live servers** (start / stop / reboot), so a leaked key or an auth
bypass has a real blast radius. When deploying:

- Keep `.env` out of version control (it is gitignored) and restrict its file
  permissions; never commit real credentials.
- Scope provider/IAM credentials to the **minimum** required (the AWS IAM user
  only needs EC2, Lightsail, and optionally Cost Explorer).
- Restrict bot access via `ADMIN_IDS` — only the listed Telegram user IDs are
  allowed in.
- Rotate any credential immediately if you suspect it was exposed.
