"""ELNOC desktop Quick-Log pane — Ctrl+Shift+L companion.

A small always-on-top pane for the logging part only: search the link quickly,
confirm the auto-filled card, add the escalation details, submit. The server
stays the brain; this pane is deliberately dumb (spec sec 11).

Why Python/tkinter and not Java: every NOC PC already runs Python for the
ELNOC tooling, and tkinter ships with it — zero new runtimes, zero installs.
A Java pane would drag in a JRE plus signing/packaging overhead for nothing
this form needs (three API calls over HTTPS).

Run:  python client/ELNOC_Pane.py [--device "PuTTY title"] [--server URL]
The AutoHotkey client (Ctrl+Shift+L) and ELNOC_QuickLog.bat launch it
automatically with the active window title as --device.

Stdlib only: tkinter + urllib + http.cookiejar. No credentials are ever
written to disk — the session cookie lives in memory for this run only.
"""
from __future__ import annotations
import argparse
import http.cookiejar
import json
import sys
import threading
import urllib.parse
import urllib.request
from datetime import datetime

ACCENT = "#e8541d"   # ember Submit, per team screenshots
INK = "#1c2333"
MUTED = "#6b7488"
BG = "#ffffff"
FIELD_BG = "#f4f6fa"


class PaneError(Exception):
    pass


# ---------------- network layer (testable without tkinter) ----------------
class PaneClient:
    def __init__(self, base: str, timeout: int = 15):
        self.base = base.rstrip("/")
        self.timeout = timeout
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def _req(self, method: str, path: str, data=None, headers=None):
        body = None
        hdrs = dict(headers or {})
        if data is not None:
            if isinstance(data, dict):
                body = urllib.parse.urlencode(data).encode()
                hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
            else:
                body = json.dumps(data).encode()
                hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, data=body, headers=hdrs, method=method)
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read().decode("utf-8", "replace")
            except Exception:
                return e.code, ""
        except Exception as e:  # server down, DNS, TLS…
            raise PaneError(f"Cannot reach {self.base}: {e}")

    def login(self, username: str, password: str) -> bool:
        status, _ = self._req("POST", "/login",
                              {"username": username, "password": password,
                               "next": "/dashboard"})
        if status in (200, 303, 302):
            s2, _ = self._req("GET", "/api/search?" + urllib.parse.urlencode({"q": "ltv8"}))
            return s2 == 200
        return False

    def search(self, q: str):
        status, text = self._req("GET", "/api/search?" + urllib.parse.urlencode({"q": q}))
        if status == 401:
            raise PaneError("Session expired — log in again.")
        if status != 200:
            raise PaneError(_server_error(text))
        try:
            return json.loads(text)
        except ValueError:
            raise PaneError("Bad response from server.")

    def link_info(self, link_id: int):
        status, text = self._req("GET", f"/api/link-info/{link_id}")
        if status == 401:
            raise PaneError("Session expired — log in again.")
        if status != 200:
            raise PaneError(_server_error(text))
        return json.loads(text)

    def submit(self, payload: dict):
        status, text = self._req("POST", "/api/quicklog", payload,
                                 {"Content-Type": "application/json"})
        try:
            doc = json.loads(text) if text else {}
        except ValueError:
            doc = {}
        if status != 200:
            raise PaneError(doc.get("error") or f"Submit failed (HTTP {status}).")
        return doc


def _server_error(text: str) -> str:
    try:
        return json.loads(text).get("error", text[:200])
    except ValueError:
        return (text or "Server error.")[:200]


def build_payload(link_id=None, customer_name="", link_name="", circuit_id="",
                  device="", symptom="", severity="major", status="open",
                  link_state="down", typed_query="", issue_detected_at="") -> dict:
    """Payload contract with POST /api/quicklog (space for tests to pin)."""
    return {"link_id": link_id, "customer_name": customer_name,
            "link_name": link_name, "circuit_id": circuit_id,
            "device": device.strip(), "symptom": symptom.strip(),
            "severity": severity, "status": status, "link_state": link_state,
            "typed_query": typed_query.strip(),
            "issue_detected_at": issue_detected_at.strip()}


def now_local_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


# ---------------- GUI ----------------
class Pane:
    def __init__(self, root, client: PaneClient, device_hint: str = ""):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = root
        self.client = client
        self.device_hint = device_hint
        self.results: list[dict] = []
        self.selected_link: dict | None = None
        self._search_after = None

        root.title("ELNOC Quick Log  ◈  Ctrl+Shift+L")
        root.geometry("410x660")
        root.minsize(380, 560)
        root.configure(bg=BG)
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass

        self._style()
        self._build_login()
        self._build_form(device_hint)
        self._show_login()

    def _style(self):
        s = self.ttk.Style()
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        s.configure("Muted.TLabel", foreground=MUTED, font=("Segoe UI", 9))
        s.configure("Title.TLabel", foreground=ACCENT, font=("Segoe UI", 16, "bold"))
        s.configure("Card.TFrame", background=FIELD_BG)
        s.configure("Accent.TButton", background=ACCENT, foreground="white",
                    font=("Segoe UI", 10, "bold"), padding=(18, 8))
        s.map("Accent.TButton", background=[("active", "#c74312")])

    def _build_login(self):
        f = self.ttk.Frame(self.root, padding=14)
        self.login_frame = f
        self.ttk.Label(f, text="ELNOC sign-in", style="Title.TLabel").pack(anchor="w")
        self.ttk.Label(f, text="Session stays in memory only — never saved.",
                       style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.e_user = self._row(f, "Username")
        self.e_pass = self._row(f, "Password", show="•")
        self.btn_login = self.ttk.Button(f, text="Connect →", style="Accent.TButton",
                                         command=self.do_login)
        self.btn_login.pack(pady=10, fill="x")
        f.pack_propagate(False)

    def _row(self, parent, label, show=None):
        self.ttk.Label(parent, text=label).pack(anchor="w", pady=(8, 2))
        e = self.ttk.Entry(parent, font=("Segoe UI", 11), show=show or "")
        e.pack(fill="x")
        return e

    def _build_form(self, device_hint):
        tk = self.tk
        f = self.ttk.Frame(self.root, padding=14)
        self.form_frame = f
        self.ttk.Label(f, text="New Escalation", style="Title.TLabel").pack(anchor="w")

        self.ttk.Label(f, text="Issue Detected  (when the issue actually occurred)").pack(anchor="w", pady=(8, 2))
        self.e_issue = self.ttk.Entry(f, font=("Segoe UI", 11))
        self.e_issue.insert(0, now_local_iso())
        self.e_issue.pack(fill="x")

        self.ttk.Label(f, text="Escalation Time  (system managed — assigned on submit)",
                       style="Muted.TLabel").pack(anchor="w", pady=(8, 2))
        self.e_esc = self.ttk.Entry(f, font=("Segoe UI", 11), state="readonly")
        self._set_esc("assigned on submit")

        self.ttk.Label(f, text="Link — search by name, alias or circuit").pack(anchor="w", pady=(8, 2))
        self.e_search = self.ttk.Entry(f, font=("Segoe UI", 12))
        self.e_search.pack(fill="x")
        self.e_search.bind("<KeyRelease>", self.on_search_key)
        self.e_search.bind("<Return>", self.on_search_enter)
        self.lb = tk.Listbox(f, height=5, font=("Segoe UI", 10), activestyle="dotbox")
        self.lb.pack(fill="x", pady=(4, 0))
        self.lb.bind("<<ListboxSelect>>", self.on_pick)
        self.lb.bind("<Return>", self.on_search_enter)

        self.lbl_card = self.ttk.Label(f, text="Pick a link — card fills in here.",
                                       style="Muted.TLabel", wraplength=370, justify="left")
        self.lbl_card.pack(anchor="w", pady=(4, 0))

        self.ttk.Label(f, text="Device  (from active window — editable)").pack(anchor="w", pady=(8, 2))
        self.e_device = self.ttk.Entry(f, font=("Segoe UI", 11))
        self.e_device.insert(0, device_hint)
        self.e_device.pack(fill="x")

        row = self.ttk.Frame(f)
        row.pack(fill="x", pady=(8, 0))
        self.ttk.Label(row, text="Severity").pack(side="left")
        self.cb_sev = self.ttk.Combobox(row, values=["critical", "major", "minor", "info"],
                                        state="readonly", width=10)
        self.cb_sev.set("major")
        self.cb_sev.pack(side="left", padx=(6, 16))
        self.ttk.Label(row, text="Link state").pack(side="left")
        self.cb_state = self.ttk.Combobox(row, values=["down", "degraded", "up"],
                                          state="readonly", width=10)
        self.cb_state.set("down")
        self.cb_state.pack(side="left", padx=(6, 0))

        self.ttk.Label(f, text="Details  (symptom, one clear line or more)").pack(anchor="w", pady=(8, 2))
        self.t_details = tk.Text(f, height=4, font=("Segoe UI", 11), wrap="word",
                                 relief="solid", borderwidth=1)
        self.t_details.pack(fill="x")

        btns = self.ttk.Frame(f)
        btns.pack(fill="x", pady=(10, 0))
        self.ttk.Button(btns, text="Cancel", command=self.root.destroy).pack(side="right", padx=(8, 0))
        self.ttk.Button(btns, text="Submit  ⏎", style="Accent.TButton",
                        command=self.do_submit).pack(side="right")

        self.lbl_result = self.ttk.Label(f, text="", style="Muted.TLabel",
                                         wraplength=370, justify="left")
        self.lbl_result.pack(anchor="w", pady=(8, 0))
        self.btn_copy = self.ttk.Button(f, text="⧉ Copy for Phoenix",
                                        command=self.do_copy_phoenix)
        self._phoenix_text = ""
        self.status = self.ttk.Label(self.root, text="Ready.",
                                     style="Muted.TLabel", anchor="w")
        self.status.pack(side="bottom", fill="x", padx=14, pady=6)

    def _set_esc(self, text):
        self.e_esc.configure(state="normal")
        self.e_esc.delete(0, "end")
        self.e_esc.insert(0, text)
        self.e_esc.configure(state="readonly")

    def _show_login(self):
        self.form_frame.pack_forget()
        self.login_frame.pack(fill="both", expand=True)
        self.e_user.focus_set()

    def _show_form(self):
        self.login_frame.pack_forget()
        self.form_frame.pack(fill="both", expand=True)
        self.e_search.focus_set()

    def say(self, msg):
        self.status.configure(text=msg)
        self.root.update_idletasks()

    # ----- actions (network off the UI thread) -----
    def do_login(self):
        u, p = self.e_user.get().strip(), self.e_pass.get()
        if not u or not p:
            self.say("Username + password required.")
            return
        self.say("Connecting…")
        self._bg(lambda: self.client.login(u, p), self._after_login, u)

    def _after_login(self, ok, user):
        if ok:
            self.say(f"Connected as {user}.  (Ctrl+Enter submits.)")
            self._show_form()
        else:
            self.say("Login failed — check credentials / server.")

    def on_search_key(self, _ev=None):
        if self._search_after:
            try:
                self.root.after_cancel(self._search_after)
            except Exception:
                pass
        self._search_after = self.root.after(220, self.do_search)

    def on_search_enter(self, _ev=None):
        if self.results:
            self.pick(0)
        return "break"

    def do_search(self):
        q = self.e_search.get().strip()
        if len(q) < 2:
            return
        self.say("Searching…")
        self._bg(lambda: self.client.search(q), self._after_search)

    def _after_search(self, results):
        self.results = results or []
        self.lb.delete(0, "end")
        for i, r in enumerate(self.results[:8]):
            self.lb.insert("end", f"{r.get('link_name')}  —  {r.get('customer')}")
        if self.results:
            self.lb.selection_set(0)
            self.say(f"{len(self.results)} match(es) — Enter selects.")
        else:
            self.say("No match — check spelling or quick-create on the web page.")

    def on_pick(self, _ev=None):
        sel = self.lb.curselection()
        if sel:
            self.pick(sel[0])

    def pick(self, idx):
        r = self.results[idx]
        self.say(f"Loading {r.get('link_name')}…")
        self._bg(lambda: self.client.link_info(r["link_id"]), self._after_info, r)

    def _after_info(self, info, r):
        self.selected_link = {"link_id": info["link_id"], "typed": self.e_search.get()}
        steps = "; ".join(f"S{s['order']}:{s['contact']}({s['wait']}m)" for s in info.get("steps", [])) or "—"
        last3 = " | ".join(f"#{c['id']} {c['symptom'][:60]}" for c in info.get("last3", [])) or "—"
        self.lbl_card.configure(
            text=f"{info['link_name']} · {info.get('customer','')} · {info.get('circuit_id','')}\n"
                 f"{info.get('a_end','')} ↔ {info.get('b_end','')} · {info.get('responsible_team','')} · {info.get('tier','')}\n"
                 f"Escalation: {steps}\nLast: {last3}")
        self.say("Card filled — type details, Ctrl+Enter to submit.")
        self.t_details.focus_set()

    def do_submit(self):
        symptom = self.t_details.get("1.0", "end").strip()
        if not symptom:
            self.say("Details required — one line is enough.")
            return
        if not self.selected_link:
            self.say("Pick a link first (search, Enter).")
            return
        payload = build_payload(
            link_id=self.selected_link["link_id"], device=self.e_device.get(),
            symptom=symptom, severity=self.cb_sev.get(), link_state=self.cb_state.get(),
            typed_query=self.selected_link.get("typed", ""),
            issue_detected_at=self.e_issue.get())
        self.say("Submitting…")
        self._bg(lambda: self.client.submit(payload), self._after_submit)

    def _after_submit(self, doc):
        self._set_esc(doc.get("escalation_time", ""))
        self._phoenix_text = doc.get("phoenix_text", "")
        self.lbl_result.configure(
            text=f"✓ Case #{doc.get('case_id')} on {doc.get('link','')} — escalated {doc.get('escalation_time','')}.")
        self.btn_copy.pack(anchor="w", pady=(6, 0))
        self.say("Logged. Copy for Phoenix, then paste into the official ticket.")
        self.t_details.delete("1.0", "end")

    def do_copy_phoenix(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self._phoenix_text)
        self.say("Phoenix text copied — paste into Cloud Phoenix.")

    def _bg(self, fn, done, *extra):
        def run():
            try:
                out = fn()
                self.root.after(0, lambda: done(out, *extra) if extra else done(out))
            except PaneError as e:
                self.root.after(0, lambda: self.say(str(e)))
            except Exception as e:  # never die silently on the night shift
                self.root.after(0, lambda: self.say(f"Error: {e}"))
        threading.Thread(target=run, daemon=True).start()


def main(argv=None):
    ap = argparse.ArgumentParser(description="ELNOC desktop Quick-Log pane")
    ap.add_argument("--device", default="", help="device hint (active window title)")
    ap.add_argument("--server", default="", help="ELNOC base URL (else ELNOC_BASE_URL)")
    args = ap.parse_args(argv)
    import os
    base = args.server or os.getenv("ELNOC_BASE_URL", "http://noc-elnoc.local:8000")
    try:
        import tkinter as tk
    except ImportError:
        print("tkinter is missing. On Windows it ships with Python; "
              "reinstall with 'tcl/tk and IDLE' enabled.", file=sys.stderr)
        return 2
    root = tk.Tk()
    Pane(root, PaneClient(base), device_hint=args.device)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
