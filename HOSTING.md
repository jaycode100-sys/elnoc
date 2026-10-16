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

### 1b. Off-site backups to Supabase Storage (≈15 min, free tier)

1. supabase.com → New project → note **Project URL** + **service_role** key
   (Project Settings → API; the service key stays server-side, never in git).
2. Storage → New bucket `elnoc-backups` (**private**).
3. `.env`: `SUPABASE_URL=…`, `SUPABASE_SERVICE_KEY=…`
   (`SUPABASE_BACKUP_BUCKET=elnoc-backups`).
4. `py -V:3.14 tools/backup_supabase.py` → prints `local:` then `off-site:`.
   Nightly via Task Scheduler after `tools\backup.py`.
5. Restore drill monthly: download an object, open it locally, run one query.

## Tier 2 — full Supabase Postgres move (a migration weekend, not today)

Run this only when SQLite strains (concurrent writers, DB > ~1 GB, or you want
Supabase Auth/Realtime). The code is ready: setting `DATABASE_URL` switches
the engine to pooled Postgres, SQLite pragmas/FTS5 stay out of the way, and
similar-case search falls back to keyword ILIKE (verified in tests).

1. Supabase → Database → Connection string (**pooler**, port 6543 for the app;
   direct port 5432 for the one-off load): `DATABASE_URL=postgresql+psycopg://…`
2. `pip install -r requirements.txt` (pulls `psycopg[binary]`).
3. Start the app once against the empty database — tables self-create.
4. Load data: export SQLite (`sqlite3 data/elnoc.db .dump`) and import, or
   re-run the four `tools/import_csv.py --kind …` files, then spot-check
   counts (cases/links/contacts) against the old DB.
5. Keep the SQLite file + Supabase backups for two weeks, then cut over
   `ELNOC_BASE_URL` and decommission.
6. Later, optionally: Supabase Auth (replace session cookies), Storage for
   `evidence/` (replace local paths), Realtime on a dashboard channel. Each is
   a separate change — say which one and it gets its own plan + tests.

## What lives where (so nothing surprises you)

| Piece | Tier 0 | Tier 1 | Tier 2 |
|---|---|---|---|
| App + DB | this PC, SQLite | same, named URL | same code, Supabase Postgres |
| Front door | quick tunnel (changes) | named tunnel + domain + WAF | same + Access policies |
| 2nd backup copy | `backups/` folder | Supabase Storage bucket | same |
| Evidence files | `evidence/` folder | same | same (Storage later) |
