$ErrorActionPreference = 'Stop'
# Offline contract test: mock gh/git; never contact or modify GitHub.
$releaseScript = Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts/Release-Actions.ps1'
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('release-contract-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $scratch | Out-Null
New-Item -ItemType Directory -Path "$scratch/scripts" | Out-Null
Copy-Item -LiteralPath $releaseScript -Destination "$scratch/scripts/Release-Actions.ps1"
$releaseScript = "$scratch/scripts/Release-Actions.ps1"
$names = @('RELEASE_TAG','GITHUB_REPOSITORY','RUNNER_TEMP','GITHUB_OUTPUT','GITHUB_STEP_SUMMARY','RELEASE_PLATFORM','RELEASE_SHA','KEEP_DRAFT')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
$global:ReleaseContract_sha = '1234567890123456789012345678901234567890'
$global:ReleaseContract_draft = $true
$global:ReleaseContract_assetNames = @()
$global:ReleaseContract_published = $false
$global:ReleaseContract_exists = $false
$global:ReleaseContract_created = $false
$global:ReleaseContract_uploaded = $false
function gh {
    $global:LASTEXITCODE = 0
    $command = $args -join ' '
    if ($command -match '^api .*git/ref/tags/') { return (@{object=@{type='commit';sha=$global:ReleaseContract_sha}} | ConvertTo-Json -Compress) }
    if ($command -match '^release list') {
        if ($global:ReleaseContract_exists) { return '[{"tagName":"v3.4.0"}]' }
        return '[]'
    }
    if ($command -match '^release view') {
        return (@{isDraft=$global:ReleaseContract_draft;body="Source commit: $global:ReleaseContract_sha";assets=@($global:ReleaseContract_assetNames | ForEach-Object { @{name=$_;size=100} })} | ConvertTo-Json -Depth 4 -Compress)
    }
    if ($command -match '^release create') { $global:ReleaseContract_created=$true; return }
    if ($command -match '^release edit') { $global:ReleaseContract_published=$true; return }
    if ($command -match '^release upload') { $global:ReleaseContract_uploaded=$true; return }
    throw "Unexpected gh call: $command"
}
function git {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'rev-parse') { return $global:ReleaseContract_sha }
    if ($args[0] -eq 'cat-file') { return }
    throw 'Unexpected git call'
}
function Assert-Fails([scriptblock]$Action, [string]$Message) {
    $failed=$false
    try { & $Action } catch { $failed=$true }
    if (-not $failed) { throw "Expected failure: $Message" }
}
try {
    $env:RELEASE_TAG='v3.4.0'; $env:GITHUB_REPOSITORY='test/repository'
    $env:RUNNER_TEMP=$scratch; $env:GITHUB_OUTPUT=Join-Path $scratch 'outputs'
    $env:GITHUB_STEP_SUMMARY=Join-Path $scratch 'summary'
    $env:RELEASE_SHA=$global:ReleaseContract_sha; $env:KEEP_DRAFT='false'
    foreach ($platform in @('windows','linux','all')) {
        $env:RELEASE_PLATFORM=$platform
        Set-Content -LiteralPath $env:GITHUB_OUTPUT -Value ''
        & $releaseScript -Phase Prepare
        $line=Get-Content -LiteralPath $env:GITHUB_OUTPUT | Where-Object { $_.StartsWith('matrix=') }
        $matrix=$line.Substring(7) | ConvertFrom-Json
        $expected=if ($platform -eq 'all') { @('windows','linux') } else { @($platform) }
        if (($matrix.include.platform -join ',') -ne ($expected -join ',')) { throw 'Platform matrix mismatch' }
    }
    if (-not $global:ReleaseContract_created) { throw 'Draft not created' }
    $global:ReleaseContract_exists=$true
    & $releaseScript -Phase Prepare
    $env:RELEASE_TAG='v3.4.0;bad'
    Assert-Fails { & $releaseScript -Phase Prepare } 'malformed tag'
    $env:RELEASE_TAG='v3.4.0'; $env:RELEASE_PLATFORM='macos'
    Assert-Fails { & $releaseScript -Phase Prepare } 'unsupported platform'
    $env:RELEASE_PLATFORM='all'
    $global:ReleaseContract_draft=$false
    Assert-Fails { & $releaseScript -Phase Prepare } 'published release overwrite'
    $global:ReleaseContract_draft=$true
    $env:RELEASE_SHA='changed'
    Assert-Fails { & $releaseScript -Phase Finalize } 'moved tag'
    $env:RELEASE_SHA=$global:ReleaseContract_sha
    New-Item -ItemType Directory -Path "$scratch/out/release" -Force | Out-Null
    Assert-Fails { & $releaseScript -Phase Upload } 'empty upload directory'
    Set-Content -LiteralPath "$scratch/out/release/fixture.zip" -Value 'offline fixture'
    & $releaseScript -Phase Upload
    if (-not $global:ReleaseContract_uploaded) { throw 'Direct draft upload did not run' }
    $global:ReleaseContract_assetNames=@('ScanTailor-v3.4.0-windows-x64.zip','SHA256SUMS-windows.txt')
    Assert-Fails { & $releaseScript -Phase Finalize } 'missing selected Linux assets'
    $global:ReleaseContract_assetNames+=@('ScanTailor-v3.4.0-linux-x64.deb','ScanTailor-v3.4.0-linux-x64.AppImage','SHA256SUMS-linux.txt')
    $env:KEEP_DRAFT='true'
    & $releaseScript -Phase Finalize
    if ($global:ReleaseContract_published) { throw 'Draft was unexpectedly published' }
    $env:KEEP_DRAFT='false'
    & $releaseScript -Phase Finalize
    if (-not $global:ReleaseContract_published) { throw 'Complete release not published' }
    Write-Output 'Release contracts passed: 3 matrices, draft retry, input guards, published-release guard, moved tag, empty/direct upload, missing assets, draft/public finalize.'
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name,$saved[$name]) }
    Get-Variable -Name 'ReleaseContract_*' -Scope Global | Remove-Variable -Scope Global
    # Preserve scratch outputs for diagnosis; no recursive deletion needed.
}
