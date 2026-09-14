[CmdletBinding()]
param([switch]$Check)
$ErrorActionPreference = 'Stop'
# Called by native-build/action.yml. CI tests; Release only compiles for packaging.
$source = Split-Path $PSScriptRoot -Parent
$build = Join-Path $source 'build-actions'
$env:QT_QPA_PLATFORM = 'offscreen'
if ($IsWindows) {
    $root = $env:NATIVE_CI_ROOT
    $env:PATH = "$root/bin;$env:PATH"
    & "$PSScriptRoot/Build-Windows.ps1" -QtRoot $root -BoostRoot $root -NativeRoot $root -CompilerRoot $root -BuildDir $build -WithTests:$Check
} else {
    $tests = if ($Check) { 'ON' } else { 'OFF' }
    $platformOptions = @('-DCMAKE_INSTALL_PREFIX=/usr')
    if ($IsMacOS) {
        $architecture = if ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture -eq 'Arm64') { 'arm64' } else { 'x86_64' }
        # Homebrew bottles target the runner OS; do not promise older macOS support.
        $platformOptions = @("-DCMAKE_PREFIX_PATH=$env:MACOS_QT_ROOT;$env:MACOS_BREW_ROOT", "-DCMAKE_OSX_ARCHITECTURES=$architecture", '-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0', '-DPORTABLE_VERSION=OFF', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5')
    }
    cmake -S $source -B $build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_CLI=ON "-DBUILD_TESTS=$tests" -DENABLE_NATIVE_ARCH=OFF @platformOptions
    if ($LASTEXITCODE -ne 0) { throw 'Configure failed' }
    cmake --build $build --parallel 4
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    & "$build/scantailor-cli" doctor
    if ($LASTEXITCODE -ne 0) { throw 'CLI doctor failed' }
    if ($Check) {
        ctest --test-dir $build --output-on-failure --timeout 60 --no-tests=error
        if ($LASTEXITCODE -ne 0) { throw 'C++ tests failed' }
    }
}
if ($Check) {
    # MenuLauncher resolves "python" on PATH. Keep it on the same interpreter as
    # the installed PDF dependencies, ahead of MSYS2's optional debugger Python.
    $env:PATH = (Split-Path $env:CI_PYTHON -Parent) + [IO.Path]::PathSeparator + $env:PATH
    & $env:CI_PYTHON -m pip install -r "$PSScriptRoot/requirements-pdf.txt"
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency install failed' }
    & $env:CI_PYTHON "$source/tests/pdf_lock_contract.py"
    if ($LASTEXITCODE -ne 0) { throw 'PDF output lock contract failed' }
    $cli = Join-Path $build $(if ($IsWindows) { 'scantailor-cli.exe' } else { 'scantailor-cli' })
    $suites = @('cli_integration', 'cli_full_integration', 'image_encoding_integration')
    if ($IsWindows) { $suites += @('menu_integration', 'workbench_integration', 'completion_ui_integration', 'task_reuse_integration', 'language_integration') }
    foreach ($suite in $suites) {
        $suiteOptions = @()
        if ($IsMacOS -and $suite -eq 'cli_full_integration') { $suiteOptions = @('--gui', "$build/scantailor-gui-roundtrip") }
        & $env:CI_PYTHON "$source/tests/$suite.py" --cli $cli @suiteOptions
        if ($LASTEXITCODE -ne 0) { throw "Integration tests failed: $suite" }
    }
    if ($IsMacOS) {
        $version = [regex]::Match((Get-Content -LiteralPath "$source/version.h.in" -Raw), '(?m)^#define VERSION "([^"]+)"').Groups[1].Value
        $arch = if ($architecture -eq 'arm64') { 'arm64' } else { 'x64' }
        & "$PSScriptRoot/Package-MacOS.ps1" -BuildDir $build -Destination (Join-Path $env:RUNNER_TEMP ('macos-runtime-' + [guid]::NewGuid())) -Tag "v$version" -Architecture $arch -QtRoot $env:MACOS_QT_ROOT -Python $env:CI_PYTHON -CheckOnly
    }
}
