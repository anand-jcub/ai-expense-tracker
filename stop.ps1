# Stop all expense-tracker watchdogs and servers for this project.
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Stop-PidFile([string]$path) {
    if (Test-Path $path) {
        $raw = (Get-Content $path -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($raw -match '^\d+$') {
            $procId = [int]$raw
            if ($procId -gt 0) {
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                Write-Host "Stopped pid $procId ($path)"
            }
        }
        Remove-Item $path -Force -ErrorAction SilentlyContinue
    }
}

Stop-PidFile (Join-Path $Root "watchdog.pid")
Stop-PidFile (Join-Path $Root "server.pid")

# Kill any leftover project python/pythonw processes
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and
        $_.CommandLine -and
        ($_.CommandLine -like '*i-want-to-build-an-ai*run_forever.py*' -or
         $_.CommandLine -like '*i-want-to-build-an-ai*app.py*' -or
         $_.CommandLine -like '*i-want-to-build-an-ai\run_forever.py*' -or
         $_.CommandLine -like '*i-want-to-build-an-ai\app.py*')
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped leftover $($_.Name) pid $($_.ProcessId)"
    }

Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
        $p = $_.OwningProcess
        if ($p -and $p -ne 0) {
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped listener pid $p"
        }
    }

Remove-Item (Join-Path $Root "watchdog.lock") -Force -ErrorAction SilentlyContinue
Write-Host "Server stopped."
