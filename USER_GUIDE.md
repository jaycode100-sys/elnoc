# ELNOC one-page user guide (for the pilot)

1. **Log fast:** press `Ctrl+Shift+L` (fallback `Alt+Shift+L`). A small desktop pane opens:
   search the link, confirm the auto-filled card, set severity, type details, Submit.
   Under 30 s. Issue-detected time is yours to set; escalation time is system-stamped.
   Device comes from the window title — edit it. The pane needs `client\ELNOC_Pane.py`
   (Python + tkinter, already on the PC — no Java, no install) launched by the
   running `ELNOC_QuickLog.ahk` (◈ tray icon) or `ELNOC_QuickLog.bat`.
   If the hotkey does nothing: check ◈ is running, try `Alt+Shift+L`, set
   `ELNOC_BASE_URL` if the server moved. `Ctrl+K` or `/` on the web page is the last resort.
2. **Work the case:** open it from Dashboard → add notes → set `waiting_other_team` + waiting party
   when you hand to Oregun/Prec Pearl/etc. Red = stale (>2 h) — chase it.
3. **Escalate:** primary contact + steps fire automatically on critical. Recipients ack from the
   link in the message; ack stops escalation. You can add **one** watcher per case.
4. **Recoveries:** an Up event adds a note + “consider closing”. Only you close — with
   root-cause + fix + first-check-next-time (all required).
5. **Handover:** Handover → Generate → `Copy for WhatsApp` pastes today’s exact style.
   Incoming engineer Acks on screen. CSV pastes into the shift-notes sheet.
   **Import:** paste the Daily Handover WhatsApp text → ELNOC matches links, diffs
   every UPDATE, and flags anything unchanged 12h+ (repeat at 48h) before applying.
   New names can auto-create links + stub cases.
6. **Phoenix:** `Copy for Phoenix` on the case page, paste into Cloud Phoenix (official ticket).
7. **Ask (optional):** Ask tab explains RSL/fibre terms and reads `-28 dBm`-style readings.
   AI text is marked; you approve everything.
8. **Never type passwords/keys** anywhere — ELNOC blocks and warns.
9. **Escalation levels:** L1 first-line checks, L2 advanced technical, L3 senior/
   network specialists, Vendor = separate third-party path. Set it on the case;
   it shows on the weekly report.
10. **Rule of the UPDATE line:** an update that reads the same for 12 hours gets
    questioned; two days identical is a repeat. Add a fresh finding or chase —
    don't forward stale words.
