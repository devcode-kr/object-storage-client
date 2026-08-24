# Object Storage Client

*한국어 · [English](README.en.md)*

S3 호환 오브젝트 스토리지용 데스크톱 클라이언트다. 화면은 FileZilla처럼 좌우 2단으로 나뉜다.
[Avalonia UI](https://avaloniaui.net)와 .NET 9로 만들었고, 코드베이스 하나로 Windows 11과 데비안
계열 리눅스, macOS를 모두 지원한다.

## 기능

- **좌우 2단 전송** — 왼쪽은 내 컴퓨터, 오른쪽은 버킷과 프리픽스다. 업로드와 다운로드는 백그라운드
  큐를 거친다. 폴더를 더블클릭하면 열리고 파일을 더블클릭하면 전송이 걸린다. 전송이 끝나면 반대쪽
  패널이 알아서 목록을 새로 읽는다.
- **전송 큐** — 대기·실패·성공 탭으로 나뉘고 항목마다 진행률이 보인다. 취소와 재시도도 된다. 전송은
  건별로 성공하거나 실패하며, 하나가 실패해도 나머지는 계속 간다. 실패한 항목을 우클릭하면 오류
  메시지나 경로, 실패 목록 전체를 복사할 수 있다.
- **메시지 로그** — FTP 클라이언트처럼 요청과 응답, 오류를 색으로 구분해 보여준다.
- **제공자 프리셋** — Amazon S3, MinIO, Cloudflare R2, Backblaze B2, Wasabi, DigitalOcean Spaces,
  Google Cloud Storage(S3 호환), NAVER Cloud Object Storage, Akamai/Linode. 직접 입력용 항목도 있다.
- **프리셋을 골라도 값은 그대로 고칠 수 있다** — 프리셋은 양식을 미리 채워줄 뿐이다. 엔드포인트와
  리전, 액세스 키, 시크릿, 버킷, 프리픽스 전부 손댈 수 있어서 목록에 없는 게이트웨이도 문제없다.
- **HTTP 프록시** — 필요하면 사이트마다 호스트와 포트를 따로 지정한다. 인증 정보와 `*`, `?`
  와일드카드를 쓰는 bypass 목록도 지원한다.
- **Site Manager** — 접속 정보를 저장해두고 관리한다. 자격증명은 암호화해서 보관하며 연결 테스트
  버튼이 있다.
- **마스터 비밀번호** — 실행할 때마다 묻는다. 자격증명은 이 비밀번호에서 뽑아낸 키로 암호화하고,
  키 자체는 디스크에 남기지 않는다.

## 설치

**Windows는 Microsoft Store로 배포한다.** 개발자 계정은 승인되었고, 현재 Store 인증과 공개 목록
링크를 기다리고 있다. 목록이 열리기 전까지 존재하지 않는 Store 링크를 안내하지 않는다. 인증을
통과한 MSIX는 Microsoft가 서명하고 Store가 업데이트를 맡는다.

**macOS는** [최신 릴리즈](https://github.com/devcode-kr/object-storage-client/releases/latest)의
서명되지 않은 `.zip` 아카이브로 제공한다. `SHA256SUMS.txt`로 내려받은 파일을 확인할 수 있지만
개발자 서명은 아니므로, 처음 실행할 때 Gatekeeper가 "손상되었기 때문에 열 수 없습니다"라고 할 수
있다. 앱을 `/Applications`로 옮긴 뒤 격리 속성을 지우면 된다.

```bash
xattr -dr com.apple.quarantine "/Applications/Object Storage Client.app"
```

**리눅스는 서명된 APT/DNF 저장소가 권장 설치 경로다.** 아래 패키지는 .NET 런타임과 필요한 시스템
의존성을 함께 처리한다. 지원 범위는 모두 **x86-64**이며 다음과 같다.

| 계열 | 지원 버전 |
| --- | --- |
| Debian / Ubuntu | Debian 12+, Ubuntu 22.04+ |
| Fedora | Fedora 44, Fedora 43 (최신 두 버전) |
| Enterprise Linux | Rocky Linux 9, AlmaLinux 9, RHEL 9 |

RHEL 9는 구독된 데스크톱에서 실제 GUI와 S3 동작을 확인하는 **RHEL 9 수동 검증**을 첫 공개 태그
전에 통과해야 한다. 앱은 X11을 직접 쓰며 Wayland에서는 XWayland를 거친다. 최소 설치에서 CJK 글자가
필요하면 `fonts-noto-cjk`(Debian/Ubuntu) 또는 `google-noto-cjk-fonts`(RPM 계열)를 추가한다.

### APT (Debian / Ubuntu)

먼저 `wget`, `gpg`와 CA 인증서를 준비한 뒤 다음 블록 전체를 실행한다. 키 파일에 비밀키가 없고
기본 공개키가 정확히 하나인지 검사한 다음, 전체 지문이 일치할 때만 로컬 keyring과 저장소 설정을
설치한다.

```bash
sudo apt install -y ca-certificates wget gnupg
set -eu
umask 077
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT HUP INT TERM
wget -O "$tmpdir/repository-key.asc" https://devcode-kr.github.io/object-storage-client/repository-key.asc
gpg --batch --show-keys --with-colons "$tmpdir/repository-key.asc" > "$tmpdir/key-info"
fingerprint=$(awk -F: '
$1 == "sec" || $1 == "ssb" { secret++; want_fpr = 0 }
$1 == "pub" { primary++; want_fpr = 1; next }
$1 == "sub" { want_fpr = 0 }
want_fpr && $1 == "fpr" { fingerprints++; fingerprint = $10; want_fpr = 0 }
END {
  if (secret != 0 || primary != 1 || fingerprints != 1) exit 1
  print fingerprint
}' "$tmpdir/key-info")
test "$fingerprint" = "843B0BB9F1A4488C8C7B60133F8AC712C8C56B90"
gpg --batch --dearmor --output "$tmpdir/object-storage-client.gpg" "$tmpdir/repository-key.asc"
sudo install -d -m 0755 /etc/apt/keyrings
sudo install -m 0644 "$tmpdir/object-storage-client.gpg" /etc/apt/keyrings/object-storage-client.gpg
printf '%s\n' 'deb [arch=amd64 signed-by=/etc/apt/keyrings/object-storage-client.gpg] https://devcode-kr.github.io/object-storage-client/apt stable main' | sudo tee /etc/apt/sources.list.d/object-storage-client.list > /dev/null
sudo apt update
sudo apt install object-storage-client
```

### DNF (Fedora / Rocky / AlmaLinux / RHEL)

```bash
sudo dnf install -y ca-certificates wget gnupg2
set -eu
umask 077
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT HUP INT TERM
wget -O "$tmpdir/repository-key.asc" https://devcode-kr.github.io/object-storage-client/repository-key.asc
gpg --batch --show-keys --with-colons "$tmpdir/repository-key.asc" > "$tmpdir/key-info"
fingerprint=$(awk -F: '
$1 == "sec" || $1 == "ssb" { secret++; want_fpr = 0 }
$1 == "pub" { primary++; want_fpr = 1; next }
$1 == "sub" { want_fpr = 0 }
want_fpr && $1 == "fpr" { fingerprints++; fingerprint = $10; want_fpr = 0 }
END {
  if (secret != 0 || primary != 1 || fingerprints != 1) exit 1
  print fingerprint
}' "$tmpdir/key-info")
test "$fingerprint" = "843B0BB9F1A4488C8C7B60133F8AC712C8C56B90"
sudo install -d -m 0755 /etc/pki/rpm-gpg
sudo install -m 0644 "$tmpdir/repository-key.asc" /etc/pki/rpm-gpg/RPM-GPG-KEY-object-storage-client
printf '%s\n' '[object-storage-client]
name=Object Storage Client
baseurl=https://devcode-kr.github.io/object-storage-client/rpm/stable/x86_64
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-object-storage-client' | sudo tee /etc/yum.repos.d/object-storage-client.repo > /dev/null
sudo dnf install object-storage-client
```

패키지 관리자를 쓸 수 없는 환경에서는 최신 릴리즈의 `linux-x64.tar.gz`를 휴대용 대안으로 쓸 수
있다. 이 tar.gz는 서명되지 않았으며 `SHA256SUMS.txt` 체크섬만 제공한다. 압축을 푼 디렉터리 안에서
직접 실행하고, 필요한 X11 라이브러리는 운영체제에서 설치해야 한다.

### 업데이트

업데이트는 앱이 아니라 운영체제 패키지 관리자가 맡는다. **앱 자체 업데이트 기능은 없다.** 평소의
시스템 업데이트에 포함하거나 다음 명령을 직접 실행한다.

```bash
sudo apt update && sudo apt upgrade
sudo dnf upgrade
```

## 소스에서 빌드하기

[.NET SDK 9.0](https://dotnet.microsoft.com/download) 이상만 있으면 된다. 워크로드도 Avalonia
전용 도구도 필요 없다. 명령은 세 플랫폼에서 똑같다.

```bash
git clone <this repo>
cd object-storage-client

dotnet build ObjectStorageClient.sln
dotnet test  ObjectStorageClient.sln
dotnet run --project src/ObjectStorageClient.App
```

모든 프로젝트에 `TreatWarningsAsErrors`가 걸려 있다. **경고가 하나라도 뜨면 빌드가 실패한다.**
테스트는 Avalonia의 headless 백엔드에서 돌기 때문에 화면이 없어도 된다. SSH로 붙었거나 컨테이너
안이어도 그대로 실행된다.

### 리눅스 (데비안·우분투)

Ubuntu 24.04부터는 저장소에 SDK가 들어 있다. 데비안이라면
[마이크로소프트 피드](https://learn.microsoft.com/dotnet/core/install/linux-debian)를 쓰거나
`dotnet-install` 스크립트를 받는다.

```bash
sudo apt install -y dotnet-sdk-9.0
sudo apt install -y libx11-6 libice6 libsm6 libfontconfig1   # Avalonia 런타임 의존성
sudo apt install -y fonts-noto-cjk                           # 한글이 필요할 때만
```

막 설치한 머신에서는 `Could not get lock /var/lib/dpkg/lock-frontend`가 뜨면서 실패하기도 한다.
첫 부팅에 `unattended-upgrades`가 돌면서 몇 분 동안 락을 잡고 있어서다. 이때는
`-o DPkg::Lock::Timeout=600`을 붙여 기다리게 하면 된다. **프로세스를 죽이거나 락 파일을 지우면
안 된다.** dpkg 작업이 중간에 끊기면 패키지 데이터베이스를 손봐야 한다. SDK만 필요하고 root 권한이
없다면 [dotnet-install 스크립트](https://learn.microsoft.com/dotnet/core/tools/dotnet-install-script)로
`$HOME`에 설치하면 apt를 거치지 않아도 된다.

최소 설치 환경에서 걸리는 게 둘 있다. 위 네 개 라이브러리가 없으면 창이 아예 뜨지 않는다.
self-contained 빌드라도 .NET 런타임만 같이 들어갈 뿐 X11과 폰트 라이브러리는 시스템 것을 쓰기
때문이다. 그리고 CJK 폰트가 없으면 한글 사이트 이름이나 로그가 네모(□)로 나온다. 고장이 아니라
그 글자를 담은 폰트가 배포 파일에 없어서다.

Avalonia 11은 X11을 직접 다룬다. 그래서 Wayland 데스크톱에서는 XWayland를 거쳐 실행된다. 우분투는
XWayland를 기본으로 깔아두니 둘 다 잘 돌아가는데, 창 크기 계산과 DPI 처리 경로가 달라서 각각
확인해볼 값어치는 있다.

```bash
dotnet run --project src/ObjectStorageClient.App

# 릴리즈에 올라가는 것과 같은 self-contained 빌드
dotnet publish src/ObjectStorageClient.App -c Release -r linux-x64 --self-contained
./src/ObjectStorageClient.App/bin/Release/net9.0/linux-x64/publish/ObjectStorageClient.App
```

사이트와 설정은 `~/.devcode/object-storage-client/`에 권한 `0600`으로 저장된다. 이 부분이 깨졌는지
확인하려면 `stat -c %a ~/.devcode/object-storage-client/sites.json`이 제일 빠르다.

### Windows 11

```powershell
winget install Microsoft.DotNet.SDK.9

dotnet build ObjectStorageClient.sln
dotnet test  ObjectStorageClient.sln
dotnet run --project src\ObjectStorageClient.App
```

Avalonia가 Win32를 직접 호출해서 SDK 말고는 깔 게 없다.

```powershell
dotnet publish src\ObjectStorageClient.App -c Release -r win-x64 --self-contained
.\src\ObjectStorageClient.App\bin\Release\net9.0\win-x64\publish\ObjectStorageClient.App.exe
```

사이트와 설정은 `%APPDATA%`가 아니라 `%USERPROFILE%\.devcode\object-storage-client\`로 간다. 다른
플랫폼과 구조를 맞춰서 디렉터리째 옮길 수 있게 하려는 것이다. Windows에는 소유자 전용 파일 모드가
없으니 그 단계는 건너뛴다.

직접 빌드한 `.exe`는 경고 없이 실행된다. SmartScreen은 네트워크로 받은 파일만 막는데, 그 얘기는
[설치](#설치)에 있다.

### 테스트용 게이트웨이

업로드와 다운로드, 전송 큐를 확인하는 데는 도커로 띄운 MinIO 하나면 충분하다.

```bash
docker run --rm -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
  quay.io/minio/minio server /data --console-address :9001
```

<http://localhost:9001>에서 버킷을 만들고 아래 설정으로 접속한다. 세 플랫폼이 같은 엔드포인트를
바라봐야 결과를 견줄 수 있다.

### 접속하기

한 번 쓰고 말 거라면 **Quickconnect** 바를, 저장해둘 거라면 **Site Manager**를 쓴다.

로컬 MinIO라면 이렇게 넣는다.

| 항목 | 값 |
| --- | --- |
| Provider | MinIO |
| Endpoint | `http://localhost:9000` |
| Region | `us-east-1` |
| Access key / Secret | MinIO 자격증명 |
| Bucket | 비워두면 전체 버킷을 훑는다 |

MinIO처럼 직접 띄운 게이트웨이에는 path-style 주소 방식이 자동으로 켜진다.

**Disable request checksums**와 **Disable chunked upload encoding**은 Amazon S3만 빼고 기본으로
켜져 있다. 끄면 AWS SDK가 `x-amz-checksum-*` 헤더와 `aws-chunked` 본문을 보내는데, 이걸 구현하지
않은 S3 호환 게이트웨이가 많다. 그런 곳에서는 업로드가 설명도 없이 `NotImplemented`로 실패한다.
두 스위치 모두 Site Manager의 *Advanced* 아래에 있다.

## 패키징

```bash
dotnet publish src/ObjectStorageClient.App -c Release -r win-x64   --self-contained
dotnet publish src/ObjectStorageClient.App -c Release -r linux-x64 --self-contained
```

macOS는 publish 결과가 맨 실행 파일이라 Finder가 응용 프로그램으로 보지 않는다. 그래서 `.app`
번들로 감싸고 압축하는 스크립트를 따로 둔다.

```bash
build/package-macos.sh osx-arm64 1.0.0 artifacts
```

릴리즈는 `v*` 태그를 밀면 [`.github/workflows/release.yml`](.github/workflows/release.yml)이
만든다. 태그가 `Directory.Build.props`의 `<Version>`과 맞는지 보고, 세 운영체제에서 테스트를 돌리고,
네 개 타깃을 묶어 `SHA256SUMS.txt`와 함께 올린다. 그다음 **묶은 빌드를 실제로 띄워서 뜨는지까지
확인한다.** 리눅스는 위에 적은 패키지만 깔린 맨 데비안 이미지에서 확인하니, 의존성 목록이 틀리면
사용자에게 가기 전에 릴리즈가 먼저 실패한다.
워크플로를 손으로 실행하면 릴리즈는 만들지 않고 같은 산출물만 뽑는다. 태그를 달기 전에 패키징을
확인할 때 쓴다.

앱 아이콘은 `build/icon/appicon.svg`에 한 번만 그려두고, `build/generate-icon.py`가 플랫폼별로
필요한 `.png`, `.ico`, `.icns`를 뽑아낸다. `rsvg-convert`, ImageMagick, `cairosvg`, headless Chrome
중에 깔린 걸 찾아 쓴다. 생성된 파일까지 커밋해두는 이유는 리눅스와 Windows 릴리즈 러너에 이 중
아무것도 없고 `iconutil`도 없어서다.

## 마스터 비밀번호

처음 실행하면 마스터 비밀번호를 정하게 하고, 그다음부터는 저장한 사이트를 풀기 위해 매번 묻는다.
비밀번호 자체는 저장하지 않는다. 솔트와 반복 횟수, 검증용 블롭만 남긴다. 그래서 **잊어버리면 되찾을
방법이 없다.** 잠금 화면에서 처음부터 다시 시작할 수는 있는데, 그러면 예전 키로 잠가둔 사이트도 함께
버려진다.

비밀번호를 묻는 창에서 종료하면 앱이 닫힌다. 키가 없으면 할 수 있는 일이 없어서다.

입력란은 영문자와 숫자, 기호만 받는다. 입력기가 한글 조합 상태여도 엉뚱한 글자가 비밀번호에 섞이지
않고, 붙여넣기로도 들어가지 않는다.

## 데이터 저장 위치

두 파일 모두 플랫폼과 상관없이 같은 디렉터리에 있다. Windows에서는 `$HOME` 자리에
`%USERPROFILE%`이 들어간다.

| 파일 | 내용 |
| --- | --- |
| `$HOME/.devcode/object-storage-client/sites.json` | Site Manager에 저장한 접속 정보 |
| `$HOME/.devcode/object-storage-client/config.json` | 환경설정과 마스터 비밀번호 파라미터 |

사이트마다 엔드포인트와 리전, 액세스 키, 시크릿 키, 세션 토큰, 버킷, 프록시 설정까지 접속에 관한
것을 통째로 묶어 AES-256-GCM으로 암호화한다. 키는 마스터 비밀번호에서 PBKDF2-HMAC-SHA256을 600,000회
돌려 뽑는다. 잠금을 풀기 전에도 목록은 보여야 하니 사이트 이름과 제공자, 민감하지 않은 스위치 몇
개만 평문으로 남긴다. 두 파일 모두 운영체제가 지원하면 소유자만 읽을 수 있는 권한으로 쓴다. 키가
디스크에 남지 않으니 이 파일들을 다른 컴퓨터로 복사해도 새어 나가는 것은 없다.

## 제거

리눅스 네이티브 패키지만 지우려면 설치에 쓴 패키지 관리자를 사용한다. 저장한 사이트와 설정은
남는다.

```bash
sudo apt remove object-storage-client
sudo dnf remove object-storage-client
```

macOS 앱은 휴지통에 넣고, 휴대용 tar.gz는 압축을 푼 디렉터리를 지우면 된다. 레지스트리나 서비스,
별도 시스템 설정은 없다.

사용자 데이터까지 없애는 일은 패키지 제거와 **별개의 선택 작업**이다. 다시 설치할 계획이 없다면
직접 지운다. 이 명령은 저장한 접속 정보와 설정을 되돌릴 수 없게 삭제한다.

```bash
rm -rf ~/.devcode/object-storage-client        # Windows: %USERPROFILE%\.devcode\object-storage-client
```

## 코드 서명과 개인정보

Windows Store 패키지는 Microsoft가 서명하고, 리눅스 네이티브 패키지와 저장소는 프로젝트 GPG 키로
서명한다. macOS와 휴대용 tar.gz는 서명 없이 체크섬만 제공한다. 자세한 보증 범위는
[CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md)에 있다.

수집하는 정보는 없다. 자세한 내용은 [개인정보 처리방침](PRIVACY.md)에 적어두었다.

## 프로젝트 구조

```
src/ObjectStorageClient.Core   도메인 모델, S3 접근, 전송 큐, 프로필 저장
src/ObjectStorageClient.App    Avalonia 뷰와 뷰모델
tests/                         양쪽 단위 테스트
```

아키텍처 메모와 코드를 고치기 전에 알아둘 제약은 [CLAUDE.md](CLAUDE.md)에 모아두었다.

## 기여

[행동 강령](CODE_OF_CONDUCT.md)을 따른다.

## 라이선스

[MIT](LICENSE). Copyright (c) 2026 Astral.
