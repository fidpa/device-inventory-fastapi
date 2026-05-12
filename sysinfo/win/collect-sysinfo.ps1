#Requires -Version 5.1
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
# Example Organization - System information collect v1.0.0
# Collects Windows system information via CIM queries and stores it as JSON.
# Target: Desktop + Nextcloud (cloud.example.com) for DB import (device inventory)
# Schema version: 1.0

Set-StrictMode -Version Latest
$ErrorActionPreference = 'SilentlyContinue'

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# -- Configuration --------------------------------------------------------
$MailAddress       = "admin@example.com"
$NextcloudUrl      = "https://cloud.example.com/remote.php/dav/files/sysinfo/inbox"
$NextcloudUser     = "sysinfo"
$NextcloudPassword = "YOUR_NEXTCLOUD_APP_PASSWORD"
# --------------------------------------------------------------------------

# -- Helper functions -------------------------------------------------------

function Write-Status {
    param([string]$Message, [string]$Color = "White")
    Write-Host "  $Message" -ForegroundColor $Color
}

function Test-DirWritable {
    param([string]$Dir)
    if (-not (Test-Path $Dir)) { return $false }
    try {
        $TestFile = Join-Path $Dir ".write_test_$PID.tmp"
        [System.IO.File]::WriteAllText($TestFile, "write_test")
        Remove-Item -LiteralPath $TestFile -Force -ErrorAction SilentlyContinue
        return $true
    } catch {
        return $false
    }
}

function Safe {
    # Null-safe string conversion; returns $null for JSON compatibility
    param($Value)
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace("$Value")) { return $null }
    return "$Value".Trim()
}

function Safe-Date {
    # Null-safe date formatting in ISO-8601 format for JSON
    param($DateValue, [string]$Format = 'yyyy-MM-ddTHH:mm:ss')
    if ($null -eq $DateValue) { return $null }
    try { return $DateValue.ToString($Format) } catch { return $null }
}

# -- Terminal server detection -----------------------------------------------
# ProductType: 1 = Workstation, 2 = Domain Controller, 3 = Server
# CLIENTNAME alone is not sufficient — it is also set for regular RDP on workstations.

$osProductType     = (Get-CimInstance Win32_OperatingSystem -EA SilentlyContinue).ProductType
$onTerminalServer  = ($osProductType -ne 1) -and ($null -ne $osProductType)

if ($onTerminalServer) {
    Write-Host ""
    Write-Host "  ========================================================" -ForegroundColor DarkGray
    Write-Host "     Example Organization - System information" -ForegroundColor Cyan
    Write-Host "  ========================================================" -ForegroundColor DarkGray
    Write-Host ""
    Write-Status "NOTE: You are connected to the terminal server." "Yellow"
    Write-Status "This program only collects the hardware of the PC" "Yellow"
    Write-Status "on which it is run directly." "Yellow"
    Write-Host ""
    Write-Status "On the terminal server only the server data would be" "Yellow"
    Write-Status "collected — that is NOT what we need." "Yellow"
    Write-Host ""
    Write-Status "Please run the program directly on your PC:" "White"
    Write-Host ""
    Write-Status "  1. Copy the folder to your local desktop" "Cyan"
    Write-Status "  2. Open the folder on your local desktop" "Cyan"
    Write-Status "  3. Double-click on  HIER-DOPPELKLICKEN.bat" "Cyan"
    Write-Host ""
    Write-Status "Questions? $MailAddress" "DarkGray"
    Write-Host ""
    Read-Host "  Press Enter to close"
    exit 0
}

# -- Last name prompt --------------------------------------------------------

Write-Host ""
Write-Host "  ========================================================" -ForegroundColor DarkGray
Write-Host "     Example Organization - System information" -ForegroundColor Cyan
Write-Host "  ========================================================" -ForegroundColor DarkGray
Write-Host ""

do {
    $last_name = (Read-Host "  Please enter your last name and press Enter").Trim()
    if (-not $last_name) {
        Write-Status "Input required. Please enter your last name." "Yellow"
    }
} while (-not $last_name)

$safeLastName = ($last_name -replace '[^\w\-]', '')
if (-not $safeLastName) { $safeLastName = "UNKNOWN" }

# -- Filename and path -------------------------------------------------------

$safeComputer = ($env:COMPUTERNAME -replace '[^\w\-]', '')
if (-not $safeComputer) { $safeComputer = "UNKNOWN" }
$fileName = "sysinfo_${safeLastName}_${safeComputer}.json"

# Determine desktop path (robust)
$desktopDir = try { [Environment]::GetFolderPath('Desktop') } catch { "" }
if (-not $desktopDir -or -not (Test-Path $desktopDir)) {
    $desktopDir = "$env:USERPROFILE\Desktop"
}
if (-not (Test-Path $desktopDir)) {
    $desktopDir = $env:USERPROFILE
}
$lokalerPath = Join-Path $desktopDir $fileName

# -- CIM data collection ----------------------------------------------------

Write-Host ""
Write-Status "Collecting system information..." "White"
Write-Status "Please wait a moment." "DarkGray"
Write-Host ""

$collectedAm = Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'

# Device
$deviceData = @{ name = $null; manufacturer = $null; model = $null; serial_number = $null; system_type = $null }
try {
    $sys  = Get-CimInstance Win32_ComputerSystem -EA Stop
    $bios = Get-CimInstance Win32_BIOS -EA Stop
    $deviceData = [ordered]@{
        name         = Safe $sys.Name
        manufacturer   = Safe $sys.Manufacturer
        model       = Safe $sys.Model
        serial_number = Safe $bios.SerialNumber
        system_type    = Safe $sys.SystemType
    }
} catch {}

# Operating System
$osData = [ordered]@{}
try {
    $os  = Get-CimInstance Win32_OperatingSystem -EA Stop
    $reg = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -EA SilentlyContinue

    $displayVersion = if ($reg) { $reg.DisplayVersion } else { $null }
    $releaseId      = if ($reg) { $reg.ReleaseId } else { $null }
    $ubr            = if ($reg) { $reg.UBR } else { $null }
    $buildFull      = if ($ubr) { "$($os.BuildNumber).$ubr" } else { "$($os.BuildNumber)" }
    $versionLabel   = if ($displayVersion) { $displayVersion } elseif ($releaseId) { $releaseId } else { $null }

    $osData = [ordered]@{
        name             = Safe $os.Caption
        version          = $versionLabel
        build            = $buildFull
        architektur      = Safe $os.OSArchitecture
        installiert_am   = Safe-Date $os.InstallDate 'yyyy-MM-dd'
        last_restart = Safe-Date $os.LastBootUpTime
    }
} catch {}

# CPU
$cpuData = [ordered]@{}
try {
    $cpu = Get-CimInstance Win32_Processor -EA Stop | Select-Object -First 1
    $cpuData = [ordered]@{
        description  = Safe $cpu.Name
        cores        = [int]$cpu.NumberOfCores
        threads      = [int]$cpu.NumberOfLogicalProcessors
        max_takt_mhz = [int]$cpu.MaxClockSpeed
    }
} catch {}

# RAM
$ramData = [ordered]@{ total_gb = 0.0; module = @() }
try {
    $ramModules = @(Get-CimInstance Win32_PhysicalMemory -EA Stop)
    if ($ramModules.Count -gt 0) {
        $totalGB = [math]::Round(($ramModules | Measure-Object Capacity -Sum).Sum / 1GB, 1)
        $ramData.total_gb = $totalGB
        $ramData.module = @($ramModules | ForEach-Object {
            $m = $_
            [ordered]@{
                kapazitaet_gb       = if ($m.Capacity) { [int][math]::Round($m.Capacity / 1GB, 0) } else { 0 }
                type                 = switch ($m.SMBIOSMemoryType) {
                    20{"DDR"} 21{"DDR2"} 24{"DDR3"} 26{"DDR4"} 34{"DDR5"} default{"Type $($m.SMBIOSMemoryType)"}
                }
                speed_mhz = if ($m.Speed) { [int]$m.Speed } else { 0 }
                manufacturer          = Safe $m.Manufacturer
                slot                = Safe $m.DeviceLocator
            }
        })
    }
} catch {}

# Drives (physical)
$laufwerkeData = @()
try {
    $laufwerkeData = @(Get-CimInstance Win32_DiskDrive -EA Stop | Sort-Object Index | ForEach-Object {
        $disk = $_
        [ordered]@{
            model        = Safe $disk.Model
            serial_number  = Safe ("$($disk.SerialNumber)".Trim())
            groesse_gb    = if ($disk.Size) { [int][math]::Round($disk.Size / 1GB, 0) } else { 0 }
            schnittstelle = Safe $disk.InterfaceType
            medientype     = Safe $disk.MediaType
        }
    })
} catch {}

# Partitions (logical drives)
$partitionenData = @()
try {
    $partitionenData = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -EA Stop |
        Where-Object { $_.Size -and $_.Size -gt 0 } |
        ForEach-Object {
            $d   = $_
            $tGB = [math]::Round($d.Size / 1GB, 0)
            $bGB = [math]::Round(($d.Size - $d.FreeSpace) / 1GB, 1)
            $pct = [math]::Round(($d.Size - $d.FreeSpace) / $d.Size * 100, 0)
            [ordered]@{
                laufwerk       = $d.DeviceID
                filesystem    = Safe $d.FileSystem
                groesse_gb     = [int]$tGB
                used_gb      = $bGB
                used_prozent = [int]$pct
            }
        })
} catch {}

# GPU
$gpuData = @()
try {
    $gpuData = @(Get-CimInstance Win32_VideoController -EA Stop | ForEach-Object {
        $gpu    = $_
        $vramGB = if ($gpu.AdapterRAM -and $gpu.AdapterRAM -gt 0) {
            [math]::Round($gpu.AdapterRAM / 1GB, 1)
        } else { 0.0 }
        $res = if ($gpu.CurrentHorizontalResolution -and $gpu.CurrentVerticalResolution) {
            "$($gpu.CurrentHorizontalResolution)x$($gpu.CurrentVerticalResolution)"
        } else { $null }
        [ordered]@{
            name            = Safe $gpu.Name
            vram_gb         = $vramGB
            treiber_version = Safe $gpu.DriverVersion
            aufloesung      = $res
        }
    })
} catch {}

# Monitore
$monitoreData = @()
try {
    $monitors = @(Get-CimInstance -Namespace root/wmi WmiMonitorID -EA SilentlyContinue)
    $monitoreData = @($monitors | ForEach-Object {
        $mon    = $_
        $mfg    = try { ($mon.ManufacturerName | Where-Object {$_ -gt 0} | ForEach-Object {[char]$_}) -join '' } catch { $null }
        $mname  = try { ($mon.UserFriendlyName | Where-Object {$_ -gt 0} | ForEach-Object {[char]$_}) -join '' } catch { $null }
        $serial = try { ($mon.SerialNumberID   | Where-Object {$_ -gt 0} | ForEach-Object {[char]$_}) -join '' } catch { $null }
        [ordered]@{
            manufacturer   = if ($mfg)    { $mfg }    else { $null }
            description  = if ($mname)  { $mname }  else { $null }
            serial_number = if ($serial) { $serial } else { $null }
        }
    })
} catch {}

# Network (IP-enabled adapters)
$networkData = @()
try {
    $networkData = @(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=True" -EA Stop |
        ForEach-Object {
            $nic  = $_
            $ipv4 = if ($nic.IPAddress) {
                $nic.IPAddress | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' } | Select-Object -First 1
            } else { $null }
            [ordered]@{
                adapter = Safe $nic.Description
                mac     = Safe $nic.MACAddress
                ip      = $ipv4
                dhcp    = [bool]$nic.DHCPEnabled
            }
        })
} catch {}

# Software (all installed programs)
$softwareData = @()
try {
    $regPaths = @(
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    $softwareData = @(Get-ItemProperty $regPaths -EA SilentlyContinue |
        Where-Object { $_.DisplayName -and $_.DisplayName -notmatch "^KB\d" } |
        Sort-Object DisplayName |
        ForEach-Object {
            $app          = $_
            $installDate = $null
            try {
                if ($app.InstallDate -match '^\d{8}$') {
                    $installDate = [datetime]::ParseExact($app.InstallDate, 'yyyyMMdd', $null).ToString('yyyy-MM-dd')
                }
            } catch {}
            [ordered]@{
                name          = $app.DisplayName
                version       = Safe $app.DisplayVersion
                installiert_am = $installDate
            }
        })
} catch {}

# -- Assemble JSON ----------------------------------------------------------

$sysinfo = [ordered]@{
    schema_version = "1.0"
    collected_at     = $collectedAm
    collected_by   = $last_name
    device         = $deviceData
    operating_system = $osData
    cpu            = $cpuData
    ram            = $ramData
    laufwerke      = $laufwerkeData
    partitionen    = $partitionenData
    gpu            = $gpuData
    monitore       = $monitoreData
    network       = $networkData
    software       = $softwareData
}

$jsonContent = $sysinfo | ConvertTo-Json -Depth 10

# -- JSON on Desktop save --------------------------------------------

try {
    [System.IO.File]::WriteAllText($lokalerPath, $jsonContent, [System.Text.Encoding]::UTF8)
} catch {
    # Fallback: USERPROFILE direkt
    try {
        $lokalerPath = "$env:USERPROFILE\$fileName"
        [System.IO.File]::WriteAllText($lokalerPath, $jsonContent, [System.Text.Encoding]::UTF8)
    } catch {
        $lokalerPath = $null
    }
}

# -- Upload after Nextcloud (cloud.example.com) ----------------------------

$shareOK = $false
try {
    $ErrorActionPreference = 'Stop'

    $uploadUrl = "$NextcloudUrl/$fileName"
    $secPass   = ConvertTo-SecureString $NextcloudPassword -AsPlainText -Force
    $cred      = New-Object System.Management.Automation.PSCredential($NextcloudUser, $secPass)

    $response  = Invoke-WebRequest `
        -Uri            $uploadUrl `
        -Method         PUT `
        -InFile         $lokalerPath `
        -Credential     $cred `
        -UseBasicParsing `
        -TimeoutSec     60 `
        -EA             Stop

    if ($response.StatusCode -in 200, 201, 204) {
        $shareOK = $true
    }
} catch {
    # Upload is optional — no error shown to the user
} finally {
    $ErrorActionPreference = 'SilentlyContinue'
}

# -- Show result --------------------------------------------------------------

$fileInfo = if ($lokalerPath -and (Test-Path -LiteralPath $lokalerPath)) {
    Get-Item -LiteralPath $lokalerPath -EA SilentlyContinue
} else { $null }
$sizeKB = if ($fileInfo) { [math]::Round($fileInfo.Length / 1KB, 0) } else { 0 }

Write-Host ""
Write-Host "  ========================================================" -ForegroundColor Green
Write-Host ""
Write-Status "DONE!  System information collected successfully." "Green"
Write-Host ""
Write-Status "File:     $fileName" "White"
Write-Status "Size:     $sizeKB KB" "DarkGray"
Write-Status "Location: $desktopDir" "DarkGray"

if ($shareOK) {
    Write-Host ""
    Write-Status "The file was automatically submitted to IT." "Green"
    Write-Status "No further action required." "Green"
} else {
    Write-Host ""
    Write-Status "Please send the file by e-mail to:" "Yellow"
    Write-Host ""
    Write-Status "  $MailAddress" "White"
    Write-Host ""
    Write-Status "The file is on your Desktop." "DarkGray"
}

Write-Host ""
Write-Host "  ========================================================" -ForegroundColor Green
Write-Host ""
Read-Host "  Press Enter to close"
