#requires -Version 5.1
$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot 'Start-StoryVerse.ps1'
$tokens = $null
$errors = $null
$null = [Management.Automation.Language.Parser]::ParseFile($launcher,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
. $launcher -LibraryOnly
$rows = @(ConvertFrom-AdbDevices "List of devices attached`r`nphone-A`tdevice product:test`r`nphone-B`tunauthorized`r`nphone-C`toffline`r`n")
if ($rows.Count -ne 3 -or $rows[0].Serial -ne 'phone-A' -or $rows[1].State -ne 'unauthorized' -or $rows[2].State -ne 'offline') { throw 'ADB parsing failed' }
if (@(ConvertFrom-AdbDevices 'List of devices attached').Count -ne 0) { throw 'Empty ADB list failed' }
$null = Get-NodePath
$python = Get-PythonCommand
$listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,0)
$listener.Start()
$port = $listener.LocalEndpoint.Port
if (-not (Test-LocalPort $port)) { throw 'Open port not detected' }
$listener.Stop()
if (Test-LocalPort $port) { throw 'Closed port detected as open' }
$temp = Join-Path ([IO.Path]::GetTempPath()) ('storyverse launcher ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp | Out-Null
$database = Join-Path $temp 'local database.db'
$stdout = Join-Path $temp 'stdout.txt'
$stderr = Join-Path $temp 'stderr.txt'
$oldDatabase = $env:DATABASE_URL
$process = $null
try {
    # An inherited production URL must never be contacted by this launcher.
    $env:DATABASE_URL = 'postgresql://must-not-connect.invalid/production'
    $prefix = $python.Prefix -join ' '
    $arguments = "$prefix -m app.local_dev --database-file `"$database`" --port $port"
    $process = Start-Process $python.Program -ArgumentList $arguments -WorkingDirectory $script:Backend -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Wait-Service "http://127.0.0.1:$port/health" 'Test backend' 60
    if (-not (Test-Path -LiteralPath $database)) { throw 'Private database not created' }
    Write-Host 'PASS: PowerShell syntax, ADB states, prerequisites, port checks, migrated private backend and health.'
} catch {
    if (Test-Path $stderr) { Get-Content $stderr | Write-Host }
    throw
} finally {
    $env:DATABASE_URL = $oldDatabase
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
