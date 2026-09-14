[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$QtRoot,
    [Parameter(Mandatory)][string]$BoostRoot,
    [string]$NativeRoot = 'C:\Strawberry\c',
    [Parameter(Mandatory)][string]$CompilerRoot,
    [string]$BuildDir,
    [ValidateRange(1, 32)][int]$Jobs = 4,
    [switch]$WithTests
)
$ErrorActionPreference = 'Stop'
$sourceDir = Split-Path $PSScriptRoot -Parent
if (-not $BuildDir) { $BuildDir = Join-Path $sourceDir 'build-cli' }
$qtPath = (Resolve-Path -LiteralPath $QtRoot).Path.Replace('\', '/')
$boostPath = (Resolve-Path -LiteralPath $BoostRoot).Path.Replace('\', '/')
$nativePath = (Resolve-Path -LiteralPath $NativeRoot).Path.Replace('\', '/')
$compilerPath = (Resolve-Path -LiteralPath $CompilerRoot).Path.Replace('\', '/')
foreach ($tool in @('gcc.exe', 'g++.exe')) {
    if (-not (Test-Path -LiteralPath "$compilerPath/bin/$tool")) { throw "Missing compiler: $tool" }
}
$oldPath = $env:PATH
try {
    $env:PATH = "$compilerPath/bin;$qtPath/bin;$nativePath/bin;$oldPath"
    $testSetting = if ($WithTests) { 'ON' } else { 'OFF' }
    & "$nativePath/bin/cmake.exe" -S $sourceDir -B $BuildDir -G Ninja `
        '-DCMAKE_BUILD_TYPE=Release' "-DBUILD_TESTS=$testSetting" '-DBUILD_CLI=ON' '-DENABLE_NATIVE_ARCH=OFF' `
        "-DCMAKE_C_COMPILER=$compilerPath/bin/gcc.exe" "-DCMAKE_CXX_COMPILER=$compilerPath/bin/g++.exe" `
        "-DCMAKE_MAKE_PROGRAM=$nativePath/bin/ninja.exe" "-DCMAKE_PREFIX_PATH=$qtPath;$nativePath" "-DBOOST_ROOT=$boostPath"
    if ($LASTEXITCODE -ne 0) { throw 'CMake configure failed' }
    & "$nativePath/bin/cmake.exe" --build $BuildDir --parallel $Jobs
    if ($LASTEXITCODE -ne 0) { throw 'Native build failed' }
    # Qt5 DLLs copied beside the EXE change Qt's relative plugin lookup prefix.
    # Deploy plugins before doctor/tests, just as the portable packaging path does.
    # MSYS2 suffixes Qt5 tools so they can coexist with Qt6.
    $deployQt = Join-Path $qtPath 'bin/windeployqt.exe'
    if (-not (Test-Path -LiteralPath $deployQt)) { $deployQt = Join-Path $qtPath 'bin/windeployqt-qt5.exe' }
    & $deployQt --release --no-translations --dir $BuildDir `
        (Join-Path $BuildDir 'scantailor-cli.exe') (Join-Path $BuildDir 'scantailor-advanced.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Build runtime deployment failed' }
    $offscreen = Join-Path $qtPath 'plugins/platforms/qoffscreen.dll'
    if (-not (Test-Path -LiteralPath $offscreen)) {
        $offscreen = Join-Path $qtPath 'share/qt5/plugins/platforms/qoffscreen.dll'
    }
    $platforms = Join-Path $BuildDir 'platforms'
    New-Item -ItemType Directory -Path $platforms -Force | Out-Null
    Copy-Item -LiteralPath $offscreen -Destination $platforms
    & "$PSScriptRoot/Test-CliRuntime.ps1" -Executable (Join-Path $BuildDir 'scantailor-cli.exe')
    if ($WithTests) {
        $oldPlatform = $env:QT_QPA_PLATFORM
        try {
            $env:QT_QPA_PLATFORM = 'offscreen'
            & "$nativePath/bin/ctest.exe" --test-dir $BuildDir --output-on-failure --timeout 60
            if ($LASTEXITCODE -ne 0) { throw 'C++ regression tests failed' }
        } finally { $env:QT_QPA_PLATFORM = $oldPlatform }
    }
} finally {
    $env:PATH = $oldPath
}
