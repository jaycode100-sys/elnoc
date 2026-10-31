# ELNOC code signing helper
# Run in PowerShell from repo root:
#   .\sign_elnoc.ps1                     # sign dist\ELNOC.exe + Output\ELNOC-Setup.exe
#   .\sign_elnoc.ps1 -Files a.exe,b.exe  # sign specific files
#   .\sign_elnoc.ps1 -Trust              # trust the self-signed cert on THIS machine (removes 'unknown publisher')
#   .\sign_elnoc.ps1 -Show               # show signature status of built binaries
#
# Build pipeline: build_elnoc_installer.ps1 calls this automatically after each build.
#
# NOTE: self-signed cert = signs binaries, but strangers will still see the
# SmartScreen prompt unless they run `.\sign_elnoc.ps1 -Trust` (or double-click
# signing\ELNOC.cer -> Install Certificate -> Current User). For real mass
# distribution trust, use Azure Trusted Sign or a commercial code-signing cert.

param(
    [string[]]$Files,
    [switch]$Trust,
    [switch]$Show,
    [switch]$SkipTimestamp
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Thumbprint = "49D43ED31D7D67AE2781C207BE4851A45EF6B8F2"

# --- Locate the cert; recreate + re-trust flows are documented if it's gone ---
function Get-ElnocCert {
    $c = Get-ChildItem "Cert:\CurrentUser\My\$Thumbprint" -ErrorAction SilentlyContinue
    if (-not $c) {
        Write-Host "Cert $Thumbprint not found in CurrentUser\My. Restore it:" -ForegroundColor Red
        Write-Host "  Import-PfxCertificate -FilePath .\signing\ELNOC-signing.pfx -Password (Read-Host -AsSecureString) -CertStoreLocation Cert:\CurrentUser\My"
        Write-Host "  (PFX password is in signing\ELNOC-signing.pfx.README.txt)"
        exit 1
    }
    return $c
}

function Show-Signature($path) {
    if (-not (Test-Path $path)) { Write-Output "$path  (missing)"; return }
    $sig = Get-AuthenticodeSignature $path
    $name = Split-Path $path -Leaf
    if ($sig.Status -in @('Valid')) {
        Write-Output "$name  SIGNED  ($($sig.SignerCertificate.Subject) | timestamped: $($null -ne $sig.TimeStamperCertificate))"
    } elseif ($sig.Status -eq 'NotSigned') {
        Write-Output "$name  NOT SIGNED"
    } else {
        Write-Output "$name  $($sig.Status)  ($($sig.StatusMessage))"
    }
}

if ($Show) {
    Show-Signature "dist\ELNOC.exe"
    Show-Signature "Output\ELNOC-Setup.exe"
    return
}

# --- Trust flow: put the self-signed cert in CurrentUser Trusted Root,
#     so Windows shows ELNOC as a verified publisher on THIS machine ---
if ($Trust) {
    $cert = Get-ElnocCert
    # self-signed certs must be trusted roots to verify; TrustedPublisher removes the extra prompt
    Import-Certificate -FilePath "signing\ELNOC.cer" -CertStoreLocation "Cert:\CurrentUser\Root" | Out-Null
    Import-Certificate -FilePath "signing\ELNOC.cer" -CertStoreLocation "Cert:\CurrentUser\TrustedPublisher" | Out-Null
    Write-Host "Cert imported into CurrentUser Root + TrustedPublisher. ELNOC binaries now verify on this machine." -ForegroundColor Green
    Show-Signature "Output\ELNOC-Setup.exe"
    return
}

# --- Sign flow ---
if (-not $Files) { $Files = @("dist\ELNOC.exe", "Output\ELNOC-Setup.exe") }
$cert = Get-ElnocCert
$signArgs = @{
    Certificate      = $cert
    HashAlgorithm    = "SHA256"
    IncludeChain     = "All"
}
if (-not $SkipTimestamp) {
    $signArgs.TimestampServer = "http://timestamp.digicert.com"
}

foreach ($f in $Files) {
    if (-not (Test-Path $f)) {
        Write-Host "SKIP (missing): $f" -ForegroundColor Yellow
        continue
    }
    try {
        Set-AuthenticodeSignature @signArgs -FilePath $f -ErrorAction Stop | Out-Null
        Show-Signature $f
    } catch {
        Write-Host "SIGN FAILED for $f : $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "(no network for timestamping? try: .\sign_elnoc.ps1 -Files $f -SkipTimestamp)" -ForegroundColor Yellow
    }
}
