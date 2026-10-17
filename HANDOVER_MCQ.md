# ELNOC Handover & Escalation — decision pack

Two parts, both written to be answered, not just read:
- **Part A — MCQ (Q1–Q30):** how the handover should look. Tick one option per
  question, return it, ELNOC is configured to match. Defaults are marked ★ —
  they are what the system does today.
- **Part B — escalation detail checklist:** the fields every escalation must
  carry before it counts as handed over. This is the standard the system now
  measures against.

---

# PART A — MCQ: how the handover should appear

Answer format: `Q1=B, Q2=A, Q3=C …` (any unanswered = keep the ★ default).

## A1. The top line (the header)
- **A ★** `TICKET UPDATES – DD/MM/YYYY` (today's exact style)
- **B** `NOC HANDOVER – DD/MM/YYYY HH:MM WAT` (adds the time)
- **C** `TICKET UPDATES – DD/MM/YYYY (DAY/NIGHT SHIFT)`

## A2. Section order
- **A ★** `UNRESOLVED LINKS` first, then `RESOLVED LINKS`, then the summary
- **B** Summary (tally) first, then unresolved, then resolved
- **C** Keep unresolved/resolved only — drop the summary

## A3. Sorting inside UNRESOLVED LINKS
- **A ★** Worst first: DOWN → DEGRADED → UNSTABLE
- **B** Oldest outage first (longest waiting on top)
- **C** By responsible party (one chase per team, grouped)

## A4. Is `UNSTABLE` a real state you want in the tally?
- **A ★** Yes — DOWN / DEGRADED / UNSTABLE / UP as four states
- **B** No, fold it into DEGRADED
- **C** Only if we define it strictly (see B6)

## A5. What exactly counts as UNSTABLE?
- **A ★** Flapping: link cycles up/down, or monitoring shows repeated state changes
- **B** Link is up but carrying errors/loss above threshold
- **C** Both — and ELNOC should decide from monitoring data, not by hand

## A6. The SHIFT SUMMARY block (end of the message)
- **A ★** On by default (can be turned off per handover)
- **B** Always on, never optional
- **C** Off by default — only when the shift lead asks

## A7. What the tally line should read like?
- **A ★** `TICKETS THIS HANDOVER: 12  (DOWN 6 · DEGRADED 2 · UNSTABLE 1 · UP 3)`
- **B** `DOWN 6 | DEGRADED 2 | UNSTABLE 1 | UP 3` (no preamble)
- **C** Add percentages: `DOWN 6 (50%) · DEGRADED 2 (17%) …`

## A8. Engineer on shift duty — how should it appear?
- **A ★** One line: `ON SHIFT DUTY: DAY ENGINEER  → INCOMING: NIGHT ENGINEER`
- **B** Two lines (outgoing and incoming separately)
- **C** Names only, no arrow, no labels

## A9. Should the duty engineer come from the login or be typed?
- **A ★** Pre-filled from who is generating it, editable before send
- **B** Always typed manually
- **C** Auto-detected from shift roster in the app (needs a roster table)

## A10. "Very current update on link restoration" — what should it list?
- **A ★** Links restored in the last 12h with the time restored and the fix
- **B** Only links restored in this shift (last 4h day / 8h night)
- **C** Everything ever restored today, oldest first
- **D** Only restorations that had a Phoenix ticket

## A11. Default restoration window
- **A ★** 12 hours (configurable per handover)
- **B** 24 hours
- **C** Since the previous handover was generated

## A12. In the restoration list, how much detail per link?
- **A ★** `LINK NAME – UP 14:20 WAT – short cause/fix`
- **B** Just `LINK NAME – UP 14:20 WAT`
- **C** `LINK NAME – UP 14:20 WAT – cause + who fixed it + Phoenix ref`

## A13. "STILL UNRESOLVED AT HANDOVER" list at the end
- **A ★** Yes — name, state, age, escalation level, who we're waiting on
- **B** No — it's already the UNRESOLVED LINKS section
- **C** Yes, but only links older than 2 hours

## A14. Age format in that list
- **A ★** Compact (`3h`, `45m`)
- **B** Long (`3H 12M`)
- **C** Always in hours (`3.2h`)

## A15. Escalation level next to each link (L1/L2/L3/Vendor)?
- **A ★** Show it — `[L2]` after the state
- **B** Hide it in the handover; app only
- **C** Show as words: `L2 (advanced technical)`

## A16. Phoenix ticket numbers
- **A ★** Never in the handover — app only (current rule, enforced by a test)
- **B** Show them for DOWN links only
- **C** Show them all — the team wants ticket refs in the message

## A17. Who is waiting on (party)
- **A ★** In every UPDATE line: `FOLLOWING UP WITH <PARTY>`
- **B** In the UPDATE line **and** a grouped chase-list at the end
- **C** Only in the grouped chase-list

## A18. Multiple waiting parties on one link
- **A ★** Name them all: `FOLLOWING UP WITH PREC PEARL TEAM AND MR. MAYOR`
- **B** Primary party only
- **C** List each on its own line under the link

## A19. `LINKS AFFECTED` lines
- **A ★** Keep exactly as today, under the main entry
- **B** Move all affected links into one summary section at the end
- **C** Show inline on the STATUS line instead

## A20. The `|` bar convention (extra info after the update)
- **A ★** Keep it — `UPDATE: FOLLOWING UP WITH X | latest finding`
- **B** Use it only where there is a second fact
- **C** Drop it; use a second `NOTE:` line

## A21. The stale-update flag (`⚠ SAME UPDATE 18h — QUESTION IT`)
- **A ★** Off in the WhatsApp text; shown in the app and handover preview
- **B** On in the text — the next shift should see it
- **C** On only after 24h

## A22. Free notes from the outgoing engineer
- **A ★** A `NOTES` block after the summary
- **B** Mixed into the relevant link's UPDATE line
- **C** First thing in the message, before UNRESOLVED LINKS

## A23. Divider lines between links
- **A ★** Keep the long `---…` divider after each unresolved link
- **B** Only before the summary
- **C** No dividers, blank lines only

## A24. Capitalisation
- **A ★** ALL CAPS for link names and headers, sentence case for updates
- **B** ALL CAPS everywhere (current real-world sample)
- **C** Keep each engineer's own style — don't normalise

## A25. Date/time style
- **A ★** `DD/MM/YYYY` in the header, `HH:MM WAT` inside entries
- **B** `DD/MM/YYYY` only — no clock times anywhere
- **C** Add the day name: `FRI 16/10/2026`

## A26. Length discipline
- **A ★** No hard limit; summary truncates its lists at 15 each
- **B** Cap the whole message (e.g. 60 lines) and summarise the rest
- **C** Group by party instead of listing every link

## A27. Who generates it?
- **A ★** Outgoing engineer generates, incoming acknowledges on screen
- **B** Auto-generated at shift change
- **C** Either can generate; whoever is leaving

## A28. Acknowledgement
- **A ★** On-screen name + time (current rule), plus a `ACKED` marker in the app
- **B** Incoming engineer replies in the WhatsApp group
- **C** No acknowledgement, handover is just broadcast

## A29. Do we keep two text variants (clean + detailed)?
- **A ★** Yes — clean classic text and detailed+summary; switch per send
- **B** One text only (detailed)
- **C** One text only (clean)

## A30. Import tolerance
- **A ★** If engineers paste yesterday's WhatsApp text back in, ELNOC parses it
  (spacing, typos, both affected-link styles) — keep?
- **B** No — ELNOC generates the text; stop accepting pasted input
- **C** Keep, but reject anything older than 24h

---

# PART B — Details required for every escalation

An escalation is only as good as these fields. ELNOC enforces the starred ones
and warns on the rest. "Ready to hand over" = every Required field is filled.

### B1. Identity — what broke
| # | Field | Required | Notes |
|---|---|---|---|
| 1 | **Link name** | ★ Required | Must match the registry exactly |
| 2 | **Customer** | ★ Required | Auto-filled from the link |
| 3 | **Circuit ID** | ★ Required | Without it the next shift cannot trace |
| 4 | **A-end / B-end** | ★ Required | Both ends, not just one |
| 5 | **Medium / service type** | Recommended | fibre, radio, carrier… |
| 6 | **Link tier** | ★ Required | core / distribution / access / edge |
| 7 | **Affected links** | Required if >1 | Parent + backup links (LINKS AFFECTED) |

### B2. State — how bad, and since when
| # | Field | Required | Notes |
|---|---|---|---|
| 8 | **Link state** | ★ Required | DOWN / DEGRADED / UNSTABLE / UP |
| 9 | **Issue detected (when it actually occurred)** | ★ Required | Engineer-reported, may predate the alert |
| 10 | **Escalation time (system managed)** | ★ Auto | Stamped by ELNOC on create |
| 11 | **Symptom in one line** | ★ Required | What is observable, not a theory |
| 12 | **Severity** | ★ Required | critical / major / minor / info |
| 13 | **Detecting source** | ★ Auto | PRTG / Zabbix / SmartOLT / mailbox |
| 14 | **Monitoring evidence** | Required for DOWN | Sensor ID, RSL, packet loss, error count |

### B3. Ownership — who holds it now
| # | Field | Required | Notes |
|---|---|---|---|
| 15 | **Engineer on duty** | ★ Required | The named human, not "NOC" |
| 16 | **Escalation level** | ★ Required | L1 / L2 / L3 / Vendor |
| 17 | **Waiting on (party)** | ★ Required when handed over | Team **and** person name |
| 18 | **Contact channel** | Recommended | Email / WhatsApp / SMS / phone |
| 19 | **Phone of the party chased** | Required for Vendor | Vendor work needs a reachable human |
| 20 | **Time of last contact attempt** | ★ Required | Without it we can't measure chasing |

### B4. Escalation state — the chain so far
| # | Field | Required | Notes |
|---|---|---|---|
| 21 | **Current step** | ★ Auto | Step 1/2/3… |
| 22 | **Time at current step** | ★ Auto | Drives the 15-min escalation clock |
| 23 | **Acknowledged by / when** | ★ Auto if acked | Ack link in the message stops the chain |
| 24 | **Re-escalation count** | ★ Auto | Wrong-team indicator for the weekly report |

### B5. Ticket — Phoenix
| # | Field | Required | Notes |
|---|---|---|---|
| 25 | **Phoenix ticket number** | Required within 30 min of L1 | **App only — never printed in the handover** |
| 26 | **Ticket opened (date/time)** | ★ Auto | Stamped when the number is entered |
| 27 | **Who opened the ticket** | ★ Auto | From the login |
| 28 | **Engineer-declared cause** | Recommended | Distinguishes "suspected" from "confirmed" |

### B6. Technical detail (what the next shift must not re-do)
| # | Field | Required | Notes |
|---|---|---|---|
| 29 | **Checks already done** | ★ Required | Say what was ruled out, not just what passed |
| 30 | **Readings taken** | Required for optics | RSL in dBm, timestamps |
| 31 | **Working theory** | Recommended | "Suspected power outage at RC" |
| 32 | **What was NOT tried yet** | Recommended | Stops duplicate work |
| 33 | **Similar past case** | ★ Auto | Link + case number, one click |

### B7. Definition of UNSTABLE (answering A5)
A link is **UNSTABLE** when any of these is true:
- it changed state ≥ 3 times in 60 minutes (flapping), or
- monitoring reports it up while errors/loss exceed threshold, or
- an engineer marks it unstable after intermittent symptoms.

### B8. Close-out (required to resolve)
| # | Field | Required |
|---|---|---|
| 34 | Root-cause category (fixed list) | ★ Required |
| 35 | Root-cause detail | ★ Required |
| 36 | Fix applied | ★ Required |
| 37 | First thing to check next time | ★ Required |
| 38 | Restoration time (auto-stamped when set UP) | ★ Auto |
| 39 | Who confirmed restoration | ★ Required |

---

## Answer sheet

```
Q1=B  Q2=B
Q3=A (possibly keep sub-headers within the handover based on UNRESOLVED options (down, degraded, unstable) to divide the ticket updates from each other. Also, put the duration of current outage (since that particular incident occurred) beside the incident in the ticket (in hh:mm)
Q4=C  Q5=C (give tip on both causes, and challenge the officer on duty to clearly find out and choose between DEGRADED->Link is up but carrying errors/loss above threshold and UNSTABLE->Flapping: link cycles up/down, or monitoring shows repeated state changes)
Q6=A  Q7=A  Q8=A  Q9=A  Q10=A
Q11=A Q12=A Q13=A Q14=B Q15=C Q16=A Q17=A Q18=A Q19=A Q20=C
Q21=B Q22=A Q23=B Q24=A Q25=A Q26=A Q27=A Q28=A Q29=A Q30=A

Also:
- Should B5 ticket-open be enforced by ELNOC blocking handover?  Y
- Should an unresolved link with no waiting party be auto-flagged at handover?  Y
- Retention: keep handover text forever, or 12 months?  12 months

ADD OPTIONAL (BUT ADVISED) MEDIA UPLOAD FOR ALL LINKS. KEEP THE UPLOADS AS A THREAD. SO, ANY UPDATE INVOLVING POF PHYSICAL LOCATION, FIBRE TRACE, INTERFACE STATUS, DEVICE ON SMARTOLT, PRTG SENSOR IS TRACKED EFFECTIVELY. ONCE A TICKET IS 'UP', CHALLENGE THE ENGINEER TO ADD MEDIA EVIDENCE OF RESOLUTION (EITHER THE PRTG UTILISATION GRAPH, ONU UTILISATION, PHYICAL INTERFACE PICTURE, LEARN-MAC PICTURE, AMONG OTHERS.

```