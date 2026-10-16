# ELNOC Quick Log — PowerShell side of ELNOC_QuickLog.bat.
# Opens the small desktop pane (ELNOC_Pane.py) with the foreground window
# title as the device hint. Falls back to the browser Quick Log if Python
# or tkinter is unavailable. Reads nothing else.
$ErrorActionPreference = 'SilentlyContinue'
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class FG {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder t, int n);
}
'@ | Out-Null

$title = ''
$h = [FG]::GetForegroundWindow()
if ($h -ne [IntPtr]::Zero) {
  $sb = New-Object System.Text.StringBuilder 512
  if ([FG]::GetWindowText($h, $sb, $sb.Capacity) -gt 0) { $title = $sb.ToString().Trim() }
}
$base = $env:ELNOC_BASE_URL
if ([string]::IsNullOrWhiteSpace($base)) { $base = 'http://noc-elnoc.local:8000' }
$base = $base.TrimEnd('/')
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pane = Join-Path $here 'ELNOC_Pane.py'

function Open-Browser {
  $url = $base + '/quicklog?device=' + [System.Net.WebUtility]::UrlEncode($title)
  $edge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
  if (-not (Test-Path $edge)) { $edge = Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe' }
  if (Test-Path $edge) { Start-Process $edge "--app=`"$url`"" } else { Start-Process $url }
}

# Prefer the desktop pane; pythonw keeps it console-free.
$launched = $false
foreach ($py in @('pyw', 'pythonw', 'python')) {
  if (Get-Command $py -ErrorAction SilentlyContinue) {
    $env:ELNOC_BASE_URL = $base
    if ($py -eq 'pyw') { Start-Process $py "`"$pane`" --device `"$title`""; $launched = $true; break }
    Start-Process $py "`"$pane`" --device `"$title`"" -WindowStyle Hidden; $launched = $true; break
  }
}
if (-not $launched) { Open-Browser }
