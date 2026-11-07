#NoEnv
#NoTrayIcon
#SingleInstance Force
#UseHook
#InstallKeybdHook
SetTitleMatchMode, 2

; ============================================================================
#elnocApp = ELNOC
#elnocExe = dist\ELNOC.exe
#elnocRepoDir = %A_ScriptDir%

; ============================================================================
; HOTKEYS - Global shortcuts that work from anywhere
; ============================================================================

; Ctrl+Alt+E  -> Open ELNOC command palette (quick command entry)
^!e::
    ElnocToggleWindow()
    SendInput, "^k"  ; Focus command palette in app
    return

; Ctrl+Alt+Q  -> Quick Log entry
^!q::
    ElnocToggleWindow()
    SendInput, "^+l"  ; Ctrl+Shift+L = Quick Log
    return

; Ctrl+Alt+M  -> Open MyShift
^!m::
    ElnocToggleWindow()
    SendInput, "^+m"  ; Ctrl+Shift+M = MyShift
    return

; Ctrl+Alt+P  -> Open Power log
^!p::
    ElnocToggleWindow()
    SendInput, "^+p"  ; Ctrl+Shift+P = Power log
    return

; Ctrl+Alt+A  -> Open AI Assistant
^!a::
    ElnocToggleWindow()
    SendInput, "^+a"  ; Ctrl+Shift+A = AI Assistant
    return

; Ctrl+Alt+D  -> Open Dashboard
^!d::
    ElnocToggleWindow()
    SendInput, "^+d"  ; Ctrl+Shift+D = Dashboard
    return

; Ctrl+Alt+H  -> Open Handover
^!h::
    ElnocToggleWindow()
    SendInput, "^+h"  ; Ctrl+Shift+H = Handover
    return

; Ctrl+Alt+L  -> Quick Log (duplicate for muscle memory)
^!l::
    ElnocToggleWindow()
    SendInput, "^+l"
    return

; Ctrl+Alt+X  -> EXIT ELNOC completely (only way to fully close)
^!x::
    ElnocExit()
    return

; ============================================================================
; FUNCTIONS
; ============================================================================

ElnocToggleWindow() {
    global
    WinExist, %#elnocApp%
    if (ErrorLevel) {
        ; ELNOC window exists somewhere
        WinShow
        WinActivate
        WinRestore
        return
    }
    
    ; ELNOC not running - launch it
    Run, %A_ScriptDir%\dist\ELNOC.exe,, UseErrorLevel
    if (ErrorLevel) {
        MsgBox, 16, ELNOC, Could not start ELNOC. Make sure dist\ELNOC.exe exists.
        return
    }
    WinWait, %#elnocApp%, , 10
    WinShow
    WinActivate
    WinRestore
}

ElnocExit() {
    global
    ; Close ELNOC completely
    WinClose, %#elnocApp%
    WinWaitClose, %#elnocApp%, , 5
}

; ============================================================================
; WINDOW EVENT HANDLING - Intercept close to hide instead of exit
; ============================================================================

#IfWinActive, %#elnocApp%
; Trap the close button (X) - hide instead of exiting
~!F4::  ; Also trap Alt+F4
    WinHide, %#elnocApp%
    return

#IfWinClose, %#elnocApp%
~!F4::
    WinHide, %#elnocApp%
    return

#IfWinClose
; System tray / taskbar behavior handled by Windows automatically
; Window stays in taskbar when hidden

; ============================================================================
; SYSTEM TRAY / TASKBAR BEHAVIOR
; ============================================================================

; When ELNOC window is hidden via Alt+F4 or window close X,
#IfWinExist, %#elnocApp%
~LButton up::  ; Not needed, but kept for reference
return

#IfWinExist
; Inno Setup will register this .ahk to run at startup
; When Windows starts, ELNOC will launch and sit in taskbar

; ============================================================================
; END
; ============================================================================
