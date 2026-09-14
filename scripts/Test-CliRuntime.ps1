[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Executable,
    [string[]]$Arguments = @('doctor'),
    [ValidateRange(1, 600)][int]$TimeoutSeconds = 30
)
$ErrorActionPreference = 'Stop'
# Build/package smoke checks must report loader failures instead of hanging on
# an invisible Windows error dialog. This setting is inherited by this child only.
if ($IsWindows -and -not ('ScanTailorBuild.ErrorMode' -as [type])) {
    Add-Type 'namespace ScanTailorBuild { public static class ErrorMode { [System.Runtime.InteropServices.DllImport("kernel32.dll")] public static extern uint SetErrorMode(uint mode); } }'
}
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = (Resolve-Path -LiteralPath $Executable).Path
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
foreach ($argument in $Arguments) { $start.ArgumentList.Add($argument) }
if ($env:GITHUB_ACTIONS -eq 'true') { $start.Environment['QT_DEBUG_PLUGINS'] = '1' }
$process = [Diagnostics.Process]::new()
$process.StartInfo = $start
try {
    if ($IsWindows) { $oldMode = [ScanTailorBuild.ErrorMode]::SetErrorMode(0x8003) }
    try { $null = $process.Start() }
    finally { if ($IsWindows) { $null = [ScanTailorBuild.ErrorMode]::SetErrorMode($oldMode) } }
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        # CI-only hang diagnosis: capture stacks without a GUI or publishing an artifact.
        $debugger = Get-Command gdb.exe -ErrorAction SilentlyContinue
        if ($env:GITHUB_ACTIONS -eq 'true' -and $debugger) {
            $debugStart = [Diagnostics.ProcessStartInfo]::new()
            $debugStart.FileName = $debugger.Source
            $debugStart.UseShellExecute = $false
            $debugStart.CreateNoWindow = $true
            $debugStart.RedirectStandardOutput = $true
            $debugStart.RedirectStandardError = $true
            foreach ($arg in @('--batch', '-ex', "attach $($process.Id)", '-ex', 'thread apply all bt', '-ex', 'detach')) {
                $debugStart.ArgumentList.Add($arg)
            }
            $debugProcess = [Diagnostics.Process]::Start($debugStart)
            try {
                $debugOut = $debugProcess.StandardOutput.ReadToEndAsync()
                $debugErr = $debugProcess.StandardError.ReadToEndAsync()
                if (-not $debugProcess.WaitForExit(15000)) { $debugProcess.Kill($true); $debugProcess.WaitForExit() }
                Write-Output $debugOut.GetAwaiter().GetResult()
                Write-Output $debugErr.GetAwaiter().GetResult()
            } finally { $debugProcess.Dispose() }
        }
        $process.Kill($true)
        $process.WaitForExit()
        Write-Output $stdout.GetAwaiter().GetResult()
        Write-Output $stderr.GetAwaiter().GetResult()
        throw "CLI runtime check timed out after $TimeoutSeconds seconds"
    }
    Write-Output $stdout.GetAwaiter().GetResult()
    Write-Output $stderr.GetAwaiter().GetResult()
    if ($process.ExitCode -ne 0) { throw "CLI runtime check failed with exit code $($process.ExitCode)" }
} finally { $process.Dispose() }
