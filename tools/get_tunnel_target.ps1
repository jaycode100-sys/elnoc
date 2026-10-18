# ELNOC - prints what to paste into your DNS provider.
# Run any time you need the CNAME target for your public hostname.
$ErrorActionPreference = "Continue"
$cfg = Join-Path $env:USERPROFILE ".cloudflared\config.yml"
if (Test-Path $cfg) {
  $uuid = (Select-String -Path $cfg -Pattern '^tunnel:\s*(\S+)').Matches.Groups[1].Value
  if ($uuid) {
    Write-Host ""
    Write-Host "  CNAME target (Value / Target / Alias):"
    Write-Host "      $uuid.cfargotunnel.com"
    Write-Host ""
    Write-Host "  Record type: CNAME      TTL: auto"
    Write-Host "  Example:  noc  ->  $uuid.cfargotunnel.com"
    Write-Host ""
    Write-Host "  Is the tunnel running?"
    $p = Get-Process cloudflared -ErrorAction SilentlyContinue
    if ($p) { Write-Host "    yes (PID $($p.Id -join ', '))" }
    else { Write-Host "    NO - start it with:  tools\cloudflared.exe tunnel run elnoc" }
    exit 0
  }
}
Write-Host "No tunnel config found at $cfg - run tools\setup_tunnel.ps1 first."