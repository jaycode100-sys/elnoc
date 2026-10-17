# HOSTING ELNOC — Cloudflare + Supabase procedures

Three tiers. Each one keeps working when the next isn't ready; never skip Tier 0.

## Tier 0 — this PC + Cloudflare quick tunnel (LIVE NOW)

What you have: `tools\run_server.bat` (uvicorn, single worker — SQLite
demands one writer) on this PC, `tools\cloudflared.exe` relaying it to a
public `https://…trycloudflare.com` URL, `ELNOC_BASE_URL` pointing at it so
WhatsApp ack links resolve on recipients' phones.

- LAN link (wallboard/NOC PCs): `http://10.10.10.2:8000`
- Restart after any `.py` change (templates reload themselves; code doesn't).
- Quick-tunnel URLs are random and **change on restart** — fine for the pilot,
  not for printed handover sheets. Tier 1 fixes that.

## Tier 1 — permanent address (Cloudflare named tunnel) + off-site backups (Supabase)

### 1a. Named tunnel + your domain (≈30 min, free)

1. Point your domain's nameservers at Cloudflare (dash → Add site).
2. On this PC: `cloudflared.exe tunnel login` (browser certifies once).
3. `cloudflared.exe tunnel create elnoc` → note the UUID.
4. Route DNS: `cloudflared.exe tunnel route dns elnoc noc.yourdomain.com`.
5. `C:\Users\Dell\.cloudflared\config.yml`:
   ```yaml
   tunnel: <UUID>
   credentials-file: C:\Users\Dell\.cloudflared\<UUID>.json
   ingress:
     - hostname: noc.yourdomain.com
       service: http://127.0.0.1:8000
     - service: http_status:404
   ```
6. Install as a service: `cloudflared.exe service install` (+ Task Scheduler
   backup running `tools\run_server.bat` at logon, and collectors every 5 min).
7. Set `ELNOC_BASE_URL=https://noc.yourdomain.com`, restart the server.
8. Optional hardening (Zero Trust → Access): put an Access application in front
   of `/admin*` and `/report/*` so only team emails reach them; leave `/ack/*`
   public — external contacts acknowledge from WhatsApp without accounts.

### 1b. Off-site backups to Supabase Storage — DONE, verified

Bucket `elnoc-backups` created private; a real nightly copy uploaded and listed
back from the API. Keys live in `.env` only (`SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, `SUPABASE_BACKUP_BUCKET`) — never in git.

1. ✅ Create project → 2. ✅ private bucket → 3. ✅ keys in `.env`
4. Run: `py -V:3.14 tools\backup_supabase.py` → prints `local:` then `off-site:`
   (first run confirmed `elnoc-backups/elnoc-20261016-1837.db`, 160 KB).
5. Schedule it nightly (Task Scheduler) after `tools\backup.py`.
6. Restore drill monthly: download an object, open it, run one query.

Full procedure for re-creating from zero:
1. supabase.com → New project (region: **eu-west-2** for this account).
2. Storage → New bucket `elnoc-backups` (**private**).
3. Project Settings → API → copy Project URL + `service_role` key.
4. Add all three values to `.env`.

## Tier 2 — full Supabase Postgres move — DONE, verified

Status: **live-ready and verified** for this project. The code is ready:
setting `DATABASE_URL` switches the engine to pooled Postgres, SQLite
pragmas/FTS5 stay out of the way, and similar-case search falls back to
keyword ILIKE (pytest-covered).

Verified connection string (region eu-west-2 = London; set in `.env`):

    DATABASE_URL=postgresql+psycopg://postgres.<project-ref>:<url-encoded-password>@aws-0-eu-west-2.pooler.supabase.com:6543/postgres

Password encoding matters: `#` becomes `%23`, `%` becomes `%25` (your DB
password starts with `%b2_…`, so both are encoded).

What was proven against the live project:
1. `tools/migrate_sqlite_to_pg.py --dry-run` → reads every table, writes nothing.
2. Real run → **all 22 tables matched** (13 cases, 5 links, 6 contacts, 26 case events…).
3. `tools/fix_pg_sequences.py` → **20 sequences synced**. Required: Postgres
   sequences stay at 1 after an explicit-ID copy, so the first real INSERT dies
   on a duplicate key. The migration now calls this automatically; the tool is
   the idempotent standalone repair.
4. App boots on Postgres; login, `/cases`, case page, dashboard, handover,
   quicklog, weekly, deck-stats all render; a real quick-log **write** succeeded
   and the probe row was removed afterwards.
5. Two Postgres-specific fixes came out of this: `prepare_threshold=None` in the
   engine (Supavisor's transaction pooler rejects client-side prepared
   statements with `DuplicatePreparedStatement`) and the sequence sync above.

Cutover when you're ready: the SQLite file is still the live default until you
set `DATABASE_URL` in `.env` and restart the server. Both hold identical data;
take the off-site backup first, flip, smoke-test the deck, keep SQLite for two
weeks before decommissioning.

## What lives where (so nothing surprises you)

| Piece | Tier 0 | Tier 1 | Tier 2 |
|---|---|---|---|
| App + DB | this PC, SQLite | same, named URL | same code, Supabase Postgres |
| Front door | quick tunnel (changes) | named tunnel + domain + WAF | same + Access policies |
| 2nd backup copy | `backups/` folder | Supabase Storage bucket | same |
| Evidence files | `evidence/` folder | same | same (Storage later) |
