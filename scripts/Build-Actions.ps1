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
    cmake -S $source -B $build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_CLI=ON "-DBUILD_TESTS=$tests" -DENABLE_NATIVE_ARCH=OFF -DCMAKE_INSTALL_PREFIX=/usr
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
        & $env:CI_PYTHON "$source/tests/$suite.py" --cli $cli
        if ($LASTEXITCODE -ne 0) { throw "Integration tests failed: $suite" }
    }
}
