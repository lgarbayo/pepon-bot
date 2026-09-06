# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| `main` (latest) | Yes |
| anything else | No |

## Reporting a vulnerability

Please report security vulnerabilities **privately**, never as a public GitHub issue.

- Preferred: use GitHub's [Private Vulnerability Reporting](https://github.com/lgarbayo/pepon-bot/security/advisories/new) (Security tab → "Report a vulnerability").
- Alternative: email **lugarbayo@gmail.com** directly.

Please include what you found, how to reproduce it, and its potential impact.

## Response timelines

I (Luis Garbayo) am currently the sole maintainer, working on this in my spare time — not a funded security team. My realistic targets are:

- Acknowledgement of your report within **48–72 hours**.
- Assessment and, if confirmed, a fix on a best-effort basis, prioritized above regular feature work.

## Known limitations

This project was built as a fast personal project, not a hardened product. Some honest, known gaps:

- **No authentication or authorization**: anyone who can reach the server's URL (e.g. anyone on the same Wi-Fi network) can view the camera feed and control the robot. Do not expose this server beyond a trusted local network.
- **Self-signed TLS certificate**: generated locally per machine, accepted manually by the browser — not chain-of-trust verified.
- No external security audit has been performed.
- Dependencies (see `docs/COMPONENTS_LICENSE.md`) are not independently vetted beyond what `pip`/Dependabot report.

## Disclosure policy

Please give us a reasonable amount of time to investigate and release a fix before disclosing details publicly (coordinated disclosure). We'll credit reporters who wish to be credited once a fix ships.
