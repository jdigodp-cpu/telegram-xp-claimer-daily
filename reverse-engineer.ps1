#requires -Version 5.1
<#
.SYNOPSIS
    Telegram XP Claimer ? Method B: reverse-engineer the mini app's HTTP request.
#>
[CmdletBinding()]
param(
    [string]$Url,
    [string]$Body,
    [string]$InitData,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Resolve parameters: explicit param > env var > captured default
# ---------------------------------------------------------------------------
$claimUrl = $Url
if (-not $claimUrl) { $claimUrl = $env:TG_CLAIM_URL }
if (-not $claimUrl) { $claimUrl = "https://app.piratezparty.com/api/daily" }

$claimBody = $Body
if (-not $claimBody) { $claimBody = $env:TG_CLAIM_BODY }
if (-not $claimBody) { $claimBody = "{}" }

$claimInitData = $InitData
if (-not $claimInitData) { $claimInitData = $env:TG_INIT_DATA }

$dryRun = $DryRun.IsPresent -or ($env:TG_DRY_RUN -eq "1")

# ---------------------------------------------------------------------------
# Build headers
# ---------------------------------------------------------------------------
$headers = @{}
$headers["Content-Type"] = "application/json"
$headers["Origin"] = "https://app.piratezparty.com"
$headers["Referer"] = "https://app.piratezparty.com/"
$headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
$headers["Accept"] = "*/*"
$headers["Accept-Language"] = "en-US,en;q=0.9"
$headers["Sec-Fetch-Dest"] = "empty"
$headers["Sec-Fetch-Mode"] = "cors"
$headers["Sec-Fetch-Site"] = "same-origin"

if ($claimInitData) {
    $headers["X-Telegram-Init-Data"] = $claimInitData
    Write-Host "initData attached to request headers." -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------
Write-Host "Method B ? replaying mini app HTTP request"
Write-Host "URL: $claimUrl"
Write-Host "Body: $claimBody"

if ($dryRun) {
    Write-Host "[DRY-RUN] Would invoke: Invoke-RestMethod -Uri $claimUrl -Method POST -Headers $headers -Body $claimBody"
    exit 0
}

try {
    $response = Invoke-RestMethod -Uri $claimUrl -Method POST -Headers $headers -Body $claimBody -ContentType "application/json" -ErrorAction Stop
    Write-Host "SUCCESS: server responded:" -ForegroundColor Green
    $response | ConvertTo-Json -Depth 3
}
catch {
    $errMsg = $_.Exception.Message
    Write-Error $errMsg
    if ($_.ErrorDetails) { $_.ErrorDetails | ForEach-Object { Write-Warning $_ } }
    exit 1
}
