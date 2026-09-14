[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
# Release-only helper. Shared native build produces build-actions; output names
# are checked by Release-Actions.ps1 before a draft can be published.
$source = Split-Path $PSScriptRoot -Parent
$build = Join-Path $source 'build-actions'
$out = Join-Path $source 'out/release'
$tag = $env:RELEASE_TAG
if ($tag -cnotmatch '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') { throw 'Invalid version tag' }
New-Item -ItemType Directory -Path $out -Force | Out-Null
if ($IsWindows) {
    $platform = 'windows'
    $root = $env:NATIVE_CI_ROOT
    $embed = Join-Path $env:RUNNER_TEMP 'python-3.12.10-embed-amd64.zip'
    Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' -OutFile $embed
    $packages = Join-Path $env:RUNNER_TEMP 'release-python-packages'
    & $env:CI_PYTHON -m pip install --only-binary=:all: --target $packages -r "$PSScriptRoot/requirements-pdf.txt"
    if ($LASTEXITCODE -ne 0) { throw 'Bundled Python dependencies failed' }
    $package = Join-Path $source "out/ScanTailor-$tag-windows-x64"
    & "$PSScriptRoot/Package-Windows.ps1" -BuildDir $build -Destination $package -QtRoot $root -CompilerRoot $root -NativeRoot $root -PythonEmbedZip $embed -PythonPackagesRoot $packages
    Compress-Archive -LiteralPath $package -DestinationPath "$out/ScanTailor-$tag-windows-x64.zip"
} elseif ($IsMacOS) {
    $arch = if ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture -eq 'Arm64') { 'arm64' } else { 'x64' }
    $platform = "macos-$arch"
    & "$PSScriptRoot/Package-MacOS.ps1" -BuildDir $build -Destination (Join-Path $source "out/ScanTailor-$tag-$platform") -OutputDir $out -Tag $tag -Architecture $arch -QtRoot $env:MACOS_QT_ROOT -Python $env:CI_PYTHON
} elseif ($IsLinux) {
    $platform = 'linux'
    Push-Location $build
    try {
        cpack -G DEB -D CPACK_DEBIAN_PACKAGE_SHLIBDEPS=ON -D CPACK_DEBIAN_PACKAGE_MAINTAINER=ScanTailor -D "CPACK_PACKAGE_FILE_NAME=ScanTailor-$tag-linux-x64" -B $out
        if ($LASTEXITCODE -ne 0) { throw 'DEB packaging failed' }
        $appDir = Join-Path $build 'AppDir'
        $env:DESTDIR = $appDir
        try {
            cmake --install $build
            if ($LASTEXITCODE -ne 0) { throw 'AppDir install failed' }
        } finally { Remove-Item Env:DESTDIR }
        foreach ($tool in @('linuxdeploy', 'linuxdeploy-plugin-qt')) {
            $file = "$tool-x86_64.AppImage"
            Invoke-WebRequest "https://github.com/linuxdeploy/$tool/releases/download/continuous/$file" -OutFile $file
            chmod +x $file
            if ($LASTEXITCODE -ne 0) { throw 'AppImage tool permission failed' }
        }
        $env:APPIMAGE_EXTRACT_AND_RUN = '1'
        $env:QMAKE = '/usr/bin/qmake'
        $env:VERSION = $tag
        $env:OUTPUT = "$out/ScanTailor-$tag-linux-x64.AppImage"
        & ./linuxdeploy-x86_64.AppImage --appdir $appDir --plugin qt --executable "$appDir/usr/bin/scantailor-advanced" --executable "$appDir/usr/bin/scantailor-cli" --output appimage
        if ($LASTEXITCODE -ne 0) { throw 'AppImage packaging failed' }
    } finally { Pop-Location }
} else { throw 'Unsupported packaging OS' }
$assets = @(Get-ChildItem -LiteralPath $out -File | Where-Object { $_.Extension -in @('.zip', '.deb', '.AppImage', '.dmg') })
$expectedCount = if ($IsWindows) { 1 } else { 2 }
if ($assets.Count -ne $expectedCount -or @($assets | Where-Object Length -eq 0).Count) { throw 'Missing or empty package outputs' }
$assets | ForEach-Object { "$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant())  $($_.Name)" } |
    Set-Content -LiteralPath "$out/SHA256SUMS-$platform.txt" -Encoding ascii
