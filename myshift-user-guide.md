# MyShift User Guide

*For NOC engineers and team leads using ELNOC. Covers the MyShift console as it works today, plus the close-gate rules you're expected to follow.*

---

## What is MyShift?

MyShift is your personal shift console inside ELNOC. It answers one question: **"What happened on my shift, and did I close it out properly?"**

You use it to:

- **Log what happened** during your shift — events, handovers, calls you made
- **Paste WhatsApp escalations** so chat history becomes a real record
- **Log power** (light, generators, inverter, solar, power tank) — required **before your shift can close**
- **Close your shift** once the power report is in

**Where:** open ELNOC, log in, then go to **MyShift** (`/myshift`).

---

## Shift basics

- **Day shift:** 07:00 – 19:00 · **Night shift:** 19:00 – 07:00 (Lagos time)
- The shift label is chosen automatically from the current time
- Dates are shown as **DD/MM/YYYY**, in Lagos time
- Every note belongs to **you** — other engineers (and you on other shifts) have their own lists. Nobody edits your notes but you.

---

## Logging a shift note

1. Open **MyShift**.
2. Check the header: it shows the **date**, your **shift** (day/night), and your username.
3. Fill in the form:
   - **Engineer notes** — what happened. E.g. *"Handed over LTV8 Ikeja-RC to night team. Prec Pearl link still down."*
   - **Extra information** *(optional)* — context, who you spoke to, next steps
   - **Power status** *(optional)* — a one-line summary; full details go in the Power log
4. Use a **quick chip** if it fits ("Power restored", "Gen on battery", "Handover done") — it fills the note for you.
5. Click **Save shift note**.

Your note appears in the list below, tagged with your shift and the time.

**Tips**

- Log as you go rather than at 18:55 — the timestamp is what makes the record useful.
- One event per note is better than one wall of text at shift end.

---

## Logging from WhatsApp

When an escalation or update lands in WhatsApp:

1. Copy the message text (or the whole conversation).
2. Open **MyShift** → **WhatsApp paste-in**.
3. Paste and click **Log from WhatsApp**.

ELNOC records it as a shift note, tagged as a WhatsApp paste. It also tries to pull out the **time** and any **battery percentage** from the text.

> ⚠ Note: the parser grabs the *first* percentage it finds in the paste. If your text contains other numbers with `%` (e.g. packet loss), check the result reads sensibly.

---

## Logging power — the shift-close requirement

**Your shift cannot close until a power report exists for today.** This is the close gate.

1. Go to the **Power** page (`/power`).
2. Add an entry any way that's convenient:
   - **Natural language** — type what happened, e.g. *"Generator on at 6:15 PM, inverter 68%"* and let it parse
   - **Manual form** — pick the activity, time, and battery level
3. One report for the date is enough to satisfy the gate, but log each significant power event (mains restored, generator changeover, low inverter) — the daily history is what the team reviews.

**Power sources:** light · big generator · small generator · inverter · solar · power tank.

---

## Closing your shift

1. Before you leave, open **MyShift**.
2. Look at the **gate banner** at the top:
   - ✅ *"Power report logged — shift can close."* — you're good
   - ⚠ *"Power report required before shift close. Log power first."* — go to the Power page, log it, come back
3. The sidebar shows your shift status: power report ✓/⚠ and your notes for the day.
4. Once the gate is green, you're closed out for the shift.

> ⚠ **Current version, know this:** the gate *tells* you the state but does not yet hard-block you — the requirement is on **you** to honor it. An enforced close (with audit record and handover stamp) is planned; until then, treat a red banner as "do not leave".

**Troubleshooting close**

| Symptom | Fix |
| --- | --- |
| Banner stays red | No power report for today's date exists — log one on `/power`, then refresh |
| Logged power, still red | Check the date: the report must match today's date shown on MyShift |
| Can't see the status panel | On narrow screens/phones the sidebar is hidden — use a wider window or desktop |

---

## Viewing and finding your notes

- Use the **date picker** to look at any past date.
- Notes are grouped per date and shift, newest first.
- Each note shows: shift tag, time, engineer, the note, extra info, and power status.

---

## For team leads

- **Power** (`/power`) shows every report for a date and recent dates — use it to review the day-duty power log at a glance.
- Each engineer's notes are theirs; there is no cross-engineer view yet (planned).
- During pilot reviews, check that a power report exists for **every** date in the window — that's the gate's paper trail.

---

## Do's and don'ts

**Do**
- Log notes as events happen, not from memory at shift end
- Log every significant power change on the Power page — not just one per day
- Paste important WhatsApp escalations into MyShift so they survive chat deletion

**Don't**
- Don't put secrets, credentials, or customer personal data in notes — notes are a team record
- Don't close your shift with a red banner
- Don't rely on the note's auto battery % without checking it matched the real value

---

## FAQ

**My note didn't save.**
All three fields were probably empty — the server rejects a completely empty note ("nothing to save"). Put at least something in notes, extra info, or power status.

**I wrote my note at 19:05 but it filed as "night".**
The shift label follows the current clock. Note the time in the text ("final note for day shift") — a user-choosable shift label is planned.

**I can't edit or delete a note.**
Current version has no edit/delete — planned as an improvement. If it matters, add a follow-up note correcting the earlier one.

**Why can't I see notes from the other engineer on shift?**
By design — MyShift is per-engineer. The handover is where shifts meet.

**The WhatsApp paste saved weird battery info.**
The parser takes the first `%` it finds. Edit-free workaround: paste the power part into the Power page's natural-language box instead, and only the narrative into MyShift.

**Where do closed shifts go?**
Today, closing is implied (gate green, you leave). The plan: closing writes an audit record and appends a shift summary to the handover document automatically.

---

*MyShift is part of [ELNOC](https://github.com/jaycode100-sys/elnoc) — the team-facing working twin of Phoenix. Questions or bugs: raise them with the ELNOC admin on your team.*