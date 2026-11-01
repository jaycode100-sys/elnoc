# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.0   | :white_check_mark: |

## Reporting a Vulnerability

Please report security vulnerabilities to the ELNOC admin on your team or open a private advisory in the GitHub repository.

Do **not** disclose vulnerabilities in public issues until they have been reviewed and patched.

## Security Basics

- PBKDF2 at 200,000 iterations with constant-time comparison
- HttpOnly and SameSite cookies
- Open-redirect guard on `next` parameter
- ORM-parameterised queries (SQL injection protection)
- Jinja autoescape (XSS protection)
- 192-bit acknowledgement tokens with expiry
- Granular role-based access control
- Secret-scrub gate on AI assistant inputs
- Webhook authentication via per-source shared secret
- No secrets baked into the image (`.env` is gitignored)

## Credentials

No default passwords exist. The superadmin password is generated randomly on first run and printed once to stdout. Set `ELNOC_SECRET_KEY` (32+ random chars) in `.env` before starting the server.
