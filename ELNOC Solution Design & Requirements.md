# ELNOC Solution Design & Requirements

Oct 11, 2026 · @NOCdesk

## 1. Executive summary

ELNOC should be one on-premises platform that lets any engineer log an incident in under 30 seconds, see how similar faults were fixed before, and alerts the right person automatically. It merges four things you already have: the ELNOC build spec (case memory, quick log, handover), `noc_manager_notifier.py` (event collection and email / WhatsApp / SMS delivery), the monitoring runbook (PRTG / Zabbix onboarding) and the two Perplexity proposals (incident workflow and SmartOLT alerting).

The design in one line: monitoring events from PRTG, Zabbix, SmartOLT, Cloud Phoenix and the downtime mailbox are normalized into one event stream, matched to a customer and link, and opened or updated as a **case**. An escalation engine then notifies the primary contact (plus any voluntarily added watcher) by email and WhatsApp, with SMS as a fallback. Engineers enrich the case with a hotkey Quick Log, and closed cases feed similar-case search and playbooks.

**What is already settled** by your own documents: FastAPI + SQLite/FTS5 server, AutoHotkey hotkey client that sends the active window title only, per-engineer accounts, no stored credentials, deterministic “learning” (no ML claims), and a four-phase build order.

**What this document adds:** a single architecture that places the existing notifier inside ELNOC, numbered requirements, an event-to-case and escalation design, a SmartOLT integration path, a gap list for the current notifier script, and the decisions you need from your team head before coding starts (section 16).

**AI agent layer.** Section 17 adds an optional Phase 6: agents that explain fibre terms, read signal levels and OTDR traces, draft cases and reports, and watch signal trends, with people approving every action.

## 2. Inputs reconciled

The five documents overlap more than they conflict; the table shows what each one contributes and where it fits.

| Input | What it gives us | Role in the solution | Gap or caution |
| --- | --- | --- | --- |
| ELNOC build spec v0.1 | Quick Log hotkey, customer/link registry, case lifecycle, similar cases, handover, playbooks, 4 phases | The core platform and UI | No alerting or monitoring feed yet (listed as “later”) |
| `noc_manager_notifier.py` | Collectors for Phoenix, PRTG, Zabbix and the mailbox; deduplicated SQLite store; instant vs digest; email / WhatsApp / SMS | Becomes the Ingestion and Notification modules inside ELNOC | Single recipient, no escalation, no acknowledgement (see section 9.6) |
| Monitoring runbook | PRTG / Zabbix onboarding, device tiers (core, distribution, access), phone push via PRTG app, Telegram, PagerDuty / Opsgenie | Defines the event sources, severity tiers and the existing paging path | Tier thresholds must map to ELNOC severity |
| Perplexity: incident workflow | Detect and correlate, ticket as source of truth, evidence attached to the record, rule-based escalation, pilot KPIs | Design principles and success measures | Generic; its “SMART” and “coordinates” points are unresolved; cited sources not checked by me |
| Perplexity: SmartOLT | Email + WhatsApp to a primary contact, optional added contact; public info shows a REST API and Telegram PON alerts | Adds SmartOLT as an event source and the primary / optional-recipient model | SmartOLT WhatsApp and event coverage are unverified; confirm with your admin |

**Three conflicts resolved in this design**

1. **Which record is official?** The spec treats ELNOC as shift memory and offers “Copy for Phoenix”; the Perplexity workflow says the ticket is the source of truth. Decision: Cloud Phoenix stays the official ticket until an approved sync exists; the ELNOC case stores `phoenix_ticket_no` and is the operational record.
2. **One manager vs many recipients.** The notifier sends to one manager; the SmartOLT note wants a primary contact plus an optional added one; the spec has escalation steps with wait times. Decision: one recipient model, `escalation_rule` steps plus per-case watchers.
3. **Evidence and location.** The incident-workflow note mentions attaching trace images and outage-location details, taken from a screenshot I cannot see. Decision: treat both as requirements (FR-31, FR-32) and confirm the meaning of “coordinates” in section 16.

## 3. Goals, scope and success measures

The goal is a NOC that loses no time to re-discovering what the last shift already knew. Five goals follow, each tied to a measure you can compare against the previous two weeks.

**Goals**

- G1: logging an event takes under 30 seconds.
- G2: the first escalation goes to the right team and person.
- G3: nothing waits on another team without being flagged.
- G4: any engineer, at any hour, can see what was done on this link or customer before.
- G5: the responsible contact is told about a critical event without anyone typing a message.

**In scope:** event ingestion (PRTG, Zabbix, SmartOLT, Phoenix, mailbox), case management, Quick Log client, escalation and notification, handover, playbooks, evidence attachments, audit trail.

**Out of scope:** replacing Cloud Phoenix, PRTG, Zabbix or SmartOLT; storing device credentials; remote device access; automatic remediation; customer-facing notifications; trained machine-learning models. AI agents are covered separately in section 17.

**Success measures** (baseline from the two weeks before the pilot, taken from the Google Sheet and WhatsApp history)

| Measure | Goal | How it is measured | Target |
| --- | --- | --- | --- |
| Time to log an event | G1 | Hotkey press to saved case, from server timestamps | Under 30 s |
| Time from alert to case created | G5 | Event `occurred_at` to `case.opened_at` | Set with team head |
| Time to acknowledge | G5 | Notification sent to acknowledgement | Under 1 hour (MTTA) |
| Time to resolve | G2, G4 | `time_to_resolve_min` per case | 4 hours (MTTR) |
| Repeat incidents on same link | G4 | Cases per link per month | Below baseline |
| Escalations to the wrong team | G2 | Cases with a re-escalation after the first step | Below baseline |
| Age of waiting-on-other-team cases | G3 | Dashboard stale-wait age | Below baseline |
| Cases with a complete card | G1 | Required fields filled at close | Set with team head |
| Handover time | G4 | Handover builder start to acknowledgement | Below baseline |
| Link uptime (assumed: monitored customer links, per month) | G2, G3 | Time in state UP divided by total time, from link state history | 97% |

## 4. Users, roles and key scenarios

ELNOC serves an eight-engineer team (a day shift of two to three, one night engineer), the line manager, and the external contacts the team escalates to.

| Role | Who | Main needs | Can do |
| --- | --- | --- | --- |
| NOC engineer | Day and night shift | Log fast, see history, escalate, hand over | Create and update cases, acknowledge handovers, add notes |
| Senior engineer | Designated seniors | Keep knowledge accurate | Everything above, plus confirm and promote playbooks, edit root-cause list |
| Line manager | Receives alerts | Know about critical events without chasing | Read dashboards, receive notifications, add a watcher |
| Admin | One or two named people | Keep the registry correct | Manage customers, links, contacts, escalation rules, users |
| External contact | Oregun team, Mr Adekunle, Yomi, Levene Lcon and others | Not users; they are directory entries | Listed in escalation steps with phone and availability hours |

**Key scenarios the design must handle**

1. **Alert-driven case.** A PRTG sensor goes down on a customer link. ELNOC opens a case stub, attaches the link, endpoints and responsible team, notifies the primary contact, and shows the case on the dashboard. The engineer adds the symptom with the hotkey.
2. **Manual quick log.** An engineer in PuTTY presses the hotkey; the device field is pre-filled from the window title. They type “ltv8 ikeja”, press Enter on the top match, and see the last three cases on that link.
3. **The 14-hour LTV8 Ikeja-RC case.** The far end was not transmitting, the evidence was in the RSL transceiver detail, and the case sat waiting on the Oregun team until Mr Adekunle intervened. With ELNOC, similar cases would have pointed to the RSL check first, and the stale-wait rule would have flagged the case red once the Oregun step’s wait time passed, prompting local re-verification or escalation upward.
4. **SmartOLT PON outage.** The event opens a case, the designated primary contact gets email and WhatsApp, and an authorized engineer can add one more recipient for that case’s updates.
5. **Shift handover.** The outgoing engineer generates the handover from open and waiting cases plus free notes; the incoming engineer acknowledges it on screen, and a plain-text copy goes to WhatsApp.

## 5. Solution architecture

ELNOC is one company-controlled server (on-premises or an approved cloud tenancy) plus a small hotkey client on engineer PCs. Everything the alerts and the team touch goes through a single case store.

&#91;embedded content: architecture · 5 sources, 1 server, 3 outputs\]

Events enter on the left of the server and flow through the case store to the escalation engine; engineers reach the same store through the Web UI, and recipients are reached only by the escalation engine.

**Module map.** The existing notifier code is reused rather than rewritten:

| Module | Comes from | Job |
| --- | --- | --- |
| `adapters/` (prtg, zabbix, smartolt, phoenix, mailbox) | Notifier collectors | Fetch from each source and return normalized events |
| `events/` | Notifier `Event`, `key()`, `store()` | Fingerprint, deduplicate, correlate events into cases |
| `cases/` | ELNOC spec | Lifecycle, similar cases, stale-wait rule, close-out rules |
| `escalation/` | New | Escalation steps, wait timers, acknowledgements, watchers |
| `notify/` | Notifier channels and `notify()` | Templates, email / WhatsApp / SMS senders, per-channel delivery log |
| `web/` | ELNOC spec | Quick Log, case page, dashboard, handover, admin (Jinja2 and HTMX) |
| `client/` | ELNOC spec | AutoHotkey v2 hotkey script |

**Runtime.** Python 3.11 or later, FastAPI, SQLAlchemy, SQLite with FTS5, rapidfuzz for matching. Two processes: the web app, and a scheduler (cron, Task Scheduler or systemd) that runs collectors and escalation checks every five minutes. Keeping them separate means alerting continues if the UI is down.

## 6. Functional requirements

There are 49 requirements in six groups. Priority: **M** = must have for the pilot, **S** = should have, **C** = could, or later. Phase numbers refer to section 13. The AI requirements (FR-70 to FR-90) are listed separately in section 17.5.

### 6.1 Event ingestion

| ID | Requirement | Pri | Phase |
| --- | --- | --- | --- |
| FR-01 | Collect down sensors from PRTG (status Down) and recoveries (status Up) | M | 3 |
| FR-02 | Collect active problems from Zabbix and map Zabbix severity to ELNOC severity | M | 3 |
| FR-03 | Collect SmartOLT events (PON outage, ONU offline) through its REST API, if the API exposes them, for the customers it monitors | S | 3 |
| FR-04 | Bring Cloud Phoenix customers and tickets in by CSV or scheduled export first; API or webhook sync is a later option | S | 3 |
| FR-05 | Read downtime notification emails from the NOC mailbox by subject keyword | M | 3 |
| FR-06 | Normalize every source into one event record with a stable fingerprint; the same event is never stored or sent twice | M | 3 |
| FR-07 | Correlate events on the same link or device within a time window into one case, not one case per event | M | 3 |
| FR-08 | A recovery event adds a note to the open case and suggests closing it; it never closes it silently | S | 3 |
| FR-09 | Suppress alerts for devices in a registered maintenance window | S | 3 |

### 6.2 Registry and Quick Log

| ID | Requirement | Pri | Phase |
| --- | --- | --- | --- |
| FR-10 | Import customers, links and contacts from CSV (`import_csv.py`) | M | 1 |
| FR-11 | Global hotkey (default Ctrl+Alt+L) opens a small pane with one search box | M | 1 |
| FR-12 | Fuzzy search across customer, link and alias; ranked matches; Enter selects | M | 1 |
| FR-13 | On select, auto-fill customer, link, endpoints, responsible team, escalation steps and the last three cases on the link | M | 1 |
| FR-14 | Pre-fill the device field from the active window title only; the engineer can edit it | M | 1 |
| FR-15 | If nothing matches, quick-create a customer and link from three fields (name, link name, circuit ID) | M | 1 |
| FR-16 | Every selection increments alias learning so frequent shorthand ranks first next time | S | 1 |
| FR-17 | “Copy for Phoenix” produces a formatted plain-text summary for one-step pasting | M | 1 |
| FR-18 | Each customer and link records which sources detect it (PRTG, Zabbix, SmartOLT, a Phoenix flag, or a combination); events from any of them correlate to the same case | M | 1 |

### 6.3 Case lifecycle

| ID | Requirement | Pri | Phase |
| --- | --- | --- | --- |
| FR-20 | Case page with a timeline of notes, status changes and escalations | M | 2 |
| FR-21 | Statuses: open, escalated, waiting\_other\_team, resolved | M | 2 |
| FR-22 | Closing requires a root-cause category, a fix and the first thing to check next time | M | 2 |
| FR-23 | Similar cases: same link first, then same customer, then full-text matches on the symptom | M | 2 |
| FR-24 | Stale-wait flag: a waiting\_other\_team case older than its rule’s wait time turns red on the dashboard and in handover | M | 2 |
| FR-25 | Dashboard: open cases, waiting-on-others with age, cases opened this shift | M | 2 |

### 6.4 Notification and escalation

| ID | Requirement | Pri | Phase |
| --- | --- | --- | --- |
| FR-26 | Each link or customer has a designated primary contact; notifications go by email and WhatsApp, with SMS as an optional fallback | M | 3 |
| FR-27 | An authorized engineer can add one optional watcher to a case, or set a standing watcher on a link; either is optional, and ELNOC records who added them and when | S | 3 |
| FR-28 | Escalation steps with wait times; if a step is not acknowledged in time, the next step is notified | M | 3 |
| FR-29 | Recipients can acknowledge from a link in the message; acknowledgement stops further escalation | M | 3 |
| FR-30 | Critical events are sent immediately; all others go in a digest | M | 3 |
| FR-31 | Attach evidence (trace output, screenshots) to the case, not only to a message | S | 2 |
| FR-32 | Record the outage location from the site or device inventory, plus an optional free-text note; never infer it from an IP address | C | 2 |
| FR-33 | Notification text follows a fixed template (section 10.3) and carries no passwords or customer details beyond policy | M | 3 |
| FR-34 | Keep a delivery log per channel; failed deliveries show on the dashboard | M | 3 |

### 6.5 Handover

| ID | Requirement | Pri | Phase |
| --- | --- | --- | --- |
| FR-40 | Handover builder pulls open and waiting cases, this shift’s closed cases and a free-notes box | M | 4 |
| FR-41 | The incoming engineer must acknowledge on screen (name and time) | M | 4 |
| FR-42 | “Copy for WhatsApp” output in the team’s current handover style | M | 4 |
| FR-43 | CSV export that pastes into the existing shift-notes sheet | M | 4 |
| FR-44 | Append to the Google Sheet automatically, only once approved | C | Later |
| FR-45 | Each case carries a link state (down, degraded, up) separate from its workflow status; the handover lists unresolved links first, then resolved | M | 4 |
| FR-46 | A case can list affected links (parent and backup links), shown under the main entry as LINKS AFFECTED | M | 4 |
| FR-47 | Group waiting cases by the team or person they wait on, so one chase covers all of that party’s links | S | 4 |

**Handover output format**, taken from the team’s 11 October 2026 sample. FR-42 must reproduce it exactly:

```
TICKET UPDATES – 11/10/2026
UNRESOLVED LINKS

<LINK NAME>
STATUS: DOWN
UPDATE: FOLLOWING UP WITH <TEAM OR PERSON> | <latest note>

<LINK NAME>
STATUS: DEGRADED
UPDATE: <latest note>
LINKS AFFECTED
<LINK>, <LINK>
-------------------------------------------------

RESOLVED LINKS

<LINK NAME>
STATUS: UP
```

- **Link state, not workflow status.** STATUS is DOWN, DEGRADED or UP; the case workflow status (open, waiting and so on) stays inside ELNOC.
- **UPDATE is built from the case.** “FOLLOWING UP WITH” plus the team or person the case waits on, then an optional note after a bar.
- **Capitals and date style** follow the sample: all caps, DD/MM/YYYY.
- **Teams are repeated.** In the sample, four of the 18 unresolved entries wait on the Oregun team and three on the Prec Pearl team, which is why FR-47 groups by waiting party.
- **Seed the contact directory** from the teams and people named in the sample.
- **Optional switch:** append how long each case has waited; off by default so the text matches today’s style.

### 6.6 Playbooks and platform

| ID | Requirement | Pri | Phase |
| --- | --- | --- | --- |
| FR-50 | Prompt a senior to promote a case to a playbook when a root-cause category recurs three or more times on a link or device type | S | 5 |
| FR-51 | Playbook = numbered steps, who to call, when to escalate, last-confirmed date; “stale” badge after 90 days | S | 5 |
| FR-52 | Suggest a matching playbook on the case page by category and keywords | S | 5 |
| FR-60 | Per-engineer accounts with a password now and SSO later | M | 0 |
| FR-61 | No hard deletes; every edit is versioned | M | 0 |
| FR-62 | Block obvious secrets (passwords, SNMP strings) in free text with a warning | M | 1 |
| FR-63 | Export cases and timings as CSV for the pilot measures | M | 2 |
| FR-64 | Weekly team-head report: repeat incidents per link, waiting-on-others age, time to resolve and wrong-team escalations, on screen and as CSV | S | 2 |

## 7. Non-functional requirements

The load is small (eight engineers), so the priorities are speed at the keyboard, trust in the data and alerting that keeps working when something else breaks.

| ID | Area | Requirement | How it is checked |
| --- | --- | --- | --- |
| NFR-01 | Speed | Quick Log page loads in under 1 second on the office LAN | Timed on a NOC PC |
| NFR-02 | Speed | Logging an event takes under 30 seconds end to end | Server timestamps in the pilot |
| NFR-03 | Availability | Alerting runs as a separate scheduled process from the web UI, so a UI fault does not stop notifications | Stop the UI, confirm a test alert still sends |
| NFR-04 | Availability | On-premises hosting keeps logging, search and dashboards working with the internet down; a cloud host cannot, so settle hosting before relying on this | Disconnect test |
| NFR-05 | Resilience | Each notification channel fails independently; one failure never blocks the others | Unit test with one channel forced to fail |
| NFR-06 | Resilience | A failed notification is retried and stays unsent until at least one channel delivers | Test with all channels down, then restored |
| NFR-07 | Monitoring the monitor | A heartbeat alert fires if collectors or the notifier have not run within an agreed interval | Stop the scheduler and confirm the alert |
| NFR-08 | Data integrity | Events are idempotent: re-running a collector never creates duplicates | Run twice, compare counts |
| NFR-09 | Auditability | No hard deletes; edits are versioned; every case change records who and when | Audit table review |
| NFR-10 | Backup | Nightly database copy to a second location; a restore is tested before the pilot | Restore drill |
| NFR-11 | Usability | Dark theme, large text, full keyboard flow for night shift | Night engineer review |
| NFR-12 | Time | Store all times in UTC, display in Africa/Lagos, show the timezone on every notification | Check across a midnight boundary |
| NFR-13 | Data residency | Logs and database stay on company-controlled infrastructure (on-premises or an approved cloud tenancy) | Security review |
| NFR-14 | Maintainability | Few pinned dependencies; a second person can run it with `pip install -r requirements.txt` and one command | Fresh-machine install |
| NFR-15 | Scale path | Start on SQLite with FTS5; move to Postgres only when concurrency or size demands it | Revisit after the pilot |

## 8. Data model

The spec’s model stays as the base. Eight new entities and a few added fields connect it to alerting, evidence and audit. Nothing in it may hold passwords, SNMP strings or SSH / WinBox credentials.

### 8.1 Entities from the spec, with additions

| Entity | Key fields | Addition in this design |
| --- | --- | --- |
| `customer` | id, name, aliases, tier, notes | None |
| `link` | id, customer\_id, name, circuit\_id, a\_end, b\_end, medium, responsible team, aliases | `primary_contact_id`, `tier` (core, distribution, access, edge, from the runbook), plus the sources that detect it (PRTG, Zabbix, SmartOLT, Phoenix flag) |
| `contact` | id, name, role, team, phone, availability\_hours, notes | `email`, `whatsapp_number`, `preferred_channels` |
| `escalation_rule` | link or customer, step order, contact\_id, wait\_minutes | `channels` per step |
| `case` | opened\_at, closed\_at, engineer, customer, link, device, phoenix\_ticket\_no, symptom, checks\_done, root\_cause\_category and detail, fix, helped\_by, escalated\_to, time\_to\_resolve\_min, first\_thing\_to\_check\_next\_time, status, confirmed\_by | `severity`, `opened_by` (auto or manual), `acknowledged_by`, `acknowledged_at`, `outage_location` |
| `case_event` | case\_id, at, engineer, kind, text | New kind: `notification` |
| `handover` | shift\_date, shift, from, to, open\_case\_ids, free\_notes, acknowledged\_by, acknowledged\_at | None |
| `playbook` | title, trigger\_category, steps, owner, last\_confirmed\_at | None |
| `alias_learned` | typed\_text, entity type and id, count | None |

### 8.2 New entities

| Entity | Key fields | Purpose |
| --- | --- | --- |
| `event` | key (fingerprint), type, source, device, summary, severity, ref, occurred\_at, received\_at, case\_id | The notifier’s `events` table, now linked to a case |
| `notification` | id, case\_id, event\_key, contact\_id, channel, status, sent\_at, ack\_at, error | Delivery log and acknowledgement (FR-29, FR-34) |
| `case_watcher` | case\_id, contact\_id, added\_by, added\_at | Optional extra recipient (FR-27) |
| `attachment` | case\_id, filename, stored\_path, sha256, uploaded\_by, uploaded\_at, note | Trace output and screenshots (FR-31) |
| `site_device` | id, hostname, ip, site, latitude, longitude, criticality tier, link\_id, monitored\_in | Location source and tier lookup (FR-32) |
| `maintenance_window` | target (device or link), start, end, reason, created\_by | Alert suppression (FR-09) |
| `app_user` | id, name, role, active, password hash | Per-engineer accounts (FR-60) |
| `audit_log` | entity, entity\_id, version, changed\_by, changed\_at, diff | Versioned edits (FR-61) |

**Severity mapping.** ELNOC uses critical, major, minor, info, as in the notifier. PRTG Down maps to critical; Zabbix severity 4 and above maps to critical and lower values to major, as the notifier does today; mailbox downtime emails map to major. The mapping lives in a config table so the team can change it without code.

**Root-cause categories** stay a fixed, editable list: far-end not transmitting, fibre cut, power, transceiver or optics, config, third-party or ISP, planned maintenance, unknown.

**Handover-driven fields.** From the handover sample, `case` also needs `link_state` (down, degraded, up), `waiting_on` (a contact or team, shown after “FOLLOWING UP WITH”), and a `case_link` table so one case can cover several affected links.

## 9. Integrations

Every source is an adapter that returns the same normalized `Event`, as the notifier’s collectors already do. Start with pulling on a five-minute schedule (the cron example in the script); add push (webhooks) later where the source supports it, to cut detection delay.

### 9.1 PRTG

Pilot: poll `/api/table.json` for sensors with status Down, using a dedicated read-only PRTG account. Later: a PRTG **HTTP Action** notification that posts to an ELNOC webhook, which the runbook already names as a supported path. Map each sensor to a `site_device` record so tier and link are known.

### 9.2 Zabbix

Pilot: JSON-RPC `problem.get` with an API token. Request the host name (`selectHosts`) so the device is the real host. Later: a Zabbix **webhook media type** pointing at ELNOC, as in the runbook’s section 6.2.

### 9.3 SmartOLT

The Perplexity note says SmartOLT publicly documents a REST API and Telegram alerts for PON outages, and that WhatsApp and the extra-contact feature are not built in. I have not verified this, so treat it as a question for your SmartOLT admin:

- Which events (PON outage, ONU offline, ONU signal) can the API return, and with what fields?
- How does the API authenticate, and are there rate limits?
- Can it filter by changes since a timestamp, so polling stays light?

If the API covers the events, add a `collect_smartolt()` adapter. If not, use another approved source (for example email alerts through the mailbox collector) or keep a controlled manual log step, as the note advises. WhatsApp and the optional extra contact are ELNOC features either way, never assumed from SmartOLT.

**Per-customer coverage.** Some customers are detected only by SmartOLT, some by SmartOLT together with PRTG, and Cloud Phoenix flags others. The registry therefore records the detecting sources for each customer and link (FR-18), and events from any of them land on the same case. The pilot alerts on PRTG and Zabbix first; SmartOLT and Phoenix are added afterwards, each switchable on or off per source.

### 9.4 Cloud Phoenix and the mailbox

Phoenix, in order of preference: API, webhook or scheduled export, CSV import (already planned for Phase 1), and finally the “Copy for Phoenix” button. Confirm which one exists with your Phoenix admin. Because the route is not yet known, CSV import is the committed path and API sync is an optional upgrade. The mailbox collector reads downtime emails by subject keyword over IMAP, with fixes listed below.

### 9.5 Delivery channels

| Channel | Provider in the script | Constraint to design for |
| --- | --- | --- |
| Email | SMTP | Simplest and auditable; use it as the record of every alert |
| WhatsApp | Meta Cloud API | Free-form text only works inside the 24-hour window; outside it, a pre-approved **template message** is required, so alerts at night need templates |
| SMS | Twilio (script comment says swap for Termii or similar) | Choose a provider that delivers reliably on local networks; keep the message under about 300 characters |
| Paging app | Not in the script | If the team already uses Telegram, PagerDuty or Opsgenie per the runbook, ELNOC can post to the same service instead of building a new channel |

### 9.6 Gaps found in `noc_manager_notifier.py`

The script is a sound prototype. I read it against the escalation and reliability requirements and found these items to fix when its code moves into ELNOC:

| # | Finding | Why it matters | Fix |
| --- | --- | --- | --- |
| 1 | PRTG `occurred_at` falls back to the current time when `lastup` is missing | The fingerprint changes every run, so the same outage can re-alert every five minutes | Use a stable value such as the first-seen time stored by ELNOC |
| 2 | The “sensor verified up” loop is sliced to zero items (`[:0]`) | Recoveries are never produced | Emit recoveries and attach them to open cases (FR-08) |
| 3 | Zabbix `device` is set to the problem name, and `recent: True` is used | The device is wrong; per the Zabbix API reference `recent` also returns recently resolved problems, so resolved problems may alert (check on your version) | Add `selectHosts`, drop `recent` or filter by status |
| 4 | The mailbox fetch uses `RFC822` | This marks mail as read, hiding it from humans; a crash after fetch loses the email | Fetch with `BODY.PEEK[]`, mark seen only after the event is stored |
| 5 | `sent` is one flag per event | If email works and WhatsApp fails, the failure is never retried or shown | Per-channel delivery log (`notification` table) |
| 6 | One message per critical event | A core outage with many down sensors sends a flood of messages | Correlate to one case, one message, then updates (FR-07) |
| 7 | WhatsApp sends free-form text only | Outside 24 hours the call fails and is only printed | Use approved templates for alerts |
| 8 | No acknowledgement or escalation | Nobody is chased if the manager does not respond | Escalation engine and acknowledgement links (FR-28, FR-29) |
| 9 | Connections are opened per call and never closed; cron runs can overlap | “Database is locked” errors under SQLite | Enable WAL mode, use a timeout and a lock file |
| 10 | Errors are printed only | A broken collector goes unnoticed | Heartbeat alert and a collector status page (NFR-07) |

## 10. Notification and escalation design

The case is the source of truth inside ELNOC; email, WhatsApp and SMS are notifications about it, never the only record. Phoenix remains the official ticket (section 2).

### 10.1 Who gets told

- **Primary contact:** set per link or customer. Gets the first notification by email and WhatsApp, with SMS as the fallback.
- **Escalation steps:** the `escalation_rule` list for that link or customer (contact, wait minutes, channels). If a step is not acknowledged within its wait time, ELNOC notifies the next step.
- **Optional watcher:** one extra recipient that an authorized engineer adds to a single case or sets as a standing watcher on a link; both modes are optional. The watcher receives status updates for that case only, never other cases or raw events. ELNOC records who added them and when.
- **Updates, not noise:** recipients get messages on opened, acknowledged, escalated and resolved, not on every raw monitoring event.

### 10.2 Delivery rules

The notifier already separates instant and digest delivery; this keeps that split and adds the escalation behaviour. Values marked \* are proposals to confirm with your team head.

| Severity | Delivery | Channels | If not acknowledged |
| --- | --- | --- | --- |
| Critical | Instant, one message per case | Email, WhatsApp, SMS | Escalate to the next step after its wait time |
| Major | Digest every 4 hours\* (instant if the link rule says so) | Email, WhatsApp | Appears in the digest and on the dashboard |
| Minor | Digest only | Email | None |
| Info | Stored on the case, not pushed | None | None |

When a case is acknowledged, escalation stops. When a recovery event arrives, the case gets a note and a “consider closing” prompt; a human closes it.

&#91;embedded content: escalation flow · 2 decisions, 1 loop\]

Each step is told in turn; an acknowledgement ends the chain, and a case that runs out of steps turns red on the dashboard and in the handover.

**Proposed starting defaults.** You have no current rules for severity and wait times, so these are my proposals, to be tuned in the pilot against the MTTA and MTTR targets:

| Rule | Proposed default | Why |
| --- | --- | --- |
| Acknowledgement wait per escalation step | 15 minutes | Three steps fit inside the 1-hour MTTA target |
| Major-severity digest | Every 4 hours | The schedule in the notifier script’s cron example |
| Stale waiting-on-team flag | 2 hours | Half the 4-hour MTTR target, leaving time to re-verify or escalate |
| MTTR breach marker | Case turns red at 4 hours | Matches the MTTR target |
| Alert delay before a case opens | Core and distribution 1 minute; access and edge 5 minutes | The tier thresholds in the runbook |

### 10.3 Message template

Adapted from the incident-workflow note, with the same fields on every channel:

```
NOC case [ID] | [severity]
Event:     [PON outage / sensor down / link failure]
Affected:  [customer, link or device, site]
Detected:  [date, time, WAT]
Status:    [new / acknowledged / escalated / waiting / resolved]
Case:      [internal link]
Acknowledge: [one-tap link]
```

The SMS and WhatsApp short form keeps the first four lines and the link. Never include credentials or raw diagnostic output. Include customer-identifying detail only where company policy allows that channel.

### 10.4 WhatsApp specifics

Register one template for “new critical case” and one for “escalation” with the variables above, and get both approved by Meta before the pilot. Confirm with your admin who is authorized to send, how recipient numbers are managed, and whether messages must be retained for audit.

## 11. Quick Log client and UX design

The client stays deliberately dumb: an AutoHotkey v2 script registers the hotkey and opens the server’s quick-log page in a small borderless Edge or Chrome `--app=` window. All logic lives on the server.

**The happy path (target under 30 seconds)**

1. Press the hotkey (default Ctrl+Alt+L). The pane opens with focus in one search box, and the device field is pre-filled from the active window title (PuTTY or WinBox titles usually carry the device name or IP).
2. Type shorthand such as “ltv8 ikeja”. Ranked matches appear, with frequently chosen aliases first.
3. Press Enter on a match. The card fills in customer, link, endpoints, responsible team, escalation steps and the last three cases on that link, plus a matching playbook once Phase 5 exists.
4. Type the symptom in one line. Status defaults to open.
5. Press Ctrl+Enter to save. The pane then offers “Copy for Phoenix” and, if the case is critical, a prompt to notify the primary contact.

**What the client must not do.** It does not log keystrokes, read the clipboard silently, or take screenshots. A security team would rightly reject that, and the spec rules it out. Evidence is attached only by an explicit engineer action: a file picker, or pasting an image into the case page with Ctrl+V.

**Screens**

| Screen | Purpose | Key elements |
| --- | --- | --- |
| Quick Log pane | Open a case in seconds | One search box, ranked matches, auto-filled card, symptom, status |
| Case page | Work the case | Timeline, status buttons, escalation log, similar cases, evidence, close-out form |
| Dashboard | See the whole NOC | Open cases, waiting-on-others with age (red when stale), cases this shift, failed notifications |
| Handover | Pass the shift | Builder, on-screen acknowledgement, WhatsApp and CSV output |
| Admin | Keep data correct | Customers, links, contacts, escalation rules, root-cause list, users, maintenance windows |

**Look and feel.** Dark theme, large text and a full keyboard flow, because the night engineer works alone. Forms ask only for what is needed to open the case; everything else is optional until close-out. The server renders pages with Jinja2 and HTMX, so no heavy JavaScript framework is needed.

## 12. Security, privacy and approvals

ELNOC will hold customer names, link and circuit IDs and contact phone numbers, so it needs a security review before the pilot. One tension to raise early: the spec says data must stay on company servers (read here as company-controlled infrastructure, since an approved cloud is acceptable), but WhatsApp and SMS messages necessarily pass through Meta and the SMS provider. The answer is a minimal message template (section 10.3), not storing anything extra with those providers.

**Controls**

| Control | Requirement |
| --- | --- |
| Credentials | Never store passwords, SNMP strings or SSH / WinBox credentials; a regex check warns and blocks obvious secrets in free text |
| Configuration | All keys and tokens in `.env` or the company secrets store, never in the repository |
| Source access | Read-only accounts for PRTG, Zabbix, SmartOLT and Phoenix, each with the least access that works |
| Authentication | Per-engineer accounts, hashed passwords, roles as in section 4; SSO later |
| Transport | HTTPS on an internal hostname; hotkey client talks only to that server |
| Evidence files | Stored on the server behind login; screenshots and trace output can reveal topology, so access follows role |
| Client agent | Hotkey only; no keystroke logging, silent clipboard reads or screenshots |
| Audit | Versioned edits, no hard deletes, a delivery log of every notification |
| Backups | Nightly copy to a second company location; restore tested |
| Outbound messages | Fixed template; no credentials or raw diagnostic output; customer detail only where policy allows |

**Approvals to file.** None blocks the first phase, but several gate the later ones.

| Approval | Needed by |
| --- | --- |
| VM or approved cloud tenancy, and an internal hostname | Phase 0 |
| AutoHotkey (or an alternative) allowed on NOC PCs | Phase 1 |
| Security review of stored data | Before the pilot |
| Read-only API accounts for PRTG and Zabbix | Phase 3 |
| SmartOLT API access and event coverage confirmed | Phase 3 |
| Phoenix API or scheduled export | Phase 3 |
| WhatsApp Cloud API account and approved templates; SMS provider account; SMTP relay account | Phase 3 |
| Google Workspace access to the shift-notes sheet | Later |
| SSO / AD integration | Later |

## 13. Implementation plan

The spec’s build rule stands: build phase by phase, and do not start the next phase until the current one passes its tests. This plan keeps the spec’s Phases 1 and 2, adds a foundations phase, and inserts **Alerting and escalation** as Phase 3 because the notifier code already exists. That renumbers the spec’s Handover to Phase 4 and Playbooks to Phase 5. You named handover and escalation as the top pains, so the build order is 0, 1, 2, 4, 3, 5: Handover (Phase 4) is built before Alerting (Phase 3). Phase numbers stay as they are so the requirement IDs do not change. The pilot alerts on PRTG and Zabbix only. Timings below are indicative, taken from the spec’s weekly plan; confirm them against the developer’s capacity.

| Phase | Indicative timing | Delivers | Exit criteria |
| --- | --- | --- | --- |
| 0. Foundations | Before week 1, approvals in parallel | FastAPI skeleton, SQLite with FTS5, accounts, versioned edits, `.env` config, nightly backup, test setup | Login works; backup and restore drill passes |
| 1. Quick Log and registry | Week 1 | CSV import, hotkey client, fuzzy search, auto-fill, quick-create, alias learning, Copy for Phoenix, secret block | Tests pass for fuzzy matching, alias learning and secret regex; page loads under 1 s |
| 2. Case lifecycle | Week 2 | Timeline, close-out rules, similar cases, stale-wait flag, dashboard, evidence and location, CSV export, 10 seed cases including the LTV8 case | Tests pass for similar-case ranking and stale-wait; seed data loads |
| 3. Alerting and escalation | Weeks 4 to 5, after Handover | Notifier code ported into adapters (PRTG and Zabbix first), correlation, delivery log, escalation engine, acknowledgement links, WhatsApp, then SmartOLT and Phoenix feeds if available, each switchable per source; optical readings stored per poll (FR-82) | Collectors idempotent; one failing channel does not block others; escalation advances after the wait and stops on acknowledgement; heartbeat alert works; test sent to a non-production recipient |
| 4. Handover | Week 3 | Builder, on-screen acknowledgement, WhatsApp text, CSV export | Handover output test passes against the 11 October sample and the text matches the team’s current style |
| Pilot | Two weeks after Phases 3 and 4 | Day shift plus the night engineer log every incident | Measures in section 3 compared with the previous two weeks |
| 5. Playbooks and learning | During or after the pilot | Promotion prompt, playbooks, stale badge, suggested playbook | Prompt fires at three recurrences; badge shows after 90 days |
| 6. AI agents | After the pilot review, in four stages | Ask, Draft, Watch and an optional Act stage (section 17) | Criteria per stage in section 17.6 |
| Later | After approvals | Phoenix sync, Sheets append, SSO | Separate approval each |

Every phase also ships its tests, a README (run, backup, restore) and, by the pilot, a one-page user guide. Keep the Phase 3 manual fallback: until the pilot proves alerting, engineers still page the manager the current way.

## 14. Testing and pilot

### 14.1 Automated tests

The spec lists six pytest areas; Phase 3 adds the alerting ones. Items marked \* are new in this design.

| Area | The tests must prove |
| --- | --- |
| Fuzzy matching | “ltv8 ikeja” ranks the LTV8 Ikeja-RC link first |
| Alias learning | A shorthand chosen repeatedly ranks above its rivals next time |
| Similar-case ranking | Same link first, then same customer, then full-text matches |
| Stale-wait rule | A waiting case turns stale exactly when its wait time passes |
| Handover output | Unresolved and resolved links appear exactly as in the 11 October sample, including STATUS, UPDATE and LINKS AFFECTED lines |
| Secret block | Passwords and SNMP strings in free text are blocked |
| Collector idempotency\* | Running a collector twice creates no duplicate events or cases |
| Correlation\* | Ten sensor-down events on one link produce one case and one message |
| Escalation\* | With no acknowledgement, the next step is notified after its wait; acknowledgement stops it |
| Channel isolation\* | With WhatsApp forced to fail, email and SMS still deliver and the failure is logged |
| Maintenance window\* | Events inside a window raise no notification |
| Template\* | Messages carry the timezone and contain no credentials |

### 14.2 Pilot

1. **Baseline.** Before go-live, record the previous two weeks of the measures in section 3 from the Google Sheet and WhatsApp history.
2. **Dry run.** Start with a small set of frequent, well-understood alert types and a test recipient. Check that alerts open the right case, updates do not duplicate it, recovery updates it, and failed notifications are visible to the NOC.
3. **Live pilot.** Two weeks, day shift plus the night engineer, every incident logged in ELNOC. Keep the manual paging fallback.
4. **Weekly review.** Walk through the dashboard with the team head: stale waits, wrong-team escalations, failed deliveries, complete-card rate.
5. **Decision.** Compare against the baseline and the targets agreed in section 3, then decide to extend, adjust or stop.

## 15. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| SmartOLT’s API does not expose the events we need | Confirm with the SmartOLT admin in Phase 0; fall back to another approved source or a controlled manual log step |
| WhatsApp templates are slow to approve, or the 24-hour window blocks alerts | File templates in Phase 0; launch with email and SMS, add WhatsApp when approved |
| A core outage floods the manager with messages | Correlate to one case and one message; later updates only on status changes |
| Engineers skip logging because it feels like extra work | Keep logging under 30 seconds, show stale waits on a shared dashboard, review feedback weekly in the pilot |
| Security rejects the hotkey client | Fall back to an installed-app shortcut or bookmark to the same page; the client adds convenience only |
| Contacts and escalation steps go stale | Every contact and rule carries a confirmed date; an admin reviews them on a schedule |
| Double entry persists between ELNOC and Phoenix | “Copy for Phoenix” now; Phoenix API or export sync later |
| The notifier fails silently | Separate process, heartbeat alert, collector status page, manual paging fallback during the pilot |
| Past cases or playbooks give wrong advice | Close-out requires a root cause; playbooks show a stale badge after 90 days; seniors confirm them; no claim of machine learning |
| Only one person can maintain it | Few pinned dependencies, README, and a second person runs it from a clean install |
| Unverified claims from the research notes reach the design | Treat every product capability in them (SmartOLT, Phoenix) as a question for the owning admin until confirmed |
| AI agents give wrong or invented answers, or send sensitive data to the provider | Numbers come from code, answers cite sources, data is minimised before every call, actions need approval, and an admin kill switch exists (section 17.4) |

## 16. Decisions needed before development

Answered on 12 October: 2 (working MVP plus pilot), 3 (manager as primary with an optional watcher, per case or standing), 4 (outage map is optional; evidence attachments stay), 6 (route unknown, so CSV first), 7 (an existing company WhatsApp account; confirm whether it runs on the Meta Cloud API), 8 (SMS is not in use today, so it is an optional fallback), 10 (only email and WhatsApp are in use) and 12 (an approved cloud is allowed). Also answered: 1 (Phoenix stays the official record; ELNOC is the team-facing working twin), 5 (SmartOLT coverage will be found while building the MVP), 11 (handover sample received, see section 6.5) and 13 (pilot targets: link uptime 97%, MTTR 4 hours, MTTA under 1 hour). Still open: 9, where section 10.2 now proposes defaults for you to accept or change.

| # | Decision | Recommendation | Decide with |
| --- | --- | --- | --- |
| 1 | Which record is official, Phoenix or ELNOC? | Phoenix is the official ticket; ELNOC is the operational record linked by ticket number | Team head |
| 2 | What are you expected to deliver: a proposal, a prototype or a production integration? | Build the MVP through the two-week pilot, on-premises | Team head |
| 3 | Who is the primary contact per link, and who may add an extra watcher? | Primary on the link record; any engineer may add one watcher, logged | Team head |
| 4 | What do “coordinates” mean: map coordinates of the site, or trace hops? | Support both: location from the site inventory, trace output as an attachment | Team head |
| 5 | Does SmartOLT’s API expose the events and fields we need? | Confirm before Phase 3; plan a fallback source | SmartOLT admin |
| 6 | How can Phoenix feed ELNOC: API, webhook, scheduled export or CSV only? | Start with CSV; use the best available route in Phase 3 | Phoenix admin |
| 7 | WhatsApp: which provider, which templates, who may send? | Meta Cloud API with two templates; file the request now | IT / security |
| 8 | Which SMS provider delivers best locally? | Pick one with delivery reports; keep the interface swappable | IT |
| 9 | Delivery rules and wait times per severity (the \* values in section 10.2) | Start with the table in 10.2 and tune in the pilot | Team head |
| 10 | Is a paging tool (Telegram, PagerDuty, Opsgenie) already in use for on-call? | If yes, send through it instead of building a new channel | Team head |
| 11 | What does the current grand-handover WhatsApp message look like? | Share one sample so the output matches | Day-shift engineers |
| 12 | Where does it run and where is the second backup copy? | VM and internal hostname; backup on a separate company location | IT |
| 13 | What targets should the pilot measures hit? | Fix them after the baseline, not before | Team head |
| 14 | May minimised prompts (link IDs and readings, no customer names) go to an external AI provider? | Ask security early; start the AI layer at the Ask level only | IT / security |

Once 1 to 4 are answered, Phase 0 can start and the other items run in parallel as approvals.

## 17. AI agent layer

AI agents turn ELNOC from a record keeper into an assistant that reads, explains, drafts and watches, while people stay in charge of every action that changes something. The layer needs only an internet connection: a hosted LLM API, a few tools the team writes, and the knowledge ELNOC already holds. It builds on the core system (sections 5 to 14) and arrives as Phase 6, after the pilot.

### 17.1 What agents add

| Area | What agents add | Example in ELNOC |
| --- | --- | --- |
| Efficiency | Free-text quick log; drafted Phoenix tickets and handover text; short summaries of long cases | Type one line such as “ltv8 ikeja far end not transmitting, rsl low”; the agent fills customer, link, symptom and a suggested root cause for you to confirm |
| Automation | Alert triage, a background watch on signal trends, drafted chase messages and weekly reports | When a core sensor drops, the agent attaches similar cases and the first check before anyone opens the case |
| Accuracy | Calculations done in code, answers that cite their source, cross-checks against monitoring and history | Flags a handover entry that says DOWN while PRTG shows UP, or a waiting case with no waiting party |
| Ease of use | Plain-language explanations of fibre terms and questions asked over your own case history | “Why does −28 dBm matter on this optic?” or “Which links waited longest on the Oregun team this month?” |

**How far it can grow.** The layer grows in four steps, each needing more trust than the last:

1. **Ask.** The agent answers questions, explains terms and reads a trace or an RSL value.
2. **Draft.** The agent writes cases, tickets, handovers and messages; a person reviews and sends.
3. **Watch.** The agent scans signal trends in the background and adds watch notes to cases and links.
4. **Act with approval.** The agent proposes an action (open a case, notify a contact, escalate) and a person approves it with one click.

Steps 1 and 2 are low risk and can start straight after the pilot. Steps 3 and 4 should wait until the answers have been measured against real cases (section 17.6).

### 17.2 Agent layer architecture

The agent service runs inside ELNOC and makes one external call: to the hosted model. Everything else it does goes through tools the team writes.

&#91;embedded content: agent layer · 1 model, 6 tools, 1 approval gate\]

The model never touches ELNOC directly. It asks the orchestrator to call a tool, its answer passes through the guardrails, and any action that would change a case or send a message waits at the approval gate for a person.

### 17.3 Agent catalogue

Eight agents cover the capabilities in 17.1. Start with one agent holding several tools, and split it into these roles only when its instructions grow muddled. The last column uses the four steps from 17.1: 1 Ask, 2 Draft, 3 Watch, 4 Act with approval.

| Agent | What it does | Tools it uses | Output | Step |
| --- | --- | --- | --- | --- |
| Explainer | Defines fibre terms and the team’s shorthand (RSL, far-end, “RC”) in plain language | Knowledge base, web lookup | Short answer with a cited source and date | 1 |
| History analyst | Answers plain-English questions over cases, such as which links waited longest on a team this month | ELNOC data through fixed read-only queries, never free SQL | Answer with the table behind it | 1 |
| RSL interpreter | Judges a received-signal reading against the optic’s limits and the link’s own history | Monitoring history, calculators, datasheet lookup | Margin in dB, status, likely causes, first checks | 1 |
| Trace reader | Reads an OTDR trace file and lists events by distance, loss and reflectance, then explains them | Trace parser, ELNOC data, knowledge base | Event table, likely cause, next check, matched to the link’s route | 1 |
| Quick Log assistant | Turns one typed line into a filled-in case | ELNOC registry and alias learning | Pre-filled card for the engineer to confirm | 2 |
| Triage assistant | When a case opens, adds similar cases, the first thing to check, a matching playbook and who to call | ELNOC data, playbooks | Triage note on the case | 2 |
| Report writer | Drafts the handover text in the team’s format, Phoenix ticket text, chase messages and the weekly report | ELNOC data | Drafts a person reviews and sends | 2 |
| Risk watcher | Scans signal history for gradual degradation and adds watch notes to links | Monitoring history, calculators | Watch note with risk level and reasons, never a countdown | 3 |

Two built-in checks belong to the Report writer and Triage assistant: flag a handover entry whose link state disagrees with monitoring, and flag a waiting case with no waiting party. Both produce a warning for a person, not a correction.

**Reading OTDR files.** Open-source parsers exist for the Telcordia SR-4731 `.sor` format, such as [pyOTDR](https://pypi.org/project/pyOTDR/) and [otdrs](https://pypi.org/project/otdrs/). The pyOTDR author says its decoding was pieced together from a limited set of sample files, so test any parser on files from your own OTDR before relying on it. Screenshots of traces can be read by a vision-capable model but with lower reliability, so treat `.sor` files as the preferred input.

### 17.4 Autonomy levels and guardrails

Each agent is switched on at one level at a time, and an admin can raise or lower it per agent.

| Level | The agent may | A person must | Enable only when |
| --- | --- | --- | --- |
| 1 Ask | Answer questions and explain; no writes | Read and judge the answer | Answers cite sources and the glossary is loaded |
| 2 Draft | Fill forms and write drafts, marked as AI-written | Confirm or edit before anything is saved or sent | Draft marking and edit tracking work |
| 3 Watch | Scan data in the background and add watch notes | Decide what to do with a note | A backtest on your own history shows the warnings are useful (section 17.6) |
| 4 Act with approval | Propose opening a case, notifying a contact or escalating | Approve each action with one click | Levels 1 to 3 have run well in practice and security has signed off |

**Never, at any level:** change device configuration, send anything to a customer, close a case, delete data, or see or store credentials. Escalation never happens without a person’s approval.

**Guardrails that apply to every agent**

- **Read-only by default.** Write tools create drafts or watch notes only.
- **Data minimised before the model call.** Customer names become link IDs or aliases, phone numbers are stripped, and the secret check from section 12 runs on every prompt.
- **Numbers come from tools.** Margins, trends and counts are computed in code; the model quotes them and does not calculate.
- **Sources and honesty.** Each answer shows its sources and a confidence label, and “I don’t know” is an accepted answer.
- **Fetched text is data, not instructions.** Web pages, emails and trace files can contain text that tries to steer the model, so the agent never follows instructions found inside them.
- **Allowlisted web only.** Lookups go to approved domains, and results are cached with their date.
- **Full audit.** Every agent action is logged on the case timeline: who asked, which tools ran, and what came back.
- **Cost and kill switch.** Per-user daily limits, and an admin switch that turns off the agent layer without affecting the core system.
- **Feedback loop.** A thumbs up or down on every answer; a senior can confirm a good answer to add it to the knowledge base.

### 17.5 AI requirements

There are 21 functional and 4 non-functional AI requirements. Priority is as in section 6. Phase 6 splits into four stages that match the steps in 17.1: 6a Ask, 6b Draft, 6c Watch, 6d Act.

| ID | Requirement | Pri | Phase |
| --- | --- | --- | --- |
| FR-70 | Ask panel on the case page and dashboard; answers use the open case as context | M | 6a |
| FR-71 | Glossary of fibre terms and team shorthand, editable by seniors, loaded as the first knowledge source | M | 6a |
| FR-72 | Web lookup limited to an admin-managed allowlist; results cached; every answer shows its source and date | M | 6a |
| FR-73 | RSL interpreter: compare a reading with the optic’s limits and the link’s history; return margin, status, likely causes and first checks | M | 6a |
| FR-74 | Record the optic model and datasheet limits for each link end | M | 6a |
| FR-75 | Trace reader: attach an OTDR `.sor` file to a case; return an event table and a plain-language explanation; keep the file as evidence | S | 6a |
| FR-76 | History analyst: answer plain-English questions through fixed, read-only queries | S | 6a |
| FR-77 | Free-text Quick Log: one typed line fills customer, link, symptom and a suggested root-cause category for confirmation | S | 6b |
| FR-78 | Triage note on a new case: similar cases, first check, matching playbook, who to call | S | 6b |
| FR-79 | Report writer: drafts for the handover (in the 11 October sample format), Phoenix ticket text, chase messages and the weekly report narrative | S | 6b |
| FR-80 | Consistency checks that warn when link state disagrees with monitoring, or a waiting case has no waiting party | S | 6b |
| FR-81 | AI-written text is marked until a person accepts or edits it | M | 6b |
| FR-82 | Store every optical reading (RSL and related) per link at each poll as a time series; start collecting as soon as alerting is live, so history exists when Phase 6c begins | M | 3 |
| FR-83 | Risk watcher: detect drift and sudden steps in readings; show a risk level with reasons; show a time range only when enough data exists | S | 6c |
| FR-84 | Backtest report comparing warnings with past failures in ELNOC history; the Watch level stays off until the team accepts the result | M | 6c |
| FR-85 | Agents can propose actions (open a case, notify, escalate); each needs one-click approval and is logged | C | 6d |
| FR-86 | Admin sets each agent’s level and can switch the whole layer off | M | 6a |
| FR-87 | Minimise data before every model call: aliases instead of customer names, no phone numbers, secret check | M | 6a |
| FR-88 | Log every agent call on the case timeline with the tools used and the answer | M | 6a |
| FR-89 | Thumbs up or down on each answer; a senior can confirm an answer into the knowledge base | S | 6a |
| FR-90 | Daily cost cap per user and a monthly budget alert | S | 6a |

| ID | Non-functional requirement | How it is checked |
| --- | --- | --- |
| NFR-20 | Agents never slow or block logging, alerting or handover; if the model is unreachable, the core system works unchanged | Cut the connection and run the core flows |
| NFR-21 | A fixed test set of real questions, readings and traces runs before any prompt or model change | Test set passes before release |
| NFR-22 | The model provider sits behind one interface so the model or vendor can be changed | Swap in a second model in a test |
| NFR-23 | Prompt and answer logs follow the same retention and access rules as case data | Security review |

### 17.6 Phase 6 plan

Phase 6 starts after the pilot review and runs in four stages. Timings are indicative and depend on how much history exists.

| Stage | Timing | Delivers | Exit criteria |
| --- | --- | --- | --- |
| 6a Ask | First, after the pilot | Ask panel, glossary, cited web lookup, RSL interpreter, trace reader, history analyst, kill switch, audit log | The fixed test set passes; every answer cites a source; the kill switch is tested; security has approved sending minimised prompts to the provider |
| 6b Draft | After 6a is trusted | Quick Log assistant, triage note, report writer, consistency checks, AI-draft marking | Draft acceptance rate and time saved are measured for two weeks and reviewed with the team head |
| 6c Watch | When enough reading history exists | Risk watcher and the backtest report | The backtest is accepted by the team; warnings are shown as risk levels with reasons |
| 6d Act | Last, and optional | Proposed actions with one-click approval | Approval flow and audit tested; security sign-off |

**Start now, so the AI has something to work with.** These cost little and belong in earlier phases:

- Store every optical reading per poll once alerting is live (FR-82), because the risk watcher needs months of history and cannot recover data that was never kept.
- Record the optic model for each link end in the registry (FR-74).
- Collect sample OTDR `.sor` files and the datasheets for the optics in use.
- Keep root-cause categories consistent at close-out; they become the labels the backtest learns from.
- Build the glossary of fibre terms and team shorthand as cases are logged.

### 17.7 Data, cost and approvals

- **What it needs:** an API key for a hosted model, an allowlist of reference websites, and the existing ELNOC server. No GPU or local model hosting.
- **Approvals:** security must agree that minimised prompts (link IDs and readings, no customer names or credentials) may go to an external provider. Check the provider’s current data-use terms as part of that review.
- **Cost:** it grows with the number of questions and how much context each one carries. Control it with caching, short context, a smaller model for simple tasks and the daily cap in FR-90. Estimate the monthly cost from the first two weeks of real use at stage 6a, not before.

### 17.8 Success measures for the AI layer

| Measure | How it is measured |
| --- | --- |
| Time to log a case with the Quick Log assistant | Compared with manual logging, from server timestamps |
| Draft acceptance | Share of AI drafts accepted with little or no edit |
| Handover time with the report writer | Against the pilot baseline |
| Answer quality | Score on the fixed test set, plus thumbs and senior confirmations |
| Warning usefulness | Share of warnings followed by a real fault, and share of past faults preceded by a warning, in the backtest |
| MTTA and MTTR | Must not get worse than the pilot targets (under 1 hour and 4 hours); the aim is to improve them |

### 17.9 Limits

- **Sudden failures can’t be predicted.** A fibre cut gives no warning; the risk watcher only covers gradual degradation.
- **Wrong inputs give wrong margins.** If a link end has the wrong optic recorded, the margin is wrong.
- **The model can be wrong or make things up.** That is why numbers come from code, answers cite sources, and a person approves anything that acts.
- **Parsers can misread trace files.** Vendor-specific files may need fixes.
- **Forecasts need data.** Sparse polling or short history limits what trends can show.
- **It depends on an external service.** An outage, a price change or a model change affects it, which is why the core system must never depend on it (NFR-20).
