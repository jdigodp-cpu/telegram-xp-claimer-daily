#requires -Version 5.1
<#
.SYNOPSIS
    Telegram XP Claimer — PowerShell runner for claim-xp-telethon.py (Method A).

.DESCRIPTION
    Installs the Telethon Python package, configures Telegram credentials, and
    runs the MTProto-based XP claimer.

    Two credential modes:
      1. Interactive first-time login (creates a reusable SESSION_STRING):
           ./claim-xp.ps1 -Interactive -ApiId <id> -ApiHash <hash> -Phone <number> -BotUsername <bot>
      2. Scheduled / CI runs using a saved session string (no login code needed):
           ./claim-xp.ps1 -SessionString $env:TG_SESSION_STRING -BotUsername <bot>

    Get API_ID and API_HASH at https://my.telegram.org/apps

.PARAMETER Config
    Path to config.json (default: config.json next to this script).
.PARAMETER Interactive
    Prompt for the login code / 2FA password interactively (first-time setup only).
.PARAMETER ApiId / ApiHash
    Telegram API credentials from my.telegram.org/apps.
.PARAMETER Phone
    Your phone number in international format, e.g. +1234567890.
.PARAMETER BotUsername
    Username of the bot that owns the mini app, without the @, e.g. xp_bot.
.PARAMETER ButtonText
    Substring to match on the button label (default: "Claim XP").
.PARAMETER ButtonIndex
    Zero-based index of the matching button to click, instead of text matching.
.PARAMETER SessionString
    Previously saved session string (recommended for GitHub Actions).
.PARAMETER Code / Password
    Login code or 2FA password (non-interactive; codes expire quickly).
.PARAMETER DryRun
    Log what would be clicked without clicking.
.PARAMETER MessageLimit
    How many recent bot messages to scan (default: 100).

.EXAMPLE
    ./claim-xp.ps1 -Interactive -ApiId 12345 -ApiHash abcdef... -Phone +15551234567 -BotUsername my_xp_bot
.EXAMPLE
    ./claim-xp.ps1 -SessionString $env:TG_SESSION_STRING -BotUsername my_xp_bot
#>
[CmdletBinding()]
param(
    [string]$Config = "config.json",
    [switch]$Interactive,
    [string]$ApiId,
    [string]$ApiHash,
    [string]$Phone,
    [string]$BotUsername,
    [string]$ButtonText = "Claim XP",
    [int]$ButtonIndex,
    [string]$SessionString,
    [string]$Code,
    [string]$Password,
    [switch]$DryRun,
    [int]$MessageLimit = 100
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pyScript = Join-Path $scriptDir "claim-xp-telethon.py"
if (!(Test-Path $pyScript)) {
    throw "Telethon script not found: $pyScript"
}

# ---------------------------------------------------------------------------
# 1. Make sure Python + Telethon are available
# ---------------------------------------------------------------------------
function Find-RealPython {
    $candidates = New-Object System.Collections.Generic.List[string]

    # 1. Anything already on PATH (but Windows ships 0-byte "store stubs" at
    #    ...\WindowsApps\python.exe that shadow real installs — skip 0-byte files).
    foreach ($name in @("python.exe", "python3.exe")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates.Add($cmd.Source) }
    }

    # 2. Common winget / user / system install locations, built with Join-Path.
    $localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $localPrograms) {
        foreach ($ver in @("Python311", "Python310", "Python312", "Python313")) {
            $candidates.Add((Join-Path $localPrograms "$ver\python.exe"))
        }
    }
    foreach ($root in @("C:\Program Files", "C:\Program Files (x86)", "C:\")) {
        foreach ($ver in @("Python311", "Python310", "Python312", "Python313")) {
            $candidates.Add((Join-Path $root "$ver\python.exe"))
        }
    }
    $candidates.Add("C:\Python311\python.exe")
    $candidates.Add("C:\Python310\python.exe")

    foreach ($cand in $candidates) {
        if (-not $cand -or !(Test-Path $cand)) { continue }
        if ((Get-Item $cand).Length -eq 0) {
            Write-Verbose "Skipping 0-byte stub: $cand"
            continue
        }
        return $cand
    }
    return $null
}

$pythonPath = Find-RealPython
if (-not $pythonPath) {
    throw "Python is required but was not found on PATH. Install python from https://python.org/ (the WindowsApps stubs are 0-byte placeholders)."
}

# Ensure pip's Scripts dir is on PATH so `python -m pip` and `pip` work.
$scriptsDir = Split-Path -Parent $pythonPath | Join-Path -ChildPath "Scripts"
if (Test-Path $scriptsDir) { $env:PATH = "$scriptsDir;$env:PATH" }

Write-Host "Using Python: $pythonPath"

Write-Host "Ensuring Telethon is installed..."
# Telethon is a hard dependency, but a pip hiccup must not abort the whole run.
try {
    & $pythonPath -m pip install -q --upgrade telethon *>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "pip install telethon reported a non-zero exit (continuing anyway)."
    }
} catch {
    Write-Warning "Could not run pip to install telethon (continuing anyway): $_"
}

# ---------------------------------------------------------------------------
# 2. Build the environment for the Python script (env vars override config.json)
# ---------------------------------------------------------------------------
function Set-TgEnv($Name, $Value) {
    # Set the TG_* env var only when a non-empty value was passed.
    if ($Value) {
        Set-Item "Env:\TG_$Name" $Value
    }
}

Set-TgEnv ApiId $ApiId
Set-TgEnv ApiHash $ApiHash
Set-TgEnv Phone $Phone
Set-TgEnv BotUsername $BotUsername
Set-TgEnv ButtonText $ButtonText
if ($PSBoundParameters.ContainsKey('ButtonIndex')) { $env:TG_BUTTON_INDEX = $ButtonIndex.ToString() }
Set-TgEnv SessionString $SessionString
Set-TgEnv Code $Code
Set-TgEnv Password $Password
if ($DryRun) { $env:TG_DRY_RUN = "1" }
$env:TG_MESSAGE_LIMIT = $MessageLimit.ToString()
# Point the script at the config file (resolved relative to this script's folder)
$configPath = Join-Path $scriptDir $Config
if (!(Test-Path $configPath)) {
    Write-Warning "Config file not found (will rely on env vars): $configPath"
}
$env:TG_CONFIG_PATH = $configPath

# ---------------------------------------------------------------------------
# 3. Run the Telethon claimer
# ---------------------------------------------------------------------------
$args = @($pyScript)
if ($Interactive) { $args += "--interactive" }
if ($configPath) { $args += $configPath }

Write-Host "Running Telegram XP claimer..."
& $pythonPath @args
$exit = $LASTEXITCODE

switch ($exit) {
    0  { Write-Host "SUCCESS: XP claim processed." -ForegroundColor Green }
    1  { Write-Warning "No matching button found. Check BOT_USERNAME / BUTTON_TEXT (see reverse-engineer.ps1 for Method B)." }
    2  { Write-Error "Configuration error. Set TG_API_ID / TG_API_HASH (from https://my.telegram.org/apps)." }
    130 { Write-Host "Interrupted by user." }
    default { Write-Error "Telethon script exited with code $exit." }
}

exit $exit
