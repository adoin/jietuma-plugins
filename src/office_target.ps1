# Read-only: do not activate windows, select cells, or modify workbooks.
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class TargetWindow { [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p); [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint f); }'
[uint32]$targetPid = 0
$null = [TargetWindow]::GetWindowThreadProcessId([IntPtr]::new([long]$expected), [ref]$targetPid)
if (-not $targetPid) { exit 3 }
$process = Get-Process -Id $targetPid
if ($process.ProcessName -notin @('EXCEL','et')) { [Console]::Out.Write('{"unsupported":true}'); exit 0 }
foreach ($progId in @('ket.Application','Excel.Application')) {
    try {
        $app = [Runtime.InteropServices.Marshal]::GetActiveObject($progId)
        [uint32]$appPid = 0
        $null = [TargetWindow]::GetWindowThreadProcessId([IntPtr]::new([long]$app.Hwnd), [ref]$appPid)
        if ($appPid -ne $targetPid) { continue }
        if ($app.Ready -eq $false) { exit 3 }
        $window = $app.ActiveWindow
        $root = [TargetWindow]::GetAncestor([IntPtr]::new([long]$expected),2)
        $appRoot = [TargetWindow]::GetAncestor([IntPtr]::new([long]$window.Hwnd),2)
        if ($root -ne $appRoot) { continue }
        $selection = $window.RangeSelection
        $row = [int]$selection.Row
        $column = [int]$selection.Column
        if ($row -lt 1 -or $column -lt 1) { exit 3 }
        [Console]::Out.Write((@{row=$row;column=$column} | ConvertTo-Json -Compress))
        exit 0
    } catch { }
}
exit 3
