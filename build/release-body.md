S3 호환 오브젝트 스토리지용 데스크톱 클라이언트다. 화면은 FileZilla처럼 좌우 2단으로 나뉜다.

## 다운로드

| 플랫폼 | 파일 |
| --- | --- |
| Windows 11 (x64) | Microsoft Store 공개 예정: @STORE_URL_KO@ |
| Debian / Ubuntu (x86-64) | `ObjectStorageClient-@VERSION@-@PACKAGE_RELEASE@-linux-x64.deb` |
| Fedora / Rocky / AlmaLinux / RHEL (x86-64) | `ObjectStorageClient-@VERSION@-@PACKAGE_RELEASE@-linux-x64.rpm` |
| 리눅스 휴대용 대안 (x86-64) | `ObjectStorageClient-@VERSION@-linux-x64.tar.gz` |
| macOS (Apple Silicon) | `ObjectStorageClient-@VERSION@-osx-arm64.zip` |
| macOS (Intel) | `ObjectStorageClient-@VERSION@-osx-x64.zip` |

.NET 런타임까지 들어 있어서 따로 설치할 게 없다.

## Windows는 Microsoft Store 공개 예정

개발자 계정은 승인됐지만 공개 목록과 인증은 아직 대기 중이다. 공개 뒤에는 Store가 MSIX에 서명하고
업데이트를 맡는다. 과거 GitHub 릴리즈의 Windows ZIP은 서명되지 않은 레거시 테스트 산출물이다.

## macOS와 리눅스 서명

RPM 패키지 자체와 서명된 APT/DNF 저장소 메타데이터는 프로젝트 GPG 키로 검증한다. `.deb`는 APT의
서명된 metadata checksum chain으로 인증한다. Release에서 단독으로 받은 `.deb`, 휴대용 tar.gz와
macOS ZIP은 `SHA256SUMS.txt`도 확인해야 한다. 체크섬만으로는 출처를 증명할 수 없다.

### macOS

현재 ZIP은 서명·notarization이 없어 Gatekeeper가 실행을 막을 수 있다. 플랫폼 보호 기능을 끄는 절차는
제공하지 않는다. 소스에서 직접 빌드하거나 서명·notarization된 배포를 기다리는 편이 안전하다.

### 리눅스

권장 설치 경로는 signed APT/DNF 저장소다. 첫 네이티브 Linux 패키지 릴리즈 전에는 Pages URL이
404를 반환할 수 있다. 그때까지 tar.gz는 수동 대안으로만 제공한다.

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
| Windows 11 (x64) | Microsoft Store listing planned: @STORE_URL_EN@ |
| Debian / Ubuntu (x86-64) | `ObjectStorageClient-@VERSION@-@PACKAGE_RELEASE@-linux-x64.deb` |
| Fedora / Rocky / AlmaLinux / RHEL (x86-64) | `ObjectStorageClient-@VERSION@-@PACKAGE_RELEASE@-linux-x64.rpm` |
| Portable Linux fallback (x86-64) | `ObjectStorageClient-@VERSION@-linux-x64.tar.gz` |
| macOS (Apple Silicon) | `ObjectStorageClient-@VERSION@-osx-arm64.zip` |
| macOS (Intel) | `ObjectStorageClient-@VERSION@-osx-x64.zip` |

Every build is self-contained — no .NET runtime installation is required.

## Windows is planned for the Microsoft Store

The developer account is approved, but listing and certification are still pending. Once public,
the Store will sign the MSIX and handle updates. Historical Windows ZIPs on GitHub are unsigned
legacy test artifacts.

## macOS and Linux signatures

Each RPM package and the signed APT/DNF repository metadata are verified with the project GPG key.
A `.deb` is authenticated by APT's signed metadata checksum chain. For a standalone release `.deb`,
the portable tar.gz, or a macOS ZIP, also verify `SHA256SUMS.txt`; a checksum alone does not prove
where a file came from.

### macOS

The current ZIP is neither signed nor notarised, so Gatekeeper may refuse to run it. This project
does not document a way to disable that protection. Build from source or wait for a signed and
notarised distribution.

### Linux

The signed APT/DNF repositories are the recommended install path. Their Pages URLs may return 404
until the first native Linux package release. Until then, the tar.gz is a manual fallback:

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

## Where your data is stored

`$HOME/.devcode/object-storage-client/` (`%USERPROFILE%` on Windows) holds `sites.json` and
`config.json`. Saved credentials are encrypted with AES-256-GCM under a key derived from your
master password, which is never written to disk — **if you forget it, there is no recovery.**

## License

MIT.

</details>
