# HOSTING — ELNOC on Cloudflare + Supabase, permanently, at zero cost

**What you get:** a permanent HTTPS address (`https://noc.cedarviewng.com`) that
survives reboots, plus Supabase Postgres + off-site backups. **Total cost: £0.**

| Piece | Where it runs | Cost |
|---|---|---|
| The app (FastAPI + SQLite/Postgres) | this NOC PC | £0 |
| Public URL | Cloudflare named tunnel → the PC | £0 (free plan) |
| Database | Supabase Postgres (eu-west-2) | £0 (free tier) |
| Off-site backups | Supabase Storage `elnoc-backups` | £0 |
| Domain | cedarviewng.com (already yours) | already paid for |

**Cost: £0.** Cloudflare free plan + Supabase free tier (already live: Postgres
migrated, sequences repaired, backups verified) + your own domain.

### Read this first: where your DNS actually lives
`cedarviewng.com` is **not** on Cloudflare nameservers. Its authoritative
servers are `ns19/ns20.qservers.net`, and the apex resolves to `102.221.237.203`.
That means `cloudflared tunnel route dns` reports "added CNAME" but writes into a
zone the internet never queries — which is why `noc.cedarviewng.com` returns
NXDOMAIN even though the tunnel is running.

You have exactly two ways to fix it, both free:

| Option | What you do | Trade-off |
|---|---|---|
| **A. Add one CNAME where DNS is managed today** (fastest) | In your current DNS panel (the `qservers` one / your registrar) add:<br>`noc` **CNAME** `125568ef-db85-4e44-a593-4f49a1c97c15.cfargotunnel.com` | Works in minutes. No nameserver change, nothing else on the domain moves. |
| **B. Move the domain to Cloudflare** (better long-term) | Add cedarviewng.com to Cloudflare, then at the registrar swap the nameservers to the two `*.ns.cloudflare.com` names Cloudflare assigns. The CNAME already created goes live automatically. | Adds Cloudflare WAF/CDN and Access for free, but every other DNS record must exist in Cloudflare first. Do it deliberately. |

Whichever you choose, the tunnel itself is already created and running — the
only missing piece is DNS telling the internet where to send `noc`.

Tunnel facts (yours, already created):
- name `elnoc`, ID `125568ef-db85-4e44-a593-4f49a1c97c15`
- credentials `C:\Users\<you>\.cloudflared\125568ef-….json`
- config `C:\Users\<you>\.cloudflared\config.yml`
- target for the CNAME: `125568ef-db85-4e44-a593-4f49a1c97c15.cfargotunnel.com`

---

## STEP 1 — The permanent URL

### 1a. Publish the DNS (you must do this first)
Add the CNAME from the table above at your real DNS host, then confirm:

```powershell
nslookup noc.cedarviewng.com 1.1.1.1     # must return the cfargotunnel target
```

### 1b. Run the tunnel
**As Administrator** (so it can install as a Windows service and start at boot):

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup_tunnel.ps1
```

The script checks login, creates the tunnel if missing, writes `config.yml`,
attempts the DNS record, and installs **cloudflared as a Windows service** so
the URL survives reboots.

**No admin rights?** The script falls back to a logon scheduled task instead
(starts when you sign in, which is enough for a NOC machine that is always
signed in). To get boot-persistence without admin, run Task Scheduler →
Create Task → **"Run whether user is logged on or not"** → trigger *At startup*
→ program `tools\cloudflared.exe`, arguments `tunnel run elnoc`, start in the
repo folder.

### 1c. Point ELNOC at the permanent URL
In `.env`:
```
ELNOC_BASE_URL=https://noc.cedarviewng.com
```
Restart the server. (This is what makes WhatsApp acknowledge links resolve on a
phone outside the LAN.)

### 1d. Verify
```
https://noc.cedarviewng.com/health   ->  {"ok":true,"app":"ELNOC"}
https://noc.cedarviewng.com/         ->  landing page
```

### Want it on the root domain instead?
`noc.cedarviewng.com` is recommended (leaves the apex free). For the apex, use
`-Hostname cedarviewng.com` and add the CNAME for `cedarviewng.com` instead.

### Doing it by hand
```powershell
tools\cloudflared.exe tunnel login
tools\cloudflared.exe tunnel create elnoc
tools\cloudflared.exe tunnel route dns elnoc noc.cedarviewng.com
notepad %USERPROFILE%\.cloudflared\config.yml     # paste the block below
tools\cloudflared.exe service install             # Administrator only
tools\cloudflared.exe tunnel run elnoc            # or just run it
```
```yaml
tunnel: <UUID from create>
credentials-file: C:\Users\<you>\.cloudflared\<UUID>.json
ingress:
  - hostname: noc.cedarviewng.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

---

## STEP 2 — Make ELNOC itself start automatically

cloudflared is a service; the app is a normal process. Make it one too, so a
reboot doesn't leave a dead URL.

**Task Scheduler → Create Task** (run once as Administrator):
- **General:** Name `ELNOC-Server`, "Run whether user is logged on or not".
- **Triggers:** At startup.
- **Actions:** Program `C:\Users\<you>\Documents\ELNOC\tools\run_server.bat`,
  Start in `C:\Users\<you>\Documents\ELNOC`.
- **Settings:** tick "Restart the task if it fails" (every 1 minute, 3 attempts).

Also add a 5-minute task for the collectors (the alerting must survive a reboot
too):
- Program: `py` · Arguments: `-V:3.14 tools\run_collectors.py`
- Trigger: Daily, repeat every 5 minutes, duration 1 day.
- Start in the repo folder.

---

## STEP 3 — Supabase (already live; here's the full picture)

Already done and verified:
- Project `wopgyzrrfjewdasnantk` (eu-west-2) with the database password set.
- All 22 ELNOC tables migrated from SQLite; every row count matched.
- Postgres sequences repaired so new inserts don't collide.
- Private bucket `elnoc-backups` created; a real backup uploaded and listed back.

The connection string (already in `.env` as `DATABASE_URL`):
```
postgresql+psycopg://postgres.wopgyzrrfjewdasnantk:<url-encoded-password>@aws-0-eu-west-2.pooler.supabase.com:6543/postgres
```
Two details that will bite you if you forget them:
- **Encode the password.** `#` → `%23`, `%` → `%25`. The current password
  starts with `%b2_`, so it must appear as `%25b2_…`.
- **Port 6543** is the transaction pooler. The app sets
  `prepare_threshold=None` because the pooler rejects client-side prepared
  statements — that is already handled in code; don't remove it.

### Cutover from SQLite to Supabase (when you're ready — same data in both)
1. Nightly off-site backup: `py -V:3.14 tools\backup_supabase.py`.
2. Set `DATABASE_URL` in `.env` (it is already there — just uncomment/confirm).
3. Restart the server; check the dashboard and one case page.
4. Keep the SQLite file for two weeks as the rollback.

### Nightly backups (Supabase Storage)
Task Scheduler, nightly at 02:00:
`py -V:3.14 tools\backup.py` then `py -V:3.14 tools\backup_supabase.py`.
Restore drill monthly: download the newest object from the bucket, open it
locally, run one query.

### 12-month retention
`py -V:3.14 tools\retention.py` clears handover text older than 12 months.
Cases and evidence are never touched.

---

## STEP 4 — Optional hardening (free, do it when you have 10 minutes)

**Cloudflare Zero Trust → Access → Applications.** Add an application for
`noc.cedarviewng.com/admin*` and `noc.cedarviewng.com/report/*`, policy = emails
of your engineers. Leave `/ack/*` public so external contacts can acknowledge
from WhatsApp without an account. Costs nothing on the free plan (up to 50
users).

**Access rule for `/api/*`** so only your office/VPN can reach the ingest
endpoints (PRTG/Zabbix webhooks).

**Rotate the Supabase service key** if it ever appears in a screenshot or log;
it is currently only in `.env`, which is git-ignored.

---

## The one thing to know about this setup

The URL is permanent; the **machine** behind it is your PC. If the PC is off,
sleeping, or on a dead network, `noc.cedarviewng.com` returns Cloudflare's
"tunnel not connected" page. Two ways to handle that:

- **Cheapest (free):** keep the PC on 24/7, disable sleep
  (`powercfg /change standby-timeout-ac 0` and for the monitor), and set
  Task Scheduler to restart the server if it fails. Good for a NOC machine
  that is always on anyway.
- **If the PC cannot be trusted to stay on:** a free-tier VM (Oracle Cloud
  Always Free, 1 GB RAM) can host ELNOC 24/7 with Docker instead. That is the
  only genuinely always-free 24/7 option I would trust; it needs a card on file
  for identity checks but costs nothing for the VM itself. Say the word and
  I'll write that runbook too.

---

## Quick reference

```powershell
# local health
py -V:3.14 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health').read())"

# public health (your permanent URL)
curl https://noc.cedarviewng.com/health

# tunnel service
sc query cloudflared

# tunnel logs
cloudflared tail

# collectors (every 5 min via Task Scheduler)
py -V:3.14 tools\run_collectors.py --dry-run

# backups
py -V:3.14 tools\backup_supabase.py
```

Everything else — the test suite, the deployment files (`Dockerfile`,
`docker-compose.yml`, `.github/workflows/ci.yml`) and the migration tooling —
is already in the repo and pushed.