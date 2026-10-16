# ELNOC — MVP through pilot (secs 5–14 of the design)

**Live links:** public → `https://browse-famous-copying-administered.trycloudflare.com`
(team + WhatsApp ack links) · NOC LAN → `http://10.10.10.2:8000` (or `http://172.16.100.17:8000` over Wi-Fi).
The public URL is a Cloudflare quick tunnel: free and instant, but it **changes
whenever the tunnel restarts** — for a permanent address, set up a named tunnel
(`cloudflared tunnel login` + DNS) or move to the team VM. Keep
`ELNOC_BASE_URL` in `.env` pointing at the current public URL so ack/message
links resolve on recipients' phones.

**Survive reboots** (needs an elevated prompt once):
`tools\run_server.bat` (uvicorn, single worker) + `tools\cloudflared.exe tunnel
--url http://127.0.0.1:8000` as two Task Scheduler tasks, trigger *At log on*,
plus `python tools\run_collectors.py` every 5 minutes. `schtasks` from a normal
prompt is denied — open Task Scheduler as Administrator instead.

**Hosting roadmap:** Tier 0 (live) → Tier 1 (named URL + off-site backups) →
Tier 2 (Supabase Postgres). Full procedures in `HOSTING.md`.

One company-controlled server + dumb hotkey client. Phoenix stays the official
ticket; ELNOC is the team-facing working twin (`phoenix_ticket_no` links them).

## Run (second person, one command each)

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # fill secrets; never commit .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# login: admin / elnoc-admin  (change immediately in Admin)
```

Schedulers (alerting runs **separately** from the UI, NFR-03):

```powershell
# every 5 min (Task Scheduler / cron / systemd)
python tools\run_collectors.py
# nightly
python tools\backup.py
```

Import registry (FR-10): `python tools/import_csv.py --kind links --file data/seed/links.csv`

## What lives where

- `app/adapters/` PRTG, Zabbix, SmartOLT, mailbox, Phoenix-CSV collectors → normalized `RawEvent`
- `app/services/correlation.py` fingerprint (stable, gap #1), idempotent store, one-case correlation, recovery notes
- `app/services/escalation.py` steps/wait/ack/watchers, stale-wait + MTTR breach
- `app/notify/` template (sec 10.3, always WAT) + per-channel senders that fail independently + dispatcher log
- `app/routers/` quicklog, cases, dashboard, handover (exact 11-Oct format), admin, ingest webhooks, ack links, playbooks, ask
- `client/ELNOC_Pane.py` desktop Quick-Log pane (tkinter, stdlib-only — no Java needed):
  `Ctrl+Shift+L` → link search → auto card → severity + details → Submit. Returns
  the case id, system escalation time and Copy-for-Phoenix text.
- `client/ELNOC_QuickLog.ahk` AutoHotkey v2 hotkey (Ctrl+Shift+L, Alt+Shift+L fallback)
  that opens the pane with the window title as device hint; `.bat`/`.ps1` do the same with no install
- `tools/run_collectors.py` 5-min loop with lock file (gap #9) + heartbeat (NFR-07)
- `tests/` 12 areas from §14.1 — `pytest -q`

## Build order actually used

0 Foundations → 1 Quick Log/registry → 2 Case lifecycle → 4 Handover → 3 Alerting/escalation → 5 Playbooks → 6a Ask. Phase numbers kept so requirement IDs don’t move.

## Pilot checklist

1. Baseline 2 weeks from sheet + WhatsApp history (§3 table; targets MTTA <1h, MTTR 4h, uptime 97%).
2. Dry run to a test recipient; check open/right-case/no-dup/recovery/failed-visible.
3. Live 2 weeks, manual paging fallback stays on.
4. Weekly review (stale waits, wrong-team, failed deliveries, complete cards).
5. Extend / adjust / stop.

## AI layer (Phase 6a only in this MVP)

Ask panel + glossary + RSL interpreter (numbers from code) + history read-only queries.
Minimised prompts, cited answers, full audit, kill switch = stop calling `/api/ask`.
Watch (6c) stays off until the backtest (FR-84) is accepted; Act (6d) needs one-click approval + sign-off.

## Gaps from `noc_manager_notifier.py` — all fixed here (§9.6)

Stable fingerprint · recoveries emitted · Zabbix host + no `recent` · `BODY.PEEK` mailbox ·
per-channel log · one-case correlation · template WhatsApp · ack/escalation engine ·
WAL+timeout+lock · heartbeat + status page.
