param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$BuildNumber,
    [string]$Tag,
    [string]$Repo = $(if ($env:CLIPFLOW_GITHUB_REPO) { $env:CLIPFLOW_GITHUB_REPO } else { "kwd421/ClipFlow" }),
    [string]$PrivateKeyFile,
    [string]$FeedUrl = $(if ($env:CLIPFLOW_WINSPARKLE_FEED_URL) { $env:CLIPFLOW_WINSPARKLE_FEED_URL } else { "https://kwd421.github.io/ClipFlow/appcast-windows.xml" }),
    [string]$PagesBase = "https://kwd421.github.io/ClipFlow",
    [switch]$SkipUpload,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

function ConvertTo-ClipFlowBuildNumber {
    param([string]$Value)
    if ($Value -match '^(\d+)\.(\d+)\.(\d+)$') {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        $patch = [int]$Matches[3]
        if ($major -lt 10 -and $minor -lt 10 -and $patch -lt 10) {
            return ($major * 100 + $minor * 10 + $patch).ToString()
        }
    }
    return ($Value -replace '\.', '')
}

function Get-WinSparklePublicKey {
    param(
        [string]$ToolPath,
        [string]$KeyPath
    )
    $existing = if ($env:CLIPFLOW_SPARKLE_PUBLIC_ED_KEY) { $env:CLIPFLOW_SPARKLE_PUBLIC_ED_KEY.Trim() } else { "" }
    if ($existing) {
        return $existing
    }
    $output = & $ToolPath public-key --private-key-file $KeyPath
    foreach ($line in $output) {
        if ($line -match '^Public key:\s+(\S+)\s*$') {
            return $Matches[1]
        }
    }
    throw "Could not read WinSparkle public key from $KeyPath"
}

function Get-WinSparkleSignature {
    param(
        [string]$ToolPath,
        [string]$KeyPath,
        [string]$ArtifactPath
    )
    $output = & $ToolPath sign --verbose --private-key-file $KeyPath $ArtifactPath
    $signature = $null
    $length = $null
    foreach ($line in $output) {
        if ($line -match 'sparkle:edSignature="([^"]+)"\s+length="(\d+)"') {
            $signature = $Matches[1]
            $length = $Matches[2]
            break
        }
    }
    if (-not $signature -or -not $length) {
        throw "winsparkle-tool sign did not return sparkle:edSignature and length"
    }
    return [pscustomobject]@{
        Signature = $signature
        Length    = $length
    }
}

function Format-SparklePubDate {
    param([datetime]$When = [datetime]::UtcNow)
    return $When.ToString("ddd, dd MMM yyyy HH:mm:ss ", [System.Globalization.CultureInfo]::InvariantCulture) + "+0000"
}

function New-WindowsAppcastItem {
    param(
        [string]$VersionValue,
        [string]$BuildNumberValue,
        [string]$RepoValue,
        [string]$TagValue,
        [string]$PagesBaseValue,
        [string]$Signature,
        [string]$Length
    )
    $pubDate = Format-SparklePubDate
    $releaseNotes = "$PagesBaseValue/ClipFlow-$VersionValue.md"
    $downloadUrl = "https://github.com/$RepoValue/releases/download/$TagValue/ClipFlow-$VersionValue.exe"
    return @"
        <item>
            <title>$VersionValue</title>
            <pubDate>$pubDate</pubDate>
            <link>https://github.com/$RepoValue</link>
            <sparkle:version>$BuildNumberValue</sparkle:version>
            <sparkle:shortVersionString>$VersionValue</sparkle:shortVersionString>
            <sparkle:minimumSystemVersion>10.0</sparkle:minimumSystemVersion>
            <sparkle:releaseNotesLink>$releaseNotes</sparkle:releaseNotesLink>
            <enclosure url="$downloadUrl" length="$Length" type="application/octet-stream" sparkle:edSignature="$Signature"/>
        </item>
"@
}

function Update-WindowsAppcast {
    param(
        [string]$AppcastPath,
        [string]$ItemXml
    )
    $content = Get-Content -Path $AppcastPath -Raw
    if ($content -match [regex]::Escape("<title>$Version</title>")) {
        throw "docs/appcast-windows.xml already contains version $Version"
    }
    $updated = [regex]::Replace(
        $content,
        '(<channel>\s*<title>ClipFlow</title>)',
        "`$1`r`n$ItemXml",
        1
    )
    if ($updated -eq $content) {
        throw "Could not insert a new item into $AppcastPath"
    }
    Set-Content -Path $AppcastPath -Value $updated -NoNewline -Encoding utf8
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if (-not $BuildNumber) {
    $BuildNumber = ConvertTo-ClipFlowBuildNumber $Version
}
if (-not $Tag) {
    $Tag = "v$Version"
}

$winSparkleTool = Join-Path $repoRoot "build-helper\third_party\winsparkle\WinSparkle-0.9.3\bin\winsparkle-tool.exe"
if (-not (Test-Path $winSparkleTool)) {
    throw "winsparkle-tool not found: $winSparkleTool"
}

if (-not $PrivateKeyFile) {
    $PrivateKeyFile = $env:CLIPFLOW_WINSPARKLE_PRIVATE_KEY_FILE
}
if (-not $PrivateKeyFile) {
    throw "Set -PrivateKeyFile or CLIPFLOW_WINSPARKLE_PRIVATE_KEY_FILE"
}
if (-not (Test-Path $PrivateKeyFile)) {
    throw "WinSparkle private key not found: $PrivateKeyFile"
}

$publicKey = Get-WinSparklePublicKey -ToolPath $winSparkleTool -KeyPath $PrivateKeyFile
$env:CLIPFLOW_VERSION = $Version
$env:CLIPFLOW_BUILD_NUMBER = $BuildNumber
$env:CLIPFLOW_WINSPARKLE_FEED_URL = $FeedUrl
$env:CLIPFLOW_SPARKLE_PUBLIC_ED_KEY = $publicKey

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "build_windows.ps1") -SkipTests
}

$artifactDir = Join-Path $repoRoot "dist"
$builtExe = Join-Path $artifactDir "ClipFlow.exe"
if (-not (Test-Path $builtExe)) {
    throw "Built executable not found: $builtExe"
}

$releaseExe = Join-Path $artifactDir "ClipFlow-$Version.exe"
Copy-Item -Force $builtExe $releaseExe

$signed = Get-WinSparkleSignature -ToolPath $winSparkleTool -KeyPath $PrivateKeyFile -ArtifactPath $releaseExe
$itemXml = New-WindowsAppcastItem `
    -VersionValue $Version `
    -BuildNumberValue $BuildNumber `
    -RepoValue $Repo `
    -TagValue $Tag `
    -PagesBaseValue $PagesBase `
    -Signature $signed.Signature `
    -Length $signed.Length

$docsDir = Join-Path $repoRoot "docs"
New-Item -ItemType Directory -Force -Path $docsDir | Out-Null
$appcastPath = Join-Path $docsDir "appcast-windows.xml"
if (-not (Test-Path $appcastPath)) {
    throw "Missing appcast template: $appcastPath"
}
Update-WindowsAppcast -AppcastPath $appcastPath -ItemXml $itemXml

$releaseNotesPath = Join-Path $docsDir "ClipFlow-$Version.md"
@"
# ClipFlow $Version

Windows ClipFlow release with WinSparkle automatic update support.
"@ | Set-Content -Path $releaseNotesPath -Encoding utf8

New-Item -ItemType File -Force -Path (Join-Path $docsDir ".nojekyll") | Out-Null

if (-not $SkipUpload) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw "GitHub CLI (gh) is required for release upload"
    }
    if (gh release view $Tag --repo $Repo 2>$null) {
        gh release upload $Tag $releaseExe --repo $Repo --clobber
    }
    else {
        gh release create $Tag $releaseExe `
            --repo $Repo `
            --title "ClipFlow $Version" `
            --notes "Windows ClipFlow release with WinSparkle automatic update support."
    }
}

Write-Host "Built $releaseExe"
Write-Host "Updated $appcastPath"
Write-Host "Wrote $releaseNotesPath"
if ($SkipUpload) {
    Write-Host "Skipped GitHub release upload"
}
else {
    Write-Host "Uploaded $releaseExe to $Repo release $Tag"
}