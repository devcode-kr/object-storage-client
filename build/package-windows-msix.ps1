<#
.SYNOPSIS
    Windows 빌드를 Microsoft Store 제출용 MSIX 패키지로 만든다.

.DESCRIPTION
    Store에 올린 패키지는 인증을 통과하면 Microsoft가 자기 인증서로 다시 서명한다. 그래서 제출용
    패키지에는 CA 인증서가 필요 없고, 여기서도 서명하지 않는다. 사이드로드해서 직접 설치해보려면
    -SelfSign 을 주면 임시 인증서를 만들어 서명한다. 그 인증서는 이 컴퓨터에서만 통한다.

    Identity 세 값(-IdentityName, -Publisher, -PublisherDisplayName)은 Partner Center의
    제품 개요 > Product management > "View app identity details"에 나오는 것을 그대로 넣어야 한다.
    대소문자와 공백까지 같아야 하고, 하나라도 다르면 업로드가 거부된다.

.EXAMPLE
    build\package-windows-msix.ps1 `
      -IdentityName 12345Astral.ObjectStorageClient `
      -Publisher "CN=A1B2C3D4-0000-0000-0000-000000000000" `
      -PublisherDisplayName Astral `
      -PackageVersion 1.0.0.0
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $IdentityName,
    [Parameter(Mandatory)][string] $Publisher,
    [Parameter(Mandatory)][string] $PublisherDisplayName,

    # Store 규칙: 네 번째 자리는 Store 몫이라 반드시 0, 첫 자리는 0이면 안 된다.
    [Parameter(Mandatory)][string] $PackageVersion,

    [string] $DisplayName = 'Object Storage Client',
    [string] $OutputDir = 'artifacts',
    [switch] $SelfSign
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$msixDir = Join-Path $repoRoot 'build/msix'
$staging = Join-Path $repoRoot 'obj/msix-staging'

function Fail([string] $message) {
    Write-Error $message
    exit 1
}

# --- 버전 검증 --------------------------------------------------------------
# 실패를 제출 단계가 아니라 빌드 단계에서 보게 한다.
if ($PackageVersion -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    Fail "PackageVersion 은 네 자리여야 한다 (예: 1.0.0.0). 받은 값: $PackageVersion"
}
$parts = $PackageVersion.Split('.')
if ([int]$parts[0] -eq 0) {
    Fail @"
Store 는 첫 자리가 0 인 버전을 받지 않는다 (받은 값: $PackageVersion).
저장소의 <Version> 이 0.x 라면 Store 제출용으로는 1.0.0.0 이상을 따로 정해야 한다.
"@
}
if ([int]$parts[3] -ne 0) {
    Fail "네 번째 자리는 Store 가 쓰는 자리라 0 이어야 한다. 받은 값: $PackageVersion"
}

# --- Windows SDK 도구 찾기 ---------------------------------------------------
function Find-SdkTool([string] $name) {
    $found = Get-Command $name -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }

    $roots = @("${env:ProgramFiles(x86)}\Windows Kits\10\bin", "$env:ProgramFiles\Windows Kits\10\bin")
    $candidates = foreach ($root in $roots) {
        if (Test-Path $root) {
            Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending |
                ForEach-Object { Join-Path $_.FullName "x64\$name" }
        }
    }
    $hit = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $hit) { Fail "$name 을 찾지 못했다. Windows SDK 가 필요하다." }
    return $hit
}

$makeappx = Find-SdkTool 'makeappx.exe'
$makepri = Find-SdkTool 'makepri.exe'
Write-Host "makeappx: $makeappx"

# --- 앱 퍼블리시 -------------------------------------------------------------
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

Write-Host "`n== publish (win-x64, self-contained) =="
dotnet publish (Join-Path $repoRoot 'src/ObjectStorageClient.App') `
    --configuration Release --runtime win-x64 --self-contained `
    --output $staging -p:Version=$($parts[0..2] -join '.') --nologo
if ($LASTEXITCODE -ne 0) { Fail 'publish 실패' }

# --- 매니페스트와 자산 -------------------------------------------------------
Copy-Item (Join-Path $msixDir 'Assets') $staging -Recurse

$manifest = Get-Content (Join-Path $msixDir 'AppxManifest.xml') -Raw
$manifest = $manifest.
    Replace('@IDENTITY_NAME@', $IdentityName).
    Replace('@PUBLISHER@', $Publisher).
    Replace('@PUBLISHER_DISPLAY_NAME@', $PublisherDisplayName).
    Replace('@PACKAGE_VERSION@', $PackageVersion).
    Replace('@DISPLAY_NAME@', $DisplayName)

if ($manifest -match '@[A-Z_]+@') {
    Fail "매니페스트에 치환되지 않은 자리가 남았다: $($Matches[0])"
}
Set-Content -Path (Join-Path $staging 'AppxManifest.xml') -Value $manifest -Encoding UTF8

# --- 리소스 인덱스 -----------------------------------------------------------
# scale-200 같은 변형 자산은 PRI 에 색인돼야 실제로 쓰인다.
Write-Host "`n== makepri =="
$priConfig = Join-Path $staging 'priconfig.xml'
& $makepri createconfig /cf $priConfig /dq 'ko-KR_en-US' /o | Out-Null
& $makepri new /pr $staging /cf $priConfig /of (Join-Path $staging 'resources.pri') /o
if ($LASTEXITCODE -ne 0) { Fail 'makepri 실패' }
Remove-Item $priConfig

# --- 패키징 ------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path (Join-Path $repoRoot $OutputDir) | Out-Null
$package = Join-Path $repoRoot "$OutputDir/ObjectStorageClient-$PackageVersion-win-x64.msix"

Write-Host "`n== makeappx =="
& $makeappx pack /d $staging /p $package /o
if ($LASTEXITCODE -ne 0) { Fail 'makeappx 실패' }

# --- 선택: 사이드로드용 자체 서명 --------------------------------------------
if ($SelfSign) {
    Write-Host "`n== 자체 서명 (이 컴퓨터에서만 유효) =="
    # 인증서 주체가 매니페스트의 Publisher 와 정확히 같아야 설치된다.
    $cert = New-SelfSignedCertificate -Type Custom -Subject $Publisher `
        -KeyUsage DigitalSignature -FriendlyName 'Object Storage Client (sideload test)' `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')
    $signtool = Find-SdkTool 'signtool.exe'
    & $signtool sign /fd SHA256 /a /sha1 $cert.Thumbprint $package
    if ($LASTEXITCODE -ne 0) { Fail 'signtool 실패' }
    Write-Host '설치하려면 인증서를 신뢰할 수 있는 루트에 넣어야 한다. 배포용이 아니다.'
}

Write-Host "`n완료: $package"
Write-Host 'Partner Center > 제출 > 패키지 에 이 파일을 올리면 된다. Store 가 서명은 알아서 한다.'
