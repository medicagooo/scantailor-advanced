[CmdletBinding()]
param(
    [string]$PdfDir,
    [string]$ScanTailorDir,
    [string]$OutputDir,
    [string]$PythonExe,
    [ValidateRange(72, 1200)][int]$Dpi = 300,
    [ValidateRange(1, 16)][int]$Jobs = 1,
    [ValidateSet('original', 'processed')][string]$PageSize = 'original',
    [string]$Config,
    [switch]$Resume,
    [switch]$Overwrite,
    [switch]$Recursive
)
$ErrorActionPreference = 'Stop'
if (-not $PdfDir) { $PdfDir = Read-Host 'PDF folder' }
if (-not $ScanTailorDir) { $ScanTailorDir = Read-Host 'Folder containing scantailor-cli.exe' }
$resolvedPdf = (Resolve-Path -LiteralPath $PdfDir).Path
$resolvedScan = (Resolve-Path -LiteralPath $ScanTailorDir).Path
$cliExe = Join-Path $resolvedScan 'scantailor-cli.exe'
if (-not (Test-Path -LiteralPath $cliExe -PathType Leaf)) {
    throw "CLI is not present: $cliExe. The original GUI-only package cannot run this script."
}
if (-not $PythonExe) {
    $bundledPython = Join-Path $resolvedScan 'python/python.exe'
    if (Test-Path -LiteralPath $bundledPython) { $PythonExe = $bundledPython }
    else { $PythonExe = (Get-Command python -ErrorAction Stop).Source }
}
$arguments = @((Join-Path $PSScriptRoot 'process_pdf_folder.py'), '--pdf-dir', $resolvedPdf,
    '--cli', $cliExe, '--dpi', "$Dpi", '--jobs', "$Jobs", '--page-size', $PageSize)
if ($OutputDir) { $arguments += @('--output-dir', $OutputDir) }
if ($Config) { $arguments += @('--config', (Resolve-Path -LiteralPath $Config).Path) }
if ($Resume) { $arguments += '--resume' }
if ($Overwrite) { $arguments += '--overwrite' }
if ($Recursive) { $arguments += '--recursive' }
& $PythonExe @arguments
$resultCode = $LASTEXITCODE
if ($resultCode -notin @(0, 1, 130)) { throw "PDF processing failed (exit $resultCode)." }
exit $resultCode
