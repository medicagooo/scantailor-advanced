[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BuildDir,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][string]$QtRoot,
    [Parameter(Mandatory)][string]$CompilerRoot,
    [string]$NativeRoot = 'C:\Strawberry\c',
    [string]$PythonEmbedZip,
    [string]$PythonPackagesRoot
)
$ErrorActionPreference = 'Stop'
$sourceDir = Split-Path $PSScriptRoot -Parent
$buildPath = (Resolve-Path -LiteralPath $BuildDir).Path
$qtPath = (Resolve-Path -LiteralPath $QtRoot).Path
$compilerPath = (Resolve-Path -LiteralPath $CompilerRoot).Path
$nativePath = (Resolve-Path -LiteralPath $NativeRoot).Path
$packagePath = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $packagePath) { throw 'Choose a new destination directory; packaging never replaces an existing package.' }
New-Item -ItemType Directory -Path $packagePath | Out-Null
foreach ($name in @('scantailor-cli.exe', 'scantailor-advanced.exe')) {
    Copy-Item -LiteralPath (Join-Path $buildPath $name) -Destination $packagePath
}
$oldPath = $env:PATH
try {
    $env:PATH = "$compilerPath/bin;$qtPath/bin;$nativePath/bin;$oldPath"
    & (Join-Path $qtPath 'bin/windeployqt.exe') --release --no-translations --dir $packagePath `
        (Join-Path $packagePath 'scantailor-cli.exe') (Join-Path $packagePath 'scantailor-advanced.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Qt deployment failed' }
    Copy-Item -LiteralPath (Join-Path $qtPath 'plugins/platforms/qoffscreen.dll') -Destination (Join-Path $packagePath 'platforms')
    # Follow PE imports so libtiff's compression DLLs are included as well.
    # Never copy system DLLs or resolve a library from an unrelated PATH entry.
    $queue = [Collections.Generic.Queue[string]]::new()
    Get-ChildItem -LiteralPath $packagePath -Recurse -File | Where-Object { $_.Extension -in @('.exe', '.dll') } |
        ForEach-Object { $queue.Enqueue($_.FullName) }
    $visited = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    while ($queue.Count -gt 0) {
        $binary = $queue.Dequeue()
        if (-not $visited.Add($binary)) { continue }
        $imports = & (Join-Path $compilerPath 'bin/objdump.exe') -p $binary
        if ($LASTEXITCODE -ne 0) { throw "Cannot inspect $binary" }
        foreach ($line in $imports) {
            if ($line -notmatch 'DLL Name:\s*(\S+)') { continue }
            $dllName = $Matches[1]
            $target = Join-Path $packagePath $dllName
            if (Test-Path -LiteralPath $target) { $queue.Enqueue($target); continue }
            if ($dllName -match '^(api-ms-|ext-ms-)' -or (Test-Path -LiteralPath (Join-Path "$env:SystemRoot/System32" $dllName))) { continue }
            $found = $null
            foreach ($folder in @("$compilerPath/bin", "$qtPath/bin", "$nativePath/bin")) {
                $candidate = Join-Path $folder $dllName
                if (Test-Path -LiteralPath $candidate) { $found = $candidate; break }
            }
            if (-not $found) { throw "Unresolved runtime dependency: $dllName ($binary)" }
            Copy-Item -LiteralPath $found -Destination $target
            $queue.Enqueue($target)
        }
    }
} finally { $env:PATH = $oldPath }
New-Item -ItemType Directory -Path (Join-Path $packagePath 'translations') | Out-Null
Get-ChildItem -LiteralPath $buildPath -Filter 'scantailor-advanced_*.qm' |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $packagePath 'translations') }
foreach ($name in @('Process-PdfFolder.ps1', 'process_pdf_folder.py', 'requirements-pdf.txt', 'physics-safe.json')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $packagePath
}
Copy-Item -LiteralPath (Join-Path $sourceDir 'LICENSE') -Destination $packagePath
Copy-Item -LiteralPath (Join-Path $sourceDir 'docs/CLI.md') -Destination (Join-Path $packagePath 'README-CLI.md')
Copy-Item -LiteralPath (Join-Path $sourceDir 'docs/CLI-COVERAGE.md') -Destination $packagePath
Copy-Item -LiteralPath (Join-Path $sourceDir 'docs/THIRD-PARTY.md') -Destination $packagePath
if ($PythonEmbedZip -or $PythonPackagesRoot) {
    if (-not ($PythonEmbedZip -and $PythonPackagesRoot)) { throw 'Supply both PythonEmbedZip and PythonPackagesRoot.' }
    $pythonPath = Join-Path $packagePath 'python'
    Expand-Archive -LiteralPath $PythonEmbedZip -DestinationPath $pythonPath
    $sitePath = Join-Path $pythonPath 'Lib/site-packages'
    New-Item -ItemType Directory -Path $sitePath -Force | Out-Null
    foreach ($name in @('pymupdf', 'PIL')) {
        Copy-Item -LiteralPath (Join-Path $PythonPackagesRoot $name) -Destination $sitePath -Recurse
    }
    Get-ChildItem -LiteralPath $PythonPackagesRoot -Directory |
        Where-Object { $_.Name -match '^(pymupdf|pillow)([-.]|\.libs)' } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $sitePath -Recurse }
    @('python312.zip', '.', 'Lib/site-packages') | Set-Content -LiteralPath (Join-Path $pythonPath 'python312._pth') -Encoding ascii
    & (Join-Path $pythonPath 'python.exe') -c 'import pymupdf; from PIL import Image; print(pymupdf.VersionBind)'
    if ($LASTEXITCODE -ne 0) { throw 'Bundled Python validation failed' }
}
$originalSearchPath = $env:PATH
try {
    # Validate using only Windows system paths, not the development environment.
    $env:PATH = "$env:SystemRoot/System32;$env:SystemRoot"
    & (Join-Path $packagePath 'scantailor-cli.exe') doctor
    if ($LASTEXITCODE -ne 0) { throw 'Packaged CLI runtime validation failed' }
} finally { $env:PATH = $originalSearchPath }
$files = Get-ChildItem -LiteralPath $packagePath -Recurse -File | ForEach-Object {
    @{path=[IO.Path]::GetRelativePath($packagePath, $_.FullName);sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
}
@{schema_version=1;built_at=(Get-Date).ToString('o');files=@($files)} | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $packagePath 'manifest.json')
Write-Output "Package ready: $packagePath"
