# ELNOC Review: CI/CD, Security and Standardisation

Nov 1, 2026 · @NOCdesk

## Verdict and scope

ELNOC's design is sound, but its internet exposure, default credentials and thin pipeline need fixing before the pilot grows. The first four security items below should be done before more users are added.

This is a static review of the `elnoc-master` zip, not a penetration test. I installed the dependencies and ran the suite: all 125 tests pass in about 5 seconds, on Python 3.13 here while CI uses 3.14. The zip has no `.git` folder, so commit history was not checked for leaked secrets.

## Fix first: security

Seven findings, ordered by risk. Items 1 to 4 are the urgent ones.

1. **Hardcoded default credentials.**
   - `seed.py` re-creates `admin / elnoc-admin` at every startup if the account is missing.
   - `superadmin.py` and `auth.py` fall back to `superadmin / ELNOC-super-2026` when `ELNOC_SUPERADMIN_PASSWORD` is unset.
   - The README also publishes the admin login.
   - The superadmin can call `/api/admin/clear-data`, which deletes all operational data with one POST.
   - **Fix:** no default passwords. Generate a random one on first run and print it once, or refuse to start. Force a password change on first login.
2. **Open self-signup on a public URL.**
   - `POST /signup` lets anyone who can reach the host create an account.
   - Any account can read cases, customers and links, and export all cases as CSV.
   - **Fix:** invite-only, admin approval, or restrict to your email domain. Put Cloudflare Access in front of the whole app. HOSTING.md lists this as "optional hardening"; it should be mandatory.
3. **Secrets and infrastructure details in committed docs.**
   - `HOSTING.md` contains the Supabase project ref, the Cloudflare tunnel ID, and a hint about the database password (it says the password starts with `%b2_`).
   - The README contains a live trycloudflare URL and internal LAN IPs (`10.10.10.2`, `172.16.100.17`).
   - `sign_elnoc.ps1` says the PFX password sits in a plaintext README next to the key.
   - `data/seed/contacts.csv` and `channels.csv` contain what look like phone numbers and emails. I did not print them, so I cannot say whether they are real.
   - **Fix:** rotate the Supabase database password now and scrub these from the docs. Keep the signing password in a password manager or CI secret. If the seed contacts are real, replace them with synthetic data.
4. **Webhook ingestion does not match its documentation.**
   - `/ingest/{source}` requires a browser session cookie, so PRTG and Zabbix cannot call it.
   - It defaults to `dry_run=True`, and any logged-in user can inject arbitrary events through the request body.
   - **Fix:** a per-source shared secret or HMAC header, restricted to a service role, with rate limiting.
5. **`/ack/{token}` changes state on a GET.**
   - WhatsApp, email scanners and link previews fetch URLs automatically, so an alert could be acknowledged by a robot, which stops escalation.
   - The 404 text says "expired", but there is no expiry.
   - **Fix:** GET shows a confirm button, POST does the acknowledgement. Add a token expiry.
6. **AI assistant output is injected as HTML.**
   - `assistant.html` and `power.html` write the model's answer with `innerHTML`. That answer can echo text that began in alert payloads or mailbox subjects, which is untrusted input.
   - The agent's `create_case` is described as needing explicit confirmation, but only the prompt asks the model to behave. Nothing server-side enforces it, so a prompt-injected case note could trigger it.
   - **Fix:** use `textContent` or sanitise the output. Return a pending action for the user to approve in the UI.
7. **Smaller issues.**
   - The session cookie has no `Secure` flag.
   - There is no login rate limit or lockout.
   - Sessions are stateless with no revocation.
   - An insecure `SECRET_KEY` only prints a warning instead of blocking startup.
   - `/admin/users` defaults a blank password to `changeme` and accepts any role string.
   - Evidence uploads have no file-type allowlist, and deleting evidence removes only the database row, not the file.
   - `clear-data` has no confirmation or pre-backup, and it hides errors as `0` counts.

## CI/CD and pipelines

The single workflow runs the tests and then builds the Docker image; the image is never pushed, scanned or deployed. Production schema changes are the biggest risk.

- **Triggers.** It runs on every push to every branch and on pull requests, so PR branches run twice. Restrict `push` to `main` and add `concurrency` with cancel-in-progress.
- **Hardening.** Add `permissions: contents: read`. Pin actions to commit SHAs, not tags.
- **Quality gates.** There are none, and there is no `pyproject.toml`. Add ruff for lint and format, a type check, coverage with a minimum threshold, and pre-commit hooks.
- **Security scanning.** None today. Add CodeQL or Semgrep, `pip-audit`, gitleaks, Trivy on the built image, and Dependabot or Renovate.
- **Postgres is untested.** Production runs on Supabase Postgres, but every test uses SQLite, and FTS5 and `ensure_columns` are SQLite-only. Add a `postgres:16` service container and run the suite against both databases.
- **Schema migrations do not reach production.** `create_all` never alters existing tables, `ensure_columns` skips non-SQLite databases, and there is no Alembic. A new column will silently not appear in production. Add Alembic and a CI check that migrations apply cleanly.
- **No release pipeline for the desktop client.** The PyInstaller build, Inno Setup installer and signing are manual PowerShell scripts, and the certificate is self-signed. Add a `windows-latest` job on version tags that builds, signs with secrets, and publishes a Release with checksums.
- **No CD.** Add a build-once, push-to-registry step (GHCR), a staging deploy with a `/health` smoke test, then promotion to production with a documented rollback.
- **Test gaps.** I found no tests dedicated to signup abuse, role denial, `/ack` or `/ingest` authentication. Only four test files use an HTTP client.

## Containers and dependencies

The container setup is sound in structure, but it runs as root and nothing is pinned.

- **Dockerfile.** It runs as root, so add a non-root `USER`. Pin the base image by digest, use a multi-stage build, and drop `pytest` from runtime requirements.
- **Compose.** Pin `cloudflared:latest`. No ports are published, so the app is reachable only through the tunnel, and the healthchecks are good.
- **Dependencies.** Everything in `requirements.txt` is `>=` with no lockfile, so builds are not reproducible. Use `uv` or `pip-tools` with hashes.

## Standardisation

The code repeats itself in several places, and configuration and conventions are not enforced anywhere.

- **Duplication.**
  - Password hashing exists in both `security.py` and `superadmin.py`.
  - There are two evidence upload endpoints (`cases.py` and `evidence.py`) with the same logic.
  - `_res()` is duplicated in `config.py` and `database.py`, and `SECRET_PATTERNS` has near-duplicate entries.
  - Config is read at import time, mixing `_int()` with raw `int()`; the raw `int()` crashes on a bad value.
- **Single source of truth.** Move settings to `pydantic-settings` with validation, so a missing or insecure secret fails at startup. Define the incident schema, severity matrix and status vocabulary once, as enums.
- **Housekeeping.**
  - FastAPI `on_event` is deprecated (the tests already warn). Use lifespan.
  - Replace `print` with structured logging.
  - The version is hardcoded as `0.1.0`.
  - The README contradicts HOSTING.md (quick tunnel versus named tunnel, outdated login line).
  - Add `SECURITY.md`, `CODEOWNERS`, a PR template, ADRs and a LICENSE decision.
- **Data governance.** The assistant sends case and link context to external LLM providers. The regex secret scrubber is a good start, but document what data leaves the system and check it against Nigeria's data protection requirements for customer data.

## What is already good

The security fundamentals are mostly sound for an internal tool.

- PBKDF2 at 200,000 iterations with constant-time comparison.
- HttpOnly and SameSite cookies, and an open-redirect guard on `next`.
- ORM-parameterised queries and Jinja autoescape.
- 192-bit ack tokens and an audit log.
- Granular role checks on customers, links and playbooks.
- A secret-scrub gate on AI inputs, plus collector rate caps and an assistant daily cap.
- `.env` is gitignored and no secrets are baked into the image.

## Suggested order of work

Start with exposure and credentials, then make production safe to change, then raise the baseline.

1. Remove default credentials, close or gate signup, and put Cloudflare Access in front of the app.
2. Rotate the Supabase password and scrub the docs.
3. Add webhook authentication and turn `/ack` into a confirm-then-POST flow.
4. Add Alembic and run Postgres in CI.
5. Add lint, security scans and Dependabot, then the Docker non-root and pinning changes.
6. Add the desktop release pipeline and the standardisation clean-up.
