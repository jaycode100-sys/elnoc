; ELNOC Quick Log — Ctrl+Shift+L desktop companion (FR-11, FR-14)
; The hotkey opens the small desktop pane (client\ELNOC_Pane.py): search the
; link quickly, confirm the card, add escalation details, submit. The pane is
; the logging part only — the server stays the brain (spec sec 11).
; Dumb by design: the pane sends NOTHING except your explicit Submit — no
; keystroke logging, no silent clipboard reads, no screenshots (sec 12).
;
; INSTALL
;   1. Install AutoHotkey v2 from https://www.autohotkey.com/  ("v2", not v1).
;      (Python 3.11+ must also be on the PC — the pane is tkinter, stdlib only,
;      no Java / no new runtime needed.)
;   2. Double-click this file. Look for the ◈ tray icon (hover = status).
;   3. Press Ctrl+Shift+L from PuTTY / WinBox / anywhere.
;   4. If nothing happens, see "IF THE HOTKEY DOES NOTHING" below.
;
; IF THE HOTKEY DOES NOTHING (most common causes in order)
;   a) This script is not running — no ◈ icon in the tray (Windows hides it
;      under the ^ overflow; check there). Double-click this file again.
;      Run it at logon: Win+R → shell:startup → drop a shortcut to this file.
;   b) Ctrl+Shift+L is taken — some OEM / graphics utilities grab it.
;      This script ALSO registers Alt+Shift+L: try that first. To change keys,
;      edit HOTKEY_MAIN / HOTKEY_FALLBACK below.
;   c) Wrong server — hover the ◈ icon: it shows the base URL. If ELNOC lives
;      elsewhere, set env var ELNOC_BASE_URL or create ELNOC_QuickLog.ini next
;      to this file containing e.g.:  base=http://noc-elnoc.local:8000
;   d) Pane won't start — right-click ◈ → "Open in browser" still works, and
;      client\ELNOC_QuickLog.bat opens the pane without AutoHotkey.
#Requires AutoHotkey v2.0
#SingleInstance Force

; ---------- config ----------
ELNOC_BASE := EnvGet("ELNOC_BASE_URL")
if (ELNOC_BASE = "") {
    try {
        ini := IniRead(A_ScriptDir "\ELNOC_QuickLog.ini", "elnoc", "base", "")
        if (ini != "")
            ELNOC_BASE := ini
    }
}
if (ELNOC_BASE = "")
    ELNOC_BASE := "http://noc-elnoc.local:8000"
ELNOC_BASE := RTrim(ELNOC_BASE, "/")

HOTKEY_MAIN := "^+l"      ; Ctrl+Shift+L — the ELNOC pane hotkey
HOTKEY_FALLBACK := "+!l"  ; Alt+Shift+L (fallback — see (b) above)

PANE := A_ScriptDir "\ELNOC_Pane.py"

; ---------- tray ----------
try {
    A_IconTip := "ELNOC ◈ Ctrl+Shift+L → desktop pane → " ELNOC_BASE
    TraySetToolTip("ELNOC Quick Log ◈ running`nCtrl+ShiftL (or Alt+Shift+L) → desktop pane`n" ELNOC_BASE)
    TrayAdd("Open Quick Log in browser", OpenInBrowser)
    TrayAdd()  ; separator
} catch {
}

; ---------- register both hotkeys, loudly if one is taken ----------
mainOk := true
fallbackOk := true
try {
    Hotkey HOTKEY_MAIN, OpenPane
} catch {
    mainOk := false
}
try {
    Hotkey HOTKEY_FALLBACK, OpenPane
} catch {
    fallbackOk := false
}
if (!mainOk && !fallbackOk) {
    MsgBox("ELNOC: neither Ctrl+Shift+L nor Alt+Shift+L could be registered.`n"
        . "Another program owns both. Edit HOTKEY_MAIN in this script and reload.", "ELNOC hotkey blocked", 16)
} else if (!mainOk) {
    try {
        TrayTip("ELNOC: Ctrl+Shift+L is taken by another app — use Alt+Shift+L.", "ELNOC Quick Log", 1)
    } catch {
    }
}

OpenPane(*) {
    global PANE
    device := ActiveTitle()
    quoted := '"' PANE '" --device "' StrReplace(device, '"', '') '"'
    ; Prefer the pane (pyw launcher → pythonw → python); browser is the fallback.
    try {
        Run('pyw ' quoted)
        return
    } catch {
    }
    try {
        Run('pythonw ' quoted)
        return
    } catch {
    }
    try {
        Run('python "' PANE '" --device "' StrReplace(device, '"', '') '"')
        return
    } catch {
    }
    OpenInBrowser()
}

OpenInBrowser(*) {
    global ELNOC_BASE
    url := ELNOC_BASE "/quicklog?device=" UrlEncode(ActiveTitle())
    try {
        Run('msedge.exe --app="' url '"')
    } catch {
        try {
            Run(url)
        } catch as err {
            MsgBox("ELNOC: could not open a browser.`n" err.Message, "ELNOC Quick Log", 16)
        }
    }
}

ActiveTitle() {
    try {
        t := WinGetTitle("A")
    } catch {
        t := ""
    }
    return Trim(t)  ; PuTTY/WinBox titles carry device/IP — pre-fill only (FR-14)
}

; Correct percent-encoding (UTF-8 bytes; unreserved chars pass through).
UrlEncode(s) {
    out := ""
    buf := Buffer(StrPut(s, "UTF-8"))
    StrPut(s, buf, "UTF-8")
    size := StrPut(s, "UTF-8") - 1  ; minus NUL terminator
    Loop size {
        b := NumGet(buf, A_Index - 1, "UChar")
        if ((b >= 0x30 && b <= 0x39) || (b >= 0x41 && b <= 0x5A) || (b >= 0x61 && b <= 0x7A) || b = 0x2D || b = 0x2E || b = 0x5F || b = 0x7E)
            out .= Chr(b)
        else
            out .= "%" Format("{:02X}", b)
    }
    return out
}
