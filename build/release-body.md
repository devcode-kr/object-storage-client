S3 호환 오브젝트 스토리지를 위한 크로스 플랫폼 데스크톱 클라이언트. FileZilla 방식의 2단 패널
인터페이스를 쓴다.

## 다운로드

| 플랫폼 | 파일 |
| --- | --- |
| Windows 11 (x64) | `ObjectStorageClient-@VERSION@-win-x64.zip` |
| Linux (x64, 데비안 계열) | `ObjectStorageClient-@VERSION@-linux-x64.tar.gz` |
| macOS (Apple Silicon) | `ObjectStorageClient-@VERSION@-osx-arm64.zip` |
| macOS (Intel) | `ObjectStorageClient-@VERSION@-osx-x64.zip` |

모든 빌드는 self-contained라 .NET 런타임을 따로 설치할 필요가 없다.

## 이 빌드들은 코드 서명이 되어 있지 않습니다

서명 인증서에는 비용이 드는데 이 프로젝트는 아직 그 비용을 쓰지 않았다. 그래서 Windows와 macOS
모두 경고를 띄운다. 아래가 그것을 넘기는 방법이다. 그냥 믿고 실행하기 꺼려진다면 먼저 체크섬을
검증하면 된다.

### Windows

1. 받은 `.zip`을 우클릭 → **속성** → **차단 해제** 체크 → **확인**, 그다음 압축을 푼다.
   (이 단계를 건너뛰면 다운로드 표시가 압축을 푼 모든 파일에 전파된다.)
2. `ObjectStorageClient.App.exe`를 실행한다. SmartScreen이 *"Windows의 PC 보호"*를 띄우면
   **추가 정보** → **실행**을 선택한다.

### macOS

macOS는 서명되지 않은 앱을 *"손상되었기 때문에 열 수 없습니다"*라고 알린다. 앱이 손상된 것이 아니라,
서명 없이 격리된 번들에 Gatekeeper가 붙이는 메시지다. 앱을 옮겨 놓은 뒤 격리 속성을 지우면 된다.

```sh
xattr -dr com.apple.quarantine "/Applications/Object Storage Client.app"
```

### Linux

막는 서명 검사가 없다. 최소 설치 환경에서는 Avalonia가 의존하는 라이브러리가 필요할 수 있다.

```sh
sudo apt install libx11-6 libice6 libsm6 libfontconfig1
tar -xzf ObjectStorageClient-@VERSION@-linux-x64.tar.gz
./ObjectStorageClient-@VERSION@-linux-x64/ObjectStorageClient.App
```

## 다운로드 검증

`SHA256SUMS.txt`가 이 릴리즈의 모든 자산을 포함한다.

```sh
sha256sum -c SHA256SUMS.txt --ignore-missing     # Linux
shasum -a 256 -c SHA256SUMS.txt --ignore-missing # macOS
```

```powershell
Get-FileHash .\ObjectStorageClient-@VERSION@-win-x64.zip -Algorithm SHA256  # Windows
```

## 데이터 저장 위치

`$HOME/.devcode/object-storage-client/` (Windows는 `%USERPROFILE%`)에 `sites.json`과
`config.json`이 저장된다. 저장된 자격증명은 마스터 비밀번호에서 파생된 키로 AES-256-GCM 암호화되며,
그 비밀번호는 디스크에 결코 기록되지 않는다 — **잊어버리면 복구할 방법이 없다.**

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
