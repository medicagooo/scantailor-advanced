[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BuildDir,
    [Parameter(Mandatory)][string]$Destination,
    [string]$OutputDir,
    [Parameter(Mandatory)][ValidatePattern('^v\d+\.\d+\.\d+$')][string]$Tag,
    [Parameter(Mandatory)][ValidateSet('arm64','x64')][string]$Architecture,
    [Parameter(Mandatory)][string]$QtRoot,
    [Parameter(Mandatory)][string]$Python,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
if (-not $IsMacOS) { throw 'macOS deployment requires a native macOS runner' }
$source = Split-Path $PSScriptRoot -Parent
if (Test-Path -LiteralPath $Destination) { throw 'Choose a new staging directory' }
New-Item -ItemType Directory -Path $Destination | Out-Null
$app = Join-Path $Destination 'ScanTailor Advanced.app'
# ditto preserves framework symlinks and executable permissions.
ditto (Join-Path $BuildDir 'scantailor-advanced.app') $app
if ($LASTEXITCODE -ne 0) { throw 'App bundle copy failed' }
$bin = Join-Path $app 'Contents/MacOS'
Copy-Item -LiteralPath (Join-Path $BuildDir 'scantailor-cli') -Destination $bin
foreach ($file in @('process_pdf_folder.py','image_encoding.py','requirements-pdf.txt','physics-safe.json')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $bin
}
New-Item -ItemType Directory -Path "$bin/translations" -Force | Out-Null
Get-ChildItem -LiteralPath $BuildDir -Filter '*.qm' -File | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination "$bin/translations" }
$cli = Join-Path $bin 'scantailor-cli'
$platformPlugins = Join-Path $app 'Contents/PlugIns/platforms'
New-Item -ItemType Directory -Path $platformPlugins -Force | Out-Null
# CLI and headless checks require offscreen even when macdeployqt chooses Cocoa.
$qtPlugins = & "$QtRoot/bin/qmake" -query QT_INSTALL_PLUGINS
if ($LASTEXITCODE -ne 0 -or -not $qtPlugins) { throw 'Cannot locate Qt plugins' }
Copy-Item -LiteralPath (Join-Path $qtPlugins 'platforms/libqoffscreen.dylib') -Destination $platformPlugins
& "$QtRoot/bin/macdeployqt" $app "-executable=$cli" "-executable=$platformPlugins/libqoffscreen.dylib" -always-overwrite
if ($LASTEXITCODE -ne 0) { throw 'Qt macOS deployment failed' }
$nativeArch = if ($Architecture -eq 'x64') { 'x86_64' } else { 'arm64' }
& $Python "$PSScriptRoot/relocate_macos.py" --bundle $app --arch $nativeArch
if ($LASTEXITCODE -ne 0) { throw 'macOS dependency relocation/audit failed' }
# Development signature only. No Developer ID signing or notarization is claimed.
codesign --force --deep --sign - $app
if ($LASTEXITCODE -ne 0) { throw 'Ad-hoc signing failed' }
codesign --verify --deep --strict $app
if ($LASTEXITCODE -ne 0) { throw 'Bundle signature verification failed' }
$saved = @{}
foreach ($name in @('PATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','DYLD_LIBRARY_PATH','DYLD_FRAMEWORK_PATH')) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name)
    [Environment]::SetEnvironmentVariable($name, $null)
}
try {
    $env:PATH = '/usr/bin:/bin:/usr/sbin:/sbin'
    & "$PSScriptRoot/Test-CliRuntime.ps1" -Executable $cli
    & "$PSScriptRoot/Test-CliRuntime.ps1" -Executable $cli -Arguments @('--version')
    & $Python "$source/tests/macos_runtime_smoke.py" --cli $cli
    if ($LASTEXITCODE -ne 0) { throw 'Staged CLI image processing failed' }
    if ($CheckOnly) {
        foreach ($suite in @('cli_integration','image_encoding_integration')) {
            & $Python "$source/tests/$suite.py" --cli $cli
            if ($LASTEXITCODE -ne 0) { throw "Staged integration failed: $suite" }
        }
    }
} finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
}
Copy-Item -LiteralPath "$source/LICENSE" -Destination $Destination
Copy-Item -LiteralPath "$source/docs/MACOS.md" -Destination "$Destination/README-macOS.md"
Copy-Item -LiteralPath "$source/docs/THIRD-PARTY.md" -Destination $Destination
if ($CheckOnly) { return }
if (-not $OutputDir) { throw 'OutputDir is required for release archives' }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$stem = "ScanTailor-$Tag-macos-$Architecture"
ditto -c -k --sequesterRsrc --keepParent $Destination "$OutputDir/$stem.zip"
if ($LASTEXITCODE -ne 0) { throw 'macOS ZIP creation failed' }
hdiutil create -volname "ScanTailor $Tag" -srcfolder $Destination -format UDZO "$OutputDir/$stem.dmg"
if ($LASTEXITCODE -ne 0) { throw 'macOS DMG creation failed' }
hdiutil verify "$OutputDir/$stem.dmg"
if ($LASTEXITCODE -ne 0) { throw 'macOS DMG verification failed' }
