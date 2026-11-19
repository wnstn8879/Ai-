#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Start','Backend','Metro','Check')][string]$Mode = 'Start',
    [string]$ApkPath,
    [string]$DeviceSerial,
    [switch]$LibraryOnly,
    [switch]$NoInstall
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$script:Runtime = Join-Path $script:Root '.runtime\windows'
$script:Mobile = Join-Path $script:Root 'mobile'
$script:Backend = Join-Path $script:Root 'backend'
$script:VenvPython = Join-Path $script:Runtime 'venv\Scripts\python.exe'
$script:ScriptPath = $PSCommandPath
$script:Package = 'com.storyverse.ai'

function Invoke-Native {
    param([string]$Program,[string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $result = @(& $Program @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    $lines = @($result | ForEach-Object { $_.ToString() })
    if ($exitCode -ne 0) { throw "명령 실행 실패 ($exitCode): $Program`n$($lines -join "`n")" }
    return $lines
}

function Invoke-Visible {
    param([string]$Program,[string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Program @Arguments; $exitCode = $LASTEXITCODE }
    finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "명령 실행 실패 ($exitCode): $Program" }
}

function Get-NodePath {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) { throw 'Node.js 22 이상을 https://nodejs.org/ 에서 설치한 뒤 다시 실행해주세요.' }
    $version = ((Invoke-Native $node.Source @('--version')) -join '').Trim().TrimStart('v')
    if ([int]($version.Split('.')[0]) -lt 22) { throw 'Node.js 22 이상이 필요합니다. https://nodejs.org/' }
    return $node.Source
}

function Get-PythonCommand {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($prefix in @('-3.12','-3.13','-3')) {
            try {
                $value = ((Invoke-Native $py.Source @($prefix,'-c','import sys; print(sys.version_info.major*100+sys.version_info.minor)')) -join '').Trim()
                if ([int]$value -ge 312) { return @{ Program=$py.Source; Prefix=@($prefix) } }
            } catch { }
        }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python -and $python.Source -notlike '*\WindowsApps\*') {
        $value = ((Invoke-Native $python.Source @('-c','import sys; print(sys.version_info.major*100+sys.version_info.minor)')) -join '').Trim()
        if ([int]$value -ge 312) { return @{ Program=$python.Source; Prefix=@() } }
    }
    throw 'Python 3.12 이상을 https://www.python.org/downloads/windows/ 에서 설치해주세요. 설치 시 Python Launcher 또는 PATH 옵션을 선택하세요.'
}

function Get-AdbPath {
    $existing = Get-Command adb.exe -ErrorAction SilentlyContinue
    if ($existing) { return $existing.Source }
    $path = Join-Path $script:Runtime 'platform-tools\adb.exe'
    if (-not (Test-Path $path)) {
        Write-Host 'Google 공식 Android Platform Tools를 프로젝트 폴더에 다운로드합니다.'
        New-Item -ItemType Directory -Force -Path $script:Runtime | Out-Null
        $zip = Join-Path $script:Runtime 'platform-tools.zip'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile $zip
        Expand-Archive -LiteralPath $zip -DestinationPath $script:Runtime -Force
        Remove-Item -LiteralPath $zip
    }
    if (-not (Test-Path $path)) { throw 'ADB 도구 준비에 실패했습니다.' }
    return $path
}

function ConvertFrom-AdbDevices {
    param([string]$Text)
    foreach ($line in ($Text -split "`r?`n")) {
        if ($line -match '^(?<serial>\S+)\s+(?<state>device|offline|unauthorized)\b') {
            [PSCustomObject]@{ Serial=$Matches.serial; State=$Matches.state }
        }
    }
}

function Get-Device {
    param([string]$Adb,[string]$Serial)
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    Write-Host '휴대폰 잠금을 풀고 USB 디버깅 허용 창에서 [허용]을 눌러주세요.'
    do {
        $rows = @(ConvertFrom-AdbDevices ((Invoke-Native $Adb @('devices','-l')) -join "`n"))
        $ready = @($rows | Where-Object { $_.State -eq 'device' -and ((-not $Serial) -or $_.Serial -eq $Serial) })
        if ($ready.Count -eq 1) { return $ready[0].Serial }
        if ($ready.Count -gt 1) { throw '기기가 여러 대입니다. 한 대만 연결하거나 -DeviceSerial 옵션으로 선택해주세요.' }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    throw '휴대폰을 찾지 못했습니다. 데이터 전송 USB 케이블, USB 디버깅 허용, 제조사 USB 드라이버를 확인해주세요.'
}

function Test-LocalPort {
    param([int]$Port)
    $client = New-Object Net.Sockets.TcpClient
    try {
        $task = $client.BeginConnect('127.0.0.1',$Port,$null,$null)
        if (-not $task.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($task)
        return $client.Connected
    } catch { return $false }
    finally { $client.Dispose() }
}

function Wait-Service {
    param([string]$Uri,[string]$Name,[int]$Seconds=120)
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "$Name 시작 실패. 별도로 열린 실행 창의 오류를 확인해주세요."
}

function Start-ServiceWindow {
    param([string]$ServiceMode)
    $quoted = $script:ScriptPath.Replace("'","''")
    $command = "& '$quoted' -Mode '$ServiceMode'"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-NoExit','-EncodedCommand',$encoded) -PassThru | Out-Null
}

function Resolve-ApkPath {
    param([string]$InputPath)
    if ($InputPath) {
        $resolved = (Resolve-Path -LiteralPath $InputPath).Path
        if ([IO.Path]::GetExtension($resolved) -ne '.apk') { throw 'ZIP을 풀고 .apk 파일을 선택해주세요.' }
        return $resolved
    }
    foreach ($candidate in @((Join-Path $script:Root 'app-debug.apk'),(Join-Path $script:Mobile 'app-debug.apk'))) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = '다운로드하고 압축을 푼 app-debug.apk를 선택하세요'
    $dialog.Filter = 'Android app (*.apk)|*.apk'
    if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw 'APK 선택을 취소했습니다.' }
    return $dialog.FileName
}

function Initialize-Dependencies {
    $null = Get-NodePath
    $python = Get-PythonCommand
    New-Item -ItemType Directory -Force -Path $script:Runtime | Out-Null
    if (-not (Test-Path $script:VenvPython)) { Invoke-Visible $python.Program ($python.Prefix + @('-m','venv',(Join-Path $script:Runtime 'venv'))) }
    Invoke-Visible $script:VenvPython @('-m','pip','install','-r',(Join-Path $script:Backend 'requirements.txt'))
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) { throw 'npm.cmd를 찾지 못했습니다. Node.js를 다시 설치해주세요.' }
    $lock = (Get-FileHash (Join-Path $script:Mobile 'package-lock.json') -Algorithm SHA256).Hash
    $stamp = Join-Path $script:Runtime 'npm-lock.sha256'
    $installed = Test-Path (Join-Path $script:Mobile 'node_modules\expo\package.json')
    if (-not $installed -or -not (Test-Path $stamp) -or ((Get-Content $stamp -Raw).Trim() -ne $lock)) {
        Push-Location $script:Mobile
        try { Invoke-Visible $npm.Source @('ci') } finally { Pop-Location }
        Set-Content -LiteralPath $stamp -Value $lock -Encoding ASCII
    }
}

function Main {
    if ($Mode -eq 'Backend') {
        Push-Location $script:Backend
        try { Invoke-Visible $script:VenvPython @('-m','app.local_dev','--database-file',(Join-Path $script:Runtime 'storyverse-local.db')) }
        finally { Pop-Location }
        return
    }
    if ($Mode -eq 'Metro') {
        $env:EXPO_PUBLIC_API_URL = 'http://127.0.0.1:8000'
        $env:EXPO_NO_TELEMETRY = '1'
        Remove-Item Env:CI -ErrorAction SilentlyContinue
        Push-Location $script:Mobile
        try { Invoke-Visible (Get-Command npm.cmd).Source @('exec','--','expo','start','--localhost','--port','8081') }
        finally { Pop-Location }
        return
    }
    if ($Mode -eq 'Check') {
        $null = Get-NodePath
        $python = Get-PythonCommand
        Write-Host "Python: $($python.Program)"
        $adb = Get-AdbPath
        Invoke-Native $adb @('devices','-l') | ForEach-Object { Write-Host $_ }
        Write-Host '기본 점검 완료. 휴대폰 상태가 device이면 연결 준비가 됐습니다.'
        return
    }
    foreach ($port in @(8000,8081)) {
        if (Test-LocalPort $port) { throw "포트 $port 가 사용 중입니다. 이전 StoryVerse 실행 창을 닫고 다시 실행해주세요. 다른 프로그램은 자동 종료하지 않습니다." }
    }
    $apk = if ($NoInstall) { $null } else { Resolve-ApkPath $ApkPath }
    Initialize-Dependencies
    $adb = Get-AdbPath
    $serial = Get-Device $adb $DeviceSerial
    Start-ServiceWindow 'Backend'
    Wait-Service 'http://127.0.0.1:8000/health' '백엔드'
    Start-ServiceWindow 'Metro'
    Wait-Service 'http://127.0.0.1:8081/status' 'Metro'
    if (-not $NoInstall) { Invoke-Native $adb @('-s',$serial,'install','-r','-t',$apk) | ForEach-Object { Write-Host $_ } }
    foreach ($port in @(8000,8081)) { $null = Invoke-Native $adb @('-s',$serial,'reverse',"tcp:$port","tcp:$port") }
    $null = Invoke-Native $adb @('-s',$serial,'shell','am','force-stop',$script:Package)
    $null = Invoke-Native $adb @('-s',$serial,'shell','am','start','-n',"$script:Package/.MainActivity")
    Write-Host '휴대폰에서 StoryVerse AI가 열렸습니다. 새 계정을 만들어 사용하세요.' -ForegroundColor Green
    Write-Host '백엔드와 Metro 창, USB 연결을 유지하세요. 종료할 때 두 창에서 Ctrl+C를 누르세요.'
}

if (-not $LibraryOnly) {
    try { Main }
    catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
}
