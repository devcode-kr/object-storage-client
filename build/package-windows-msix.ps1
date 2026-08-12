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
    # 보통은 이렇게. 버전은 Directory.Build.props 에서 읽고 리비전은 0 이 된다.
    build\package-windows-msix.ps1 `
      -IdentityName 12345Astral.ObjectStorageClient `
      -Publisher "CN=A1B2C3D4-0000-0000-0000-000000000000" `
      -PublisherDisplayName Astral

.EXAMPLE
    # 코드는 그대로인데 다시 포장해서 올려야 할 때만 리비전을 준다.
    build\package-windows-msix.ps1 ... -Revision 1
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $IdentityName,
    [Parameter(Mandatory)][string] $Publisher,
    [Parameter(Mandatory)][string] $PublisherDisplayName,

    # 비우면 Directory.Build.props 의 <Version> 을 읽는다. 굳이 넘길 이유는 없다.
    [string] $Version,

    # 네 번째 자리. 릴리즈 워크플로는 언제나 0 으로 낸다. 코드 변경 없이 같은 버전을 다시
    # 제출해야 할 때만 여기서 올린다. 기준 버전을 통째로 다시 적지 않아도 되게 분리해 두었다.
    [int] $Revision = 0,

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

# --- 버전 결정과 검증 --------------------------------------------------------
# 실패를 제출 단계가 아니라 빌드 단계에서 보게 한다.
if (-not $Version) {
    $propsPath = Join-Path $repoRoot 'Directory.Build.props'
    [xml] $props = Get-Content $propsPath
    $node = $props.SelectSingleNode('//PropertyGroup/Version')
    if (-not $node) { Fail "$propsPath 에서 <Version> 을 찾지 못했다." }
    $Version = $node.InnerText.Trim()
}

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Fail "Version 은 세 자리여야 한다 (예: 1.0.0). 받은 값: $Version"
}
if ([int]$Version.Split('.')[0] -eq 0) {
    Fail @"
Store 는 첫 자리가 0 인 버전을 받지 않는다 (받은 값: $Version).
Directory.Build.props 의 <Version> 을 1.0.0 이상으로 올려야 한다.
"@
}
if ($Revision -lt 0 -or $Revision -gt 65535) {
    Fail "Revision 은 0~65535 여야 한다. 받은 값: $Revision"
}

$PackageVersion = "$Version.$Revision"
Write-Host "패키지 버전: $PackageVersion"
if ($Revision -ne 0) {
    Write-Host "  리비전 $Revision — 코드 변경 없는 재제출로 간주한다. 릴리즈 워크플로는 언제나 0 이다."
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
    --output $staging -p:Version=$Version --nologo
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
