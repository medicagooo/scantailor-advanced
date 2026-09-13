[CmdletBinding()]
param([Parameter(Mandatory)][string]$ToolDir)
$ErrorActionPreference = 'Stop'
$toolPath = (Resolve-Path -LiteralPath $ToolDir).Path
$pythonPath = Join-Path $toolPath 'python/python.exe'
$testRoot = Join-Path (Split-Path $PSScriptRoot -Parent) ('build-native/encoding-powershell-' + [guid]::NewGuid().ToString('N'))
$pdfDir = Join-Path $testRoot '输入 PDF'
New-Item -ItemType Directory -Path $pdfDir -Force | Out-Null
$pdf = Join-Path $pdfDir 'sample.pdf'
& $pythonPath -c 'import pymupdf,sys; doc=pymupdf.open(); page=doc.new_page(width=240,height=320); page.insert_text((20,40),"PowerShell encoding"); doc.save(sys.argv[1]); doc.close()' $pdf
if ($LASTEXITCODE -ne 0) { throw 'fixture failed' }
$originalHash = (Get-FileHash -LiteralPath $pdf -Algorithm SHA256).Hash
$config = Join-Path $testRoot 'settings.json'
'{"schema_version":2,"defaults":{"deskew":{"mode":"off"}}}' | Set-Content -LiteralPath $config -Encoding utf8
foreach ($codec in @('png','tiff','jpeg')) {
    $output = Join-Path $testRoot $codec
    $options = @{PdfDir=$pdfDir; ScanTailorDir=$toolPath; OutputDir=$output; Dpi=120; Config=$config; ImageFormat=$codec}
    if ($codec -eq 'png') { $options.PngCompression = 0 }
    elseif ($codec -eq 'tiff') { $options.TiffCompression = 'lzw' }
    else { $options.JpegQuality = 25 }
    & (Join-Path $toolPath 'Process-PdfFolder.ps1') @options
    if ($LASTEXITCODE -ne 0) { throw "PowerShell $codec failed" }
    $stateFile = Get-ChildItem -LiteralPath (Join-Path $output '_scantailor/.work') -Filter state.json -File -Recurse | Select-Object -First 1
    $state = Get-Content -LiteralPath $stateFile.FullName -Raw | ConvertFrom-Json
    $policy = $state.signature.image_encoding
    if ($policy.format -ne $codec) { throw 'Format was not forwarded' }
    if ($codec -eq 'png' -and $policy.png_compression -ne 0) { throw 'PNG 0 was not forwarded' }
    if ($codec -eq 'tiff' -and $policy.tiff_compression -ne 'lzw') { throw 'TIFF codec was not forwarded' }
    if ($codec -eq 'jpeg' -and $policy.jpeg_quality -ne 25) { throw 'JPEG quality was not forwarded' }
}
if ((Get-FileHash -LiteralPath $pdf -Algorithm SHA256).Hash -ne $originalHash) { throw 'Input changed' }
Write-Output 'PASS: PowerShell forwards PNG level 0, TIFF LZW and JPEG quality 25; source unchanged.'
