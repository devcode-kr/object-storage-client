# Object Storage Client

*한국어 · [English](README.en.md)*

S3 호환 오브젝트 스토리지를 위한 크로스 플랫폼 데스크톱 클라이언트. FileZilla 방식의 2단 패널
인터페이스를 쓴다. [Avalonia UI](https://avaloniaui.net)와 .NET 9로 만들었고, 하나의 코드베이스로
Windows 11, 데비안 계열 Linux, macOS에서 동작한다.

## 기능

- **2단 패널 전송** — 왼쪽은 로컬 파일 시스템, 오른쪽은 버킷과 프리픽스. 업로드와 다운로드는 백그라운드
  큐를 거친다. 폴더를 더블클릭하면 들어가고, 파일을 더블클릭하면 전송된다. 전송이 끝나면 반대편 패널이
  스스로 새로고침된다.
- **전송 큐** — 대기 / 실패 / 성공 탭, 항목별 진행률, 취소와 재시도. 전송은 각각 독립적으로 성공하거나
  실패하며, 한 건의 실패가 나머지를 멈추지 않는다. 실패한 전송을 우클릭하면 오류 메시지, 경로,
  실패 목록 전체를 복사할 수 있다.
- **메시지 로그** — FTP 클라이언트처럼 요청·응답·오류를 색으로 구분해 보여준다.
- **제공자 프리셋** — Amazon S3, MinIO, Cloudflare R2, Backblaze B2, Wasabi, DigitalOcean Spaces,
  Google Cloud Storage(S3 호환), NAVER Cloud Object Storage, Akamai/Linode, 그리고 완전 수동 입력.
- **모든 값은 여전히 직접 수정할 수 있다** — 프리셋은 양식을 미리 채워줄 뿐이다. 엔드포인트, 리전,
  액세스 키, 시크릿, 버킷, 프리픽스 전부 편집 가능하므로 목록에 없는 S3 호환 게이트웨이도 쓸 수 있다.
- **HTTP 프록시(선택)** — 사이트별 호스트·포트, 인증 정보, 그리고 `*` / `?` 와일드카드를 쓰는
  bypass 목록.
- **Site Manager** — 자격증명이 암호화되어 저장되는 접속 정보 관리와 "연결 테스트" 버튼.
- **마스터 비밀번호** — 실행할 때마다 묻는다. 자격증명은 여기서 파생된 키로 암호화되며, 그 키는 결코
  디스크에 기록되지 않는다.

## 설치

[최신 릴리즈](https://github.com/devcode-kr/object-storage-client/releases/latest)에서 플랫폼에 맞는
self-contained 빌드를 받으면 된다. .NET 런타임을 따로 설치할 필요가 없다. 릴리즈마다 검증용
`SHA256SUMS.txt`가 함께 제공된다.

**아직 코드 서명이 되어 있지 않아** Windows와 macOS 모두 경고를 띄운다.

- **Windows** — 압축을 풀기 전에 `.zip` 속성 창에서 차단을 해제하고, SmartScreen이 뜨면
  *추가 정보 → 실행*을 누른다.
- **macOS** — "손상되었기 때문에 열 수 없습니다"라고 나온다. 미서명 상태로 격리(quarantine)된 번들에
  Gatekeeper가 붙이는 메시지다. 설치한 뒤 속성을 지우면 된다:
  `xattr -dr com.apple.quarantine "/Applications/Object Storage Client.app"`
- **Linux** — 막는 것이 없다. 최소 설치 환경에서는 `libx11-6`, `libice6`, `libsm6`,
  `libfontconfig1`이 필요할 수 있다.

릴리즈 노트에 각 절차가 자세히 적혀 있다.

## 소스에서 빌드하기

[.NET SDK 9.0](https://dotnet.microsoft.com/download) 이상이 필요하다. 그 외에는 아무것도 필요 없다 —
워크로드도, Avalonia 전용 도구도. 명령은 세 플랫폼 모두 동일하다.

```bash
git clone <this repo>
cd object-storage-client

dotnet build ObjectStorageClient.sln
dotnet test  ObjectStorageClient.sln
dotnet run --project src/ObjectStorageClient.App
```

모든 프로젝트에 `TreatWarningsAsErrors`가 걸려 있어 **경고가 하나라도 있으면 빌드가 실패한다.**
테스트는 Avalonia의 headless 백엔드에서 돌아 디스플레이가 필요 없으므로 SSH나 컨테이너에서도
안전하게 실행된다.

### Linux (데비안 / 우분투)

Ubuntu 24.04 이상은 저장소에 SDK가 들어 있다. 데비안에서는
[Microsoft 피드](https://learn.microsoft.com/dotnet/core/install/linux-debian)나 `dotnet-install`
스크립트를 쓴다.

```bash
sudo apt install -y dotnet-sdk-9.0
sudo apt install -y libx11-6 libice6 libsm6 libfontconfig1   # Avalonia 런타임 의존성
sudo apt install -y fonts-noto-cjk                           # 한글·CJK 표시가 필요할 때만
```

갓 설치한 머신에서는 `Could not get lock /var/lib/dpkg/lock-frontend`로 실패할 수 있다. 첫 부팅에
`unattended-upgrades`가 돌면서 몇 분간 락을 잡기 때문이다. 실패시키지 말고 기다리도록
`-o DPkg::Lock::Timeout=600`을 붙인다. **프로세스를 죽이거나 락 파일을 지우지 말 것** — dpkg
트랜잭션이 중간에 끊기면 패키지 데이터베이스를 복구해야 한다. SDK만 필요하고 root 권한이 없다면
[dotnet-install 스크립트](https://learn.microsoft.com/dotnet/core/tools/dotnet-install-script)가
`$HOME`에 설치하므로 apt를 아예 거치지 않는다.

최소 설치 환경에서 걸리는 것이 두 가지다. 위 네 개의 라이브러리가 없으면 self-contained 빌드인데도
창이 아예 뜨지 않는다 — .NET 런타임은 번들되지만 X11과 폰트 라이브러리는 그렇지 않기 때문이다.
그리고 CJK 폰트가 없으면 한글이나 일본어 사이트 이름과 로그가 네모(□)로 나온다. 고장 난 것이 아니라
그 영역을 담은 폰트가 배포물에 없을 뿐이다.

Avalonia 11은 X11을 직접 대상으로 하므로 Wayland 데스크톱에서는 XWayland를 통해 실행된다. 우분투는
XWayland를 기본 설치한다. 두 세션 모두 동작하지만, 창 크기 계산과 DPI 처리 경로가 달라서 각각
확인해볼 값어치는 있다.

```bash
dotnet run --project src/ObjectStorageClient.App

# 또는 릴리즈에 실리는 것과 같은 self-contained 빌드
dotnet publish src/ObjectStorageClient.App -c Release -r linux-x64 --self-contained
./src/ObjectStorageClient.App/bin/Release/net9.0/linux-x64/publish/ObjectStorageClient.App
```

사이트와 설정은 `~/.devcode/object-storage-client/`에 `0600` 권한으로 저장된다.
`stat -c %a ~/.devcode/object-storage-client/sites.json`으로 회귀 여부를 가장 빠르게 확인할 수 있다.

### Windows 11

```powershell
winget install Microsoft.DotNet.SDK.9

dotnet build ObjectStorageClient.sln
dotnet test  ObjectStorageClient.sln
dotnet run --project src\ObjectStorageClient.App
```

Avalonia가 Win32를 직접 호출하므로 SDK 외에 설치할 것이 없다.

```powershell
dotnet publish src\ObjectStorageClient.App -c Release -r win-x64 --self-contained
.\src\ObjectStorageClient.App\bin\Release\net9.0\win-x64\publish\ObjectStorageClient.App.exe
```

사이트와 설정은 `%APPDATA%`가 아니라 `%USERPROFILE%\.devcode\object-storage-client\`에 저장된다.
다른 플랫폼과 같은 구조로 두어 디렉터리째 다른 머신으로 옮길 수 있게 하려는 것이다. Windows에는
소유자 전용 파일 모드가 없으므로 그 단계는 건너뛴다.

로컬에서 빌드한 `.exe`는 아무 경고 없이 실행된다. SmartScreen은 네트워크를 통해 들어온 바이너리만
막으며, 그건 [설치](#설치) 절에서 다룬다.

### 테스트용 게이트웨이

업로드·다운로드·전송 큐를 확인하는 데는 도커로 띄운 MinIO 하나면 충분하다.

```bash
docker run --rm -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
  quay.io/minio/minio server /data --console-address :9001
```

<http://localhost:9001>에서 버킷을 만든 뒤 아래 설정으로 접속한다. 세 플랫폼이 같은 엔드포인트를
바라보게 해야 결과를 비교할 수 있다.

### 접속하기

한 번 쓰고 말 세션이면 **Quickconnect** 바를, 저장해 둘 접속이면 **Site Manager**를 쓴다.

로컬 MinIO 기준:

| 항목 | 값 |
| --- | --- |
| Provider | MinIO |
| Endpoint | `http://localhost:9000` |
| Region | `us-east-1` |
| Access key / Secret | MinIO 자격증명 |
| Bucket | 선택 — 비워두면 전체 버킷을 탐색 |

MinIO를 비롯한 자체 호스팅 게이트웨이에는 path-style 주소 방식이 자동으로 켜진다.

**Disable request checksums**와 **Disable chunked upload encoding**은 Amazon S3를 제외한 모든
제공자에서 기본으로 켜져 있다. 그러지 않으면 AWS SDK가 `x-amz-checksum-*` 헤더와 `aws-chunked`
요청 본문을 보내는데, 이를 구현하지 않은 S3 호환 게이트웨이가 많아 업로드가 아무 설명 없는
`NotImplemented`로 실패한다. 이 스위치들은 Site Manager의 *Advanced* 아래에 있다.

## 패키징

```bash
dotnet publish src/ObjectStorageClient.App -c Release -r win-x64   --self-contained
dotnet publish src/ObjectStorageClient.App -c Release -r linux-x64 --self-contained
```

macOS에서는 publish 결과가 Finder가 응용 프로그램으로 인식하는 형태가 아니라 맨 실행 파일이다.
그래서 `.app` 번들로 감싸고 압축하는 스크립트를 거친다.

```bash
build/package-macos.sh osx-arm64 0.0.1 artifacts
```

릴리즈는 `v*` 태그를 밀면 [`.github/workflows/release.yml`](.github/workflows/release.yml)이
만든다. 태그가 `Directory.Build.props`의 `<Version>`과 일치하는지 확인하고, 세 운영체제에서 테스트를
돌리고, 네 개 타깃을 패키징해 `SHA256SUMS.txt`와 함께 첨부한다. 그런 다음 **패키징된 빌드를 실제로
띄워 기동을 확인한다** — Linux는 위에 적힌 패키지만 설치된 맨 데비안 이미지 안에서 확인하므로,
그 목록이 틀리면 사용자에게 도달하기 전에 릴리즈가 실패한다.
워크플로를 수동 실행하면 릴리즈를 만들지 않고 같은 산출물만 빌드한다. 태그를 달기 전에 패키징 변경을
확인하는 방법이다.

애플리케이션 아이콘은 `build/icon/appicon.svg`에 한 번 그려두고, `build/generate-icon.py`가 각
플랫폼이 요구하는 `.png`, `.ico`, `.icns`로 래스터화한다. `rsvg-convert`, ImageMagick, `cairosvg`,
headless Chrome 중 있는 것을 찾아 쓴다. 생성된 파일을 커밋해 두는 이유는 Linux와 Windows 릴리즈
러너에 이 중 아무것도 없고 `iconutil`도 없기 때문이다.

## 마스터 비밀번호

최초 실행 시 마스터 비밀번호를 정하게 하고, 이후 실행마다 저장된 사이트를 복호화하기 위해 다시 묻는다.
비밀번호 자체는 저장되지 않는다 — 솔트, 반복 횟수, 검증용 블롭만 저장된다 — 따라서 **복구할 방법이
없다.** 잊어버리면 잠금 화면에서 처음부터 다시 시작할 수 있고, 그러면 이전 키와 함께 저장된 사이트도
버려진다.

비밀번호 프롬프트에서 종료하면 앱이 닫힌다. 키 없이는 쓸 수 있는 세션이 없기 때문이다.

비밀번호 입력란은 영문자·숫자·기호만 받는다. 입력기가 조합 모드에 있어도 예상치 못한 문자가 마스터
비밀번호에 들어가지 않으며, 붙여넣기로도 들어가지 않는다.

## 데이터 저장 위치

두 파일 모두 모든 플랫폼에서 같은 디렉터리에 있다 (Windows에서는 `$HOME` 자리에 `%USERPROFILE%`).

| 파일 | 내용 |
| --- | --- |
| `$HOME/.devcode/object-storage-client/sites.json` | Site Manager에 저장한 접속 정보 |
| `$HOME/.devcode/object-storage-client/config.json` | 환경설정과 마스터 비밀번호 파라미터 |

저장된 사이트마다 엔드포인트, 리전, 액세스 키, 시크릿 키, 세션 토큰, 버킷, 프록시 설정까지 접속에
관한 전체가 하나의 블록으로 AES-256-GCM 암호화된다. 키는 마스터 비밀번호에서 PBKDF2-HMAC-SHA256
(600,000회 반복)으로 파생된다. 잠금을 풀기 전에도 목록을 보여줄 수 있도록 사이트 이름, 제공자,
민감하지 않은 스위치 몇 개만 평문으로 남는다. 두 파일 모두 운영체제가 지원하는 경우 소유자 전용
권한으로 기록된다. 키가 디스크에 닿지 않으므로 이 파일들을 다른 머신에 복사해도 아무것도 노출되지
않는다.

## 제거

설치 관리자가 없으므로 제거할 것도 없다. 압축을 푼 폴더를 지우면 되고, macOS에서는 앱을 휴지통으로
옮기면 된다. 레지스트리에 쓴 것도, 설치된 서비스도, 변경된 시스템 설정도 없다.

저장된 사이트와 설정은 그 폴더 바깥에 있고 **의도적으로 남긴다.** 다시 설치했을 때 잃지 않도록 하기
위해서다. 지우려면 직접 삭제한다.

```bash
rm -rf ~/.devcode/object-storage-client        # Windows: %USERPROFILE%\.devcode\object-storage-client
```

## 코드 서명

릴리즈는 아직 서명되어 있지 않다. [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md)에 누가 릴리즈에
서명할 수 있는지, 무엇이 서명되는지, 그 서명이 무엇을 보증하고 무엇을 보증하지 않는지 적어두었다.

## 프로젝트 구조

```
src/ObjectStorageClient.Core   도메인 모델, S3 접근, 전송 큐, 프로필 저장
src/ObjectStorageClient.App    Avalonia 뷰와 뷰모델
tests/                         양쪽의 단위 테스트
```

아키텍처 메모와 코드를 고치기 전에 알아둘 제약은 [CLAUDE.md](CLAUDE.md)에 있다.

## 기여

[행동 강령](CODE_OF_CONDUCT.md)을 따른다.

## 라이선스

[MIT](LICENSE). Copyright (c) 2026 Astral.
