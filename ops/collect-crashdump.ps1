# One-shot elevated collector: copies crash artifacts to a user-readable folder.
# Read-only with respect to the system: nothing is deleted or modified.
$ErrorActionPreference = 'SilentlyContinue'
$dest = 'C:\Users\Tien Duy Vo\Desktop\crashdump'
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# 1. Kernel minidumps
Copy-Item 'C:\Windows\Minidump\*.dmp' -Destination $dest -Force

# 2. WER kernel report for the 0x13A bugcheck (queue + archive)
foreach ($root in @('C:\ProgramData\Microsoft\Windows\WER\ReportQueue',
                    'C:\ProgramData\Microsoft\Windows\WER\ReportArchive')) {
    Get-ChildItem $root -Directory -Filter 'Kernel_13a*' | ForEach-Object {
        Copy-Item $_.FullName -Destination (Join-Path $dest $_.Name) -Recurse -Force
    }
}

# 3. WER sysdata (contains the loaded-driver list at crash time)
Copy-Item 'C:\Windows\SystemTemp\WER-*.sysdata.xml' -Destination $dest -Force

# 4. GPU watchdog live-kernel dumps: inventory + newest dump
Get-ChildItem 'C:\Windows\LiveKernelReports' -Recurse -File |
    Select-Object FullName, Length, LastWriteTime |
    Export-Csv (Join-Path $dest 'livekernel-inventory.csv') -NoTypeInformation
Get-ChildItem 'C:\Windows\LiveKernelReports' -Recurse -File -Filter '*.dmp' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1 |
    ForEach-Object { Copy-Item $_.FullName -Destination $dest -Force }

# 5. Hand ownership of the copies to the owner so non-elevated tools can read them
& icacls $dest /grant "${env:USERNAME}:(OI)(CI)F" /T | Out-Null

"collected $(Get-Date -Format o)" | Out-File (Join-Path $dest '_DONE.txt') -Encoding utf8
