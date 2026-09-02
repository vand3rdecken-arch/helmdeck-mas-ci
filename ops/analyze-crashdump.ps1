# Analyzes the collected kernel minidump with WinDbg (user-scope MSIX, no admin needed).
# Writes a plain-text report next to the dump.
$ErrorActionPreference = 'Continue'
$dest    = 'C:\Users\Tien Duy Vo\Desktop\crashdump'
$symbols = 'C:\Users\Tien Duy Vo\Desktop\crashdump\symbols'
$report  = Join-Path $dest 'analyze.txt'
$windbg  = "$env:LOCALAPPDATA\Microsoft\WindowsApps\WinDbgX.exe"

$dump = Get-ChildItem $dest -Filter '*.dmp' |
        Where-Object { $_.Name -notlike 'WATCHDOG*' } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $dump) { "NO DUMP FOUND in $dest"; exit 1 }

New-Item -ItemType Directory -Force -Path $symbols | Out-Null
Remove-Item $report -ErrorAction SilentlyContinue

$cmds = @(
    ".sympath srv*$symbols*https://msdl.microsoft.com/download/symbols"
    '.reload /f'
    ".logopen $report"
    '!analyze -v'
    '.bugcheck'
    'k'
    'lm kv'
    '.logclose'
    'qq'
) -join '; '

"dump    : $($dump.FullName)"
"windbg  : $windbg"
"running : !analyze -v (Symbole werden geladen, kann 1-3 Min dauern)"

& $windbg -z $dump.FullName -c $cmds

# WinDbgX detaches; wait for the log to stop growing
$last = -1; $stable = 0
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Seconds 3
    if (Test-Path $report) {
        $len = (Get-Item $report).Length
        if ($len -eq $last -and $len -gt 0) { $stable++ } else { $stable = 0 }
        if ($stable -ge 3) { break }
        $last = $len
    }
}
"report  : $report ($(if(Test-Path $report){(Get-Item $report).Length}else{0}) bytes)"
