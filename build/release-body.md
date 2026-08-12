S3 호환 오브젝트 스토리지용 데스크톱 클라이언트다. 화면은 FileZilla처럼 좌우 2단으로 나뉜다.

## 다운로드

| 플랫폼 | 파일 |
| --- | --- |
| Windows 11 (x64) | `ObjectStorageClient-@VERSION@-win-x64.zip` |
| 리눅스 (x64, 데비안 계열) | `ObjectStorageClient-@VERSION@-linux-x64.tar.gz` |
| macOS (Apple Silicon) | `ObjectStorageClient-@VERSION@-osx-arm64.zip` |
| macOS (Intel) | `ObjectStorageClient-@VERSION@-osx-x64.zip` |

.NET 런타임까지 들어 있어서 따로 설치할 게 없다.

## 이 빌드에는 코드 서명이 없습니다

서명 인증서에는 돈이 드는데 아직 거기까지 쓰지 못했다. 그래서 Windows와 macOS 모두 경고를 띄운다.
넘어가는 방법은 아래에 있다. 그냥 실행하기가 꺼려지면 체크섬부터 확인하면 된다.

### Windows

1. 받은 `.zip`을 우클릭해 **속성**에서 **차단 해제**를 체크하고 **확인**을 누른 다음 압축을 푼다.
   이 단계를 건너뛰면 다운로드 딱지가 압축을 푼 파일 전부에 옮겨 붙는다.
2. `ObjectStorageClient.App.exe`를 실행한다. SmartScreen이 *"Windows의 PC 보호"*를 띄우면
   **추가 정보**를 누르고 **실행**을 고른다.

### macOS

서명이 없는 앱을 macOS는 *"손상되었기 때문에 열 수 없습니다"*라고 알린다. 앱이 망가진 게 아니라,
서명 없이 격리된 번들에 Gatekeeper가 붙이는 문구다. 앱을 옮겨놓고 격리 딱지를 떼면 실행된다.

```sh
xattr -dr com.apple.quarantine "/Applications/Object Storage Client.app"
```

### 리눅스

막는 서명 검사가 없다. 다만 최소 설치 환경이라면 Avalonia가 쓰는 라이브러리를 먼저 깔아야 할 수
있다.

```sh
sudo apt install libx11-6 libice6 libsm6 libfontconfig1
tar -xzf ObjectStorageClient-@VERSION@-linux-x64.tar.gz
./ObjectStorageClient-@VERSION@-linux-x64/ObjectStorageClient.App
```

## 받은 파일 확인하기

`SHA256SUMS.txt`에 이번 릴리즈의 모든 파일이 들어 있다.

```sh
sha256sum -c SHA256SUMS.txt --ignore-missing     # 리눅스
shasum -a 256 -c SHA256SUMS.txt --ignore-missing # macOS
```

```powershell
Get-FileHash .\ObjectStorageClient-@VERSION@-win-x64.zip -Algorithm SHA256  # Windows
```

## 데이터가 저장되는 곳

`$HOME/.devcode/object-storage-client/`에 `sites.json`과 `config.json`이 생긴다. Windows에서는
`%USERPROFILE%` 아래다. 저장한 자격증명은 마스터 비밀번호에서 뽑은 키로 AES-256-GCM 암호화하고,
비밀번호 자체는 디스크에 남기지 않는다. **잊어버리면 되찾을 방법이 없다.**

## 라이선스

MIT.

---

<details>
<summary><b>English</b></summary>

A cross-platform desktop client for S3-compatible object storage, with a FileZilla-style
two-pane interface.

## Downloads

| Platform | File |
| --- | --- |
| Windows 11 (x64) | `ObjectStorageClient-@VERSION@-win-x64.zip` |
| Linux (x64, Debian family) | `ObjectStorageClient-@VERSION@-linux-x64.tar.gz` |
| macOS (Apple Silicon) | `ObjectStorageClient-@VERSION@-osx-arm64.zip` |
| macOS (Intel) | `ObjectStorageClient-@VERSION@-osx-x64.zip` |

Every build is self-contained — no .NET runtime installation is required.

## These builds are not code-signed

Signing certificates cost money that this project has not spent yet, so both Windows and macOS
will warn you. The steps below are how you get past that. Verify the checksums first if you
would rather not take that on faith.

### Windows

1. Right-click the downloaded `.zip` → **Properties** → tick **Unblock** → **OK**, then extract.
   (Skipping this propagates the download mark to every extracted file.)
2. Run `ObjectStorageClient.App.exe`. SmartScreen shows *"Windows protected your PC"* —
   choose **More info** → **Run anyway**.

### macOS

macOS reports unsigned apps as *"damaged and can't be opened"*. The app is not damaged; that is
the Gatekeeper message for a quarantined bundle without a signature. Remove the quarantine
attribute after moving the app into place:

```sh
xattr -dr com.apple.quarantine "/Applications/Object Storage Client.app"
```

### Linux

No signature checks stand in the way. On a minimal install you may need the libraries Avalonia
depends on:

```sh
sudo apt install libx11-6 libice6 libsm6 libfontconfig1
tar -xzf ObjectStorageClient-@VERSION@-linux-x64.tar.gz
./ObjectStorageClient-@VERSION@-linux-x64/ObjectStorageClient.App
```

## Verifying your download

`SHA256SUMS.txt` covers every asset in this release.

```sh
sha256sum -c SHA256SUMS.txt --ignore-missing     # Linux
shasum -a 256 -c SHA256SUMS.txt --ignore-missing # macOS
```

```powershell
Get-FileHash .\ObjectStorageClient-@VERSION@-win-x64.zip -Algorithm SHA256  # Windows
```

## Where your data is stored

`$HOME/.devcode/object-storage-client/` (`%USERPROFILE%` on Windows) holds `sites.json` and
`config.json`. Saved credentials are encrypted with AES-256-GCM under a key derived from your
master password, which is never written to disk — **if you forget it, there is no recovery.**

## License

MIT.

</details>
