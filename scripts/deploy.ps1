# Build the current tree locally and ship the image to a test server over SSH.
# Config lives in scripts/deploy.local.env (gitignored); copy
# scripts/deploy.local.env.example to start. Environment variables win over the file.
#
# Usage:  .\scripts\deploy.ps1 [-DryRun]
# DryRun prints every command without executing anything.

param([switch]$DryRun)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$ConfigFile = Join-Path $ScriptDir "deploy.local.env"

$Config = @{}
if (Test-Path $ConfigFile) {
    foreach ($line in Get-Content $ConfigFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $Config[$matches[1]] = ($matches[2].Trim() -replace '^["]|["]$', '')
        }
    }
}
if (-not (Test-Path $ConfigFile)) {
    Write-Warning "No scripts/deploy.local.env - copy scripts/deploy.local.env.example and set DEPLOY_HOST."
}

function Val([string]$Name, [string]$Default) {
    $envValue = (Get-Item "Env:$Name" -ErrorAction SilentlyContinue).Value
    if ($envValue) { return $envValue }
    if ($Config.ContainsKey($Name)) { return $Config[$Name] }
    return $Default
}

$DeployHost = Val "DEPLOY_HOST" ""
if (-not $DeployHost) { throw "DEPLOY_HOST is required (deploy.local.env or env var)." }

$ImageName = Val "DEPLOY_IMAGE" "sublarr"
$Overwrite = (Val "DEPLOY_OVERWRITE" "true").ToLower() -eq "true"
$Platform = Val "DEPLOY_PLATFORM" ""
$RemoteCmd = Val "DEPLOY_REMOTE_CMD" ""
$ComposeDir = Val "DEPLOY_COMPOSE_DIR" ""
if (-not $RemoteCmd -and $ComposeDir) {
    # Container pins its image ID at creation, so a loaded new image only takes
    # effect after recreation. Fixed tag (overwrite mode) means the compose file
    # never needs editing between builds.
    $RemoteCmd = "cd $ComposeDir && docker compose up -d --force-recreate"
}

$Version = "0.0.0-dev"
$VersionFile = Join-Path $RepoRoot "backend\VERSION"
if (Test-Path $VersionFile) { $Version = (Get-Content $VersionFile -Raw).Trim() }

# DEPLOY_TAG wins; OVERWRITE=true reuses one tag (old image pruned on server),
# OVERWRITE=false tags the exact short git sha so builds never collide.
$Tag = Val "DEPLOY_TAG" ""
if (-not $Tag) { if ($Overwrite) { $Tag = "dev" } else { $Tag = "sha-" + (git rev-parse --short HEAD) } }
$Image = "${ImageName}:${Tag}"

Set-Location $RepoRoot

function Run([string]$Exe, [string[]]$CmdArgs) {
    if ($DryRun) { Write-Host "DRY-RUN: $Exe $($CmdArgs -join ' ')"; return }
    & $Exe @CmdArgs
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed (exit $LASTEXITCODE)" }
}

Write-Host "=== Build $Image (VERSION=$Version$(if ($Platform) { ", platform=$Platform" })) ===" -ForegroundColor Cyan
if ($Platform) {
    Run "docker" @("buildx", "build", "--platform", $Platform, "--load", "--build-arg", "VERSION=$Version", "-t", $Image, ".")
} else {
    Run "docker" @("build", "--build-arg", "VERSION=$Version", "-t", $Image, ".")
}

# PowerShell pipes corrupt binary streams, so the tar goes through a file + scp.
$Tar = Join-Path $env:TEMP "sublarr-deploy.tar"
$RemoteTar = "/tmp/$ImageName-deploy.tar"
Run "docker" @("save", "-o", $Tar, $Image)
Write-Host "=== Ship to $DeployHost ===" -ForegroundColor Cyan
Run "scp" @($Tar, "${DeployHost}:$RemoteTar")
$LoadCmd = "docker load -i $RemoteTar && rm $RemoteTar"
if ($Overwrite) { $LoadCmd += " && docker image prune -f" }
Run "ssh" @($DeployHost, $LoadCmd)
Remove-Item $Tar -ErrorAction SilentlyContinue

if ($RemoteCmd) {
    Write-Host "=== Remote: $RemoteCmd ===" -ForegroundColor Cyan
    Run "ssh" @($DeployHost, $RemoteCmd)
}

Write-Host "Deployed $Image to $DeployHost" -ForegroundColor Green
