#Requires -Version 5.1
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
# Example Organization - Printer collection v1.0.0
# Collects all network printers via CIM + SNMP and uploads JSON to Nextcloud.
# Runs on the Windows Terminal Server as a Scheduled Task (no user interaction).
# Schema version: 1.0

param(
    [switch]$DryRun,   # No upload; local JSON is still created
    [switch]$SkipSnmp  # Skip SNMP queries (CIM only)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'SilentlyContinue'

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# -- Configuration --------------------------------------------------------
$NextcloudUrl      = "https://cloud.example.com/remote.php/dav/files/sysinfo/inbox"
$NextcloudUser     = "sysinfo"
$NextcloudPassword = "YOUR_NEXTCLOUD_APP_PASSWORD"
# --------------------------------------------------------------------------

# -- Helper functions -------------------------------------------------------

function Write-Status {
    param([string]$Message, [string]$Color = "White")
    Write-Host "  $Message" -ForegroundColor $Color
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

# -- SNMP-Funktionen -------------------------------------------------------

function Encode-SnmpOid {
    # Dotted-notation (e.g. "1.3.6.1.2.1.1.1.0") -> BER-encoded bytes
    param([string]$OidStr)
    $parts = $OidStr.Trim('.').Split('.') | ForEach-Object { [int]$_ }
    $bytes = [System.Collections.Generic.List[byte]]::new()
    # First two components combined: (first * 40 + second)
    $bytes.Add([byte]($parts[0] * 40 + $parts[1]))
    for ($i = 2; $i -lt $parts.Count; $i++) {
        $val = $parts[$i]
        if ($val -lt 128) {
            $bytes.Add([byte]$val)
        } else {
            # Multi-byte BER encoding (Big-Endian, MSB-first with 0x80 bit)
            $subBytes = [System.Collections.Generic.List[byte]]::new()
            $subBytes.Add([byte]($val -band 0x7F))
            $val = $val -shr 7
            while ($val -gt 0) {
                $subBytes.Add([byte](($val -band 0x7F) -bor 0x80))
                $val = $val -shr 7
            }
            $subBytes.Reverse()
            foreach ($b in $subBytes) { $bytes.Add($b) }
        }
    }
    return $bytes.ToArray()
}

function Build-SnmpGet {
    # Builds a complete SNMPv2c GET-request packet (ASN.1/BER)
    param([string]$Community, [string[]]$OidList)
    $communityBytes = [System.Text.Encoding]::ASCII.GetBytes($Community)

    # Variable Bindings for every OID
    $varBindsContent = @()
    foreach ($oid in $OidList) {
        $oidBytes = Encode-SnmpOid $oid
        # OID-Objekt: 0x06 + Length + Bytes
        $oidTlv = @([byte]0x06, [byte]$oidBytes.Length) + $oidBytes
        # Null-Value: 0x05 0x00
        $nullTlv = @([byte]0x05, [byte]0x00)
        # VarBind Sequence: 0x30 + Length + OID-TLV + Null-TLV
        $varBindContent = $oidTlv + $nullTlv
        $varBind = @([byte]0x30, [byte]$varBindContent.Length) + $varBindContent
        $varBindsContent += $varBind
    }

    # VarBindList Sequence
    $varBindsSeq = @([byte]0x30, [byte]$varBindsContent.Length) + $varBindsContent

    # Request-ID (from TickCount, positiv)
    $reqIdVal = [System.Environment]::TickCount -band 0x7FFFFFFF
    $reqIdBytes = [System.BitConverter]::GetBytes([int]$reqIdVal)
    [System.Array]::Reverse($reqIdBytes)
    $reqIdTlv = @([byte]0x02, [byte]$reqIdBytes.Length) + [byte[]]$reqIdBytes

    # Error-Status: 0, Error-Index: 0
    $errStatus = @([byte]0x02, [byte]0x01, [byte]0x00)
    $errIndex  = @([byte]0x02, [byte]0x01, [byte]0x00)

    # PDU-Content
    $pduContent = $reqIdTlv + $errStatus + $errIndex + $varBindsSeq

    # GetRequest PDU: 0xA0
    $pdu = @([byte]0xA0, [byte]$pduContent.Length) + $pduContent

    # SNMP Version 1 (v2c = Integer 1)
    $versionTlv   = @([byte]0x02, [byte]0x01, [byte]0x01)
    $communityTlv = @([byte]0x04, [byte]$communityBytes.Length) + $communityBytes

    $msgContent = $versionTlv + $communityTlv + $pdu

    # Outer Sequence
    $packet = @([byte]0x30, [byte]$msgContent.Length) + $msgContent
    return [byte[]]$packet
}

function Parse-SnmpResponse {
    # Extracts the value from an SNMP response (first VarBind)
    param([byte[]]$Data)
    try {
        $i = 0
        # Outer Sequence
        if ($Data[$i] -ne 0x30) { return $null }; $i++
        if ($Data[$i] -lt 128) { $i++ } else { $skip = $Data[$i] -band 0x7F; $i += $skip + 1 }
        # Version (skip integer)
        if ($Data[$i] -ne 0x02) { return $null }; $i++; $i += $Data[$i] + 1
        # Community (skip OctetString)
        if ($Data[$i] -ne 0x04) { return $null }; $i++; $i += $Data[$i] + 1
        # Response PDU (0xA2)
        if ($Data[$i] -ne 0xA2) { return $null }; $i++
        if ($Data[$i] -lt 128) { $i++ } else { $skip = $Data[$i] -band 0x7F; $i += $skip + 1 }
        # RequestID (skip)
        if ($Data[$i] -ne 0x02) { return $null }; $i++; $i += $Data[$i] + 1
        # ErrorStatus: check whether 0 (no error)
        if ($Data[$i] -ne 0x02) { return $null }; $i++
        $errLen = $Data[$i]; $i++
        $errVal = 0
        for ($k = 0; $k -lt $errLen; $k++) { $errVal = ($errVal -shl 8) -bor $Data[$i]; $i++ }
        if ($errVal -ne 0) { return $null }
        # ErrorIndex (skip)
        if ($Data[$i] -ne 0x02) { return $null }; $i++; $i += $Data[$i] + 1
        # VarBindList Sequence
        if ($Data[$i] -ne 0x30) { return $null }; $i++
        if ($Data[$i] -lt 128) { $i++ } else { $skip = $Data[$i] -band 0x7F; $i += $skip + 1 }
        # First VarBind Sequence
        if ($Data[$i] -ne 0x30) { return $null }; $i++
        if ($Data[$i] -lt 128) { $i++ } else { $skip = $Data[$i] -band 0x7F; $i += $skip + 1 }
        # OID (skip)
        if ($Data[$i] -ne 0x06) { return $null }; $i++; $i += $Data[$i] + 1
        # Value
        $valType = $Data[$i]; $i++
        if ($Data[$i] -lt 128) {
            $valLen = $Data[$i]; $i++
        } else {
            $numBytes = $Data[$i] -band 0x7F; $i++
            $valLen = 0
            for ($k = 0; $k -lt $numBytes; $k++) { $valLen = ($valLen -shl 8) -bor $Data[$i]; $i++ }
        }
        if ($valLen -eq 0) { return $null }
        $valBytes = $Data[$i..($i + $valLen - 1)]
        # OctetString (0x04), PrintableString (0x13), VisibleString (0x1A) -> UTF-8
        if ($valType -in @(0x04, 0x13, 0x16, 0x1A)) {
            return [System.Text.Encoding]::UTF8.GetString($valBytes).Trim([char]0).Trim()
        }
        # Integer (0x02), Counter32 (0x41), Gauge32 (0x42), Counter64 (0x46), TimeTicks (0x43)
        if ($valType -in @(0x02, 0x41, 0x42, 0x43, 0x46)) {
            $num = 0
            foreach ($b in $valBytes) { $num = ($num -shl 8) -bor $b }
            return $num
        }
        return $null
    } catch {
        return $null
    }
}

function Send-SnmpGet {
    # Sends an SNMP GET-request and returns the parsed value
    param(
        [string]$IpAddress,
        [string]$OidStr,
        [string]$Community = "public",
        [int]$TimeoutMs = 2000
    )
    try {
        $packet = Build-SnmpGet -Community $Community -OidList @($OidStr)
        $udp    = [System.Net.Sockets.UdpClient]::new()
        $udp.Client.ReceiveTimeout = $TimeoutMs
        $udp.Connect($IpAddress, 161)
        $null     = $udp.Send($packet, $packet.Length)
        $ep       = [System.Net.IPEndPoint]::new([System.Net.IPAddress]::Any, 0)
        $response = $udp.Receive([ref]$ep)
        $udp.Close()
        return Parse-SnmpResponse -Data $response
    } catch {
        return $null
    }
}

function Get-PrinterSnmpData {
    # Queries all relevant SNMP OIDs for a printer
    param([string]$IpAddress, [string]$Community = "public")

    # Reachability check: sysDescr must respond
    $sysDescr   = Send-SnmpGet -IpAddress $IpAddress -OidStr "1.3.6.1.2.1.1.1.0"
    $hrDevDescr = Send-SnmpGet -IpAddress $IpAddress -OidStr "1.3.6.1.2.1.25.3.2.1.3.1"

    if ($null -eq $sysDescr -and $null -eq $hrDevDescr) {
        return $null  # No SNMP available
    }

    $result = [ordered]@{
        manufacturer    = $null
        model        = $null
        serial_number  = $null
        pages_total = $null
        pages_color  = $null
        toner         = @()
    }

    # Model/Manufacturer from hrDeviceDescr (preferred) or sysDescr
    if ($hrDevDescr) {
        $result.model = Safe $hrDevDescr
        # Manufacturer: first word if hrDeviceDescr has multiple parts
        $parts = "$hrDevDescr".Trim() -split '\s+', 2
        if ($parts.Count -ge 2 -and $parts[0].Length -le 30) {
            $result.manufacturer = Safe $parts[0]
        }
    } elseif ($sysDescr) {
        $result.model = Safe $sysDescr
    }

    # Serial Number (Printer-MIB)
    $result.serial_number = Safe (Send-SnmpGet -IpAddress $IpAddress -OidStr "1.3.6.1.2.1.43.5.1.1.17.1")

    # Page counter
    $pages = Send-SnmpGet -IpAddress $IpAddress -OidStr "1.3.6.1.2.1.43.10.2.1.4.1.1"
    if ($null -ne $pages) { $result.pages_total = [int]$pages }

    $pagesColor = Send-SnmpGet -IpAddress $IpAddress -OidStr "1.3.6.1.2.1.43.10.2.1.4.1.2"
    if ($null -ne $pagesColor) { $result.pages_color = [int]$pagesColor }

    # Toner entries (indices 1-6)
    $tonerList = [System.Collections.Generic.List[object]]::new()
    for ($idx = 1; $idx -le 6; $idx++) {
        $beschr  = Send-SnmpGet -IpAddress $IpAddress -OidStr "1.3.6.1.2.1.43.11.1.1.6.1.$idx"
        $maxKap  = Send-SnmpGet -IpAddress $IpAddress -OidStr "1.3.6.1.2.1.43.11.1.1.8.1.$idx"
        $fuellst = Send-SnmpGet -IpAddress $IpAddress -OidStr "1.3.6.1.2.1.43.11.1.1.9.1.$idx"

        # No entry for this index
        if ($null -eq $beschr -and $null -eq $fuellst) { continue }

        $tonerList.Add([ordered]@{
            description   = Safe $beschr
            max_kapazitaet = if ($null -ne $maxKap)  { [int]$maxKap }  else { $null }
            fill_level     = if ($null -ne $fuellst) { [int]$fuellst } else { $null }
        })
    }
    $result.toner = @($tonerList)

    return $result
}

# -- Filename and Pathe ---------------------------------------------------

$safeComputer = ($env:COMPUTERNAME -replace '[^\w\-]', '')
if (-not $safeComputer) { $safeComputer = "UNBEKANNT" }
$fileName   = "printer_${safeComputer}_$(Get-Date -Format 'yyyyMMdd').json"

$tempDir = $env:TEMP
if (-not $tempDir -or -not (Test-Path $tempDir)) { $tempDir = $env:USERPROFILE }
$lokalerPath = Join-Path $tempDir $fileName

# -- Printers-Collection -------------------------------------------------------

Write-Host ""
Write-Host "  ========================================================" -ForegroundColor DarkGray
Write-Host "     Example Organization - Printers-Collection" -ForegroundColor Cyan
Write-Host "  ========================================================" -ForegroundColor DarkGray
Write-Host ""
Write-Status "Collecting printers..." "White"
if ($DryRun)   { Write-Status "[DRY-RUN] Upload will be skipped." "Yellow" }
if ($SkipSnmp) { Write-Status "[SKIP-SNMP] SNMP queries will be skipped." "Yellow" }

$collectedAm = Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'

# Load TCP/IP printer ports (Name -> IP-Address, port number)
$tcpPorts = @{}
try {
    Get-CimInstance Win32_TCPIPPrinterPort -EA Stop | ForEach-Object {
        $port = $_
        $ipAddress = Safe $port.HostAddress
        # Fallback: IP from Port-Namen extrahieren (e.g. "192.0.2.1", "IP_192.0.2.1", "192.0.2.1_1")
        if (-not $ipAddress -and $port.Name -match '(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})') {
            $ipAddress = $Matches[1]
        }
        $tcpPorts[$port.Name] = [ordered]@{
            ip_address  = $ipAddress
            port_number = if ($port.PortNumber) { [int]$port.PortNumber } else { 9100 }
            snmp_active  = [bool]$port.SNMPEnabled
        }
    }
} catch {}

Write-Status "$($tcpPorts.Count) TCP/IP printer ports found." "DarkGray"

# Load all installed printers via CIM
$allePrucker = @()
try {
    $allePrucker = @(Get-CimInstance Win32_Printer -EA Stop)
} catch {
    try {
        # Fallback: Get-Printer Cmdlet
        $allePrucker = @(Get-Printer -EA Stop)
    } catch {}
}

$printerList = [System.Collections.Generic.List[object]]::new()

foreach ($p in $allePrucker) {
    $portName = "$($p.PortName)".Trim()

    # Only Networkprinter beruecksichtigen (Port in TCP/IP-Table present)
    if (-not $tcpPorts.ContainsKey($portName)) { continue }

    $portInfo  = $tcpPorts[$portName]
    $ipAddress = $portInfo.ip_address

    # Evaluate capabilities: 4 = Color, 3 = Duplex
    $caps   = @($p.Capabilities)
    $color  = $caps -contains 4
    $duplex = $caps -contains 3

    # Map PrinterStatus (Win32_Printer.PrinterStatus)
    $statusRaw = try { [int]$p.PrinterStatus } catch { 2 }
    $status = switch ($statusRaw) {
        1  { "paused" }
        2  { "unknown" }
        3  { "online" }
        4  { "printing" }
        5  { "warming_up" }
        6  { "paper_jam" }
        7  { "offline" }
        default { "unknown" }
    }

    # Query SNMP data (per printer IP)
    $snmpData = $null
    if ($ipAddress -and -not $SkipSnmp) {
        Write-Status "SNMP: $($p.Name) ($ipAddress)..." "DarkGray"
        $snmpData = Get-PrinterSnmpData -IpAddress $ipAddress
    }

    $printerList.Add([ordered]@{
        name           = Safe $p.Name
        treiber        = Safe $p.DriverName
        port_name      = Safe $portName
        ip_address     = Safe $ipAddress
        port_number    = $portInfo.port_number
        snmp_activeiert = $portInfo.snmp_active
        shared         = [bool]$p.Shared
        share_name     = Safe $p.ShareName
        location       = Safe $p.Location
        comment      = Safe $p.Comment
        color          = $color
        duplex         = $duplex
        status         = $status
        snmp           = $snmpData
    })
}

Write-Status "$($printerList.Count) network printers found." "White"

# -- Assemble JSON ----------------------------------------------------------

$payload = [ordered]@{
    schema_version = "1.0"
    collected_at     = $collectedAm
    collected_by    = $safeComputer
    printer        = @($printerList)
}

$jsonContent = $payload | ConvertTo-Json -Depth 10

# -- JSON local save --------------------------------------------------

try {
    [System.IO.File]::WriteAllText($lokalerPath, $jsonContent, [System.Text.Encoding]::UTF8)
} catch {
    try {
        $lokalerPath = "$env:USERPROFILE\$fileName"
        [System.IO.File]::WriteAllText($lokalerPath, $jsonContent, [System.Text.Encoding]::UTF8)
    } catch {
        $lokalerPath = $null
    }
}

# -- Upload after Nextcloud -------------------------------------------------

$uploadOK = $false
if (-not $DryRun -and $lokalerPath -and (Test-Path -LiteralPath $lokalerPath)) {
    try {
        $ErrorActionPreference = 'Stop'
        $uploadUrl = "$NextcloudUrl/$fileName"
        $secPass   = ConvertTo-SecureString $NextcloudPassword -AsPlainText -Force
        $cred      = New-Object System.Management.Automation.PSCredential($NextcloudUser, $secPass)

        $response = Invoke-WebRequest `
            -Uri            $uploadUrl `
            -Method         PUT `
            -InFile         $lokalerPath `
            -Credential     $cred `
            -UseBasicParsing `
            -TimeoutSec     60 `
            -EA             Stop

        if ($response.StatusCode -in 200, 201, 204) {
            $uploadOK = $true
        }
    } catch {
        # Upload optional — no error for the scheduled task
    } finally {
        $ErrorActionPreference = 'SilentlyContinue'
    }
}

# -- Show result ----------------------------------------------------

Write-Host ""
if ($DryRun) {
    Write-Status "[DRY-RUN] No upload performed." "Yellow"
    if ($lokalerPath) { Write-Status "Locally saved: $lokalerPath" "DarkGray" }
} elseif ($uploadOK) {
    Write-Status "Upload successful: $fileName" "Green"
} else {
    Write-Status "Upload failed. File saved locally:" "Yellow"
    Write-Status "  $lokalerPath" "DarkGray"
}
Write-Host "  ========================================================" -ForegroundColor DarkGray
Write-Host ""
