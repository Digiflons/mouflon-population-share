# Security policy

Mouflon Population is a personal project that processes **private household audio**. Please treat any security or privacy problem seriously and privately.

## Reporting a problem

- Do **not** open a public issue for a vulnerability.
- Use GitHub's private vulnerability reporting on this repository ("Security" tab → "Report a vulnerability"), or contact the owner directly.
- Include what you found, how to reproduce it, and what could be exposed.

## Rules for this repository

- No secrets in Git, in issues, in work files or in logs. Camera passwords, MQTT logins and Home Assistant tokens are entered by the owner in Home Assistant or GitHub settings only.
- Household audio never leaves the house and is never stored by default.
- Dependencies and workflows are checked by Aikido, Dependabot and `pip-audit` in CI.
- Threat model and current findings: [`docs/security.md`](docs/security.md).

## Upstream

Vulnerabilities in the original BirdNET-Analyzer code should also be reported to its authors: https://github.com/birdnet-team/BirdNET-Analyzer
