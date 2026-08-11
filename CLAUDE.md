# CLAUDE.md

*한국어 · [English](CLAUDE.en.md)*

이 파일은 Claude Code(claude.ai/code)가 이 저장소에서 작업할 때 참고하는 지침이다.

## 이게 무엇인가

S3 호환 오브젝트 스토리지를 위한 크로스 플랫폼 데스크톱 클라이언트. Avalonia UI로 만들었고 FileZilla
처럼 배치했다 — quick-connect 바, 메시지 로그, 좌우로 나란한 로컬/원격 파일 패널, 그리고 대기/실패/
성공 탭이 있는 전송 큐. 하나의 코드베이스로 Windows 11, 데비안 계열 Linux, macOS를 대상으로 한다.

## 명령

```bash
dotnet build ObjectStorageClient.sln            # 전체 빌드
dotnet test  ObjectStorageClient.sln            # 전체 테스트
dotnet run --project src/ObjectStorageClient.App # GUI 실행

# 단일 테스트 / 단일 클래스
dotnet test tests/ObjectStorageClient.Core.Tests --filter "FullyQualifiedName~TransferQueueTests"
dotnet test tests/ObjectStorageClient.Core.Tests --filter "FullyQualifiedName~ObjectKeyTests.ToLocalPath_RejectsKeysThatEscapeTheTargetDirectory"

# self-contained 데스크톱 빌드
dotnet publish src/ObjectStorageClient.App -c Release -r win-x64   --self-contained
dotnet publish src/ObjectStorageClient.App -c Release -r linux-x64 --self-contained
dotnet publish src/ObjectStorageClient.App -c Release -r osx-arm64 --self-contained
```

모든 프로젝트에 `TreatWarningsAsErrors`가 켜져 있으므로 **경고 하나가 빌드를 실패시킨다.**

## 의미가 있는 버전 고정

- **Avalonia는 12.x가 아니라 11.3 라인에 고정되어 있다.** Avalonia 12의 Roslyn 분석기는 .NET 10
  SDK(컴파일러 4.14)를 요구하는데 이 저장소는 .NET 9 SDK로 빌드한다. .NET 10 SDK로 옮기지 않은 채
  `Directory.Packages.props`의 `AvaloniaVersion`만 올리면 `CS9057`로 실패한다.
  12.x로 올릴 때는 이것들도 함께 바뀐다: `Avalonia.Diagnostics` → `AvaloniaUI.DiagnosticsSupport`,
  그리고 `App.axaml`의 DataGrid 테마 include가 `Themes/Fluent.xaml`에서 `Themes/Fluent.axaml`로.
- `Avalonia.Controls.DataGrid`는 코어 패키지보다 뒤처지기 때문에 별도 버전
  (`AvaloniaDataGridVersion`)을 따른다.
- 모든 패키지 버전은 `Directory.Packages.props`에 있다(중앙 패키지 관리). csproj에는
  `<PackageReference Include="..." />`만 있고 `Version` 속성이 없다.

## 아키텍처

두 개의 프로젝트. 그리고 강한 의존 규칙 하나: **Core는 절대 Avalonia를 참조하지 않는다.**

```
src/ObjectStorageClient.Core   도메인 모델, S3 접근, 전송, 프로필 저장
src/ObjectStorageClient.App    Avalonia 뷰 + 뷰모델 (MVVM, CommunityToolkit.Mvvm)
```

`IObjectStorageClient`(`Core/Abstractions`)가 그 경계다. `S3ObjectStorageClient`가 AWSSDK.S3 위에서
이를 구현하고, 테스트는 `FakeObjectStorageClient`로 대체한다. 뷰모델은 인터페이스에만 의존하며
`Amazon.*` 타입에는 의존하지 않는다.

### 제공자 프리셋 대 수동 입력

`StorageProviderCatalog`가 내장 제공자를 담는다(AWS, MinIO, R2, B2, Wasabi, Spaces, GCS, NAVER
Cloud, Linode, 그리고 `custom` 항목). **프리셋은 양식을 채워줄 뿐이다 — 모든 필드는 편집 가능한
상태로 남고, 엔드포인트·키·리전·버킷을 전부 손으로 입력한 프로필도 일급 케이스다.**
`ConnectionEditorViewModel`이 이를 강제한다. `_suppressPresetSync`가 필드 변경 핸들러를 막아서,
저장된 프로필을 불러올 때 프리셋이 사용자가 저장해 둔 값을 덮어쓰지 못하게 한다. 제공자를 추가한다는
것은 `StorageProviderCatalog.All`에 항목 하나를 넣는 것이고 그 외에는 아무것도 아니다.

`ConnectionProfile.ResolveEndpoint()`가 실효 엔드포인트를 결정하는 유일한 지점이다. 명시된
`ServiceUrl`이 프리셋의 `{region}`/`{account}` 템플릿을 항상 이긴다.

### 프록시와 TLS 설정이 커스텀 HttpClientFactory에 있는 이유

AWS SDK v4에서 `ClientConfig`의 `ProxyBypassList`/`ProxyBypassOnLocal`이 제거되었다. 그래서
`S3HttpClientFactory`가 `HttpClientHandler`를 직접 구성한다 — 프록시 자격증명, glob을 정규식으로
바꾼 bypass 목록, 그리고 "모든 TLS 인증서 허용" 옵트인 스위치를 이쪽이 소유한다.
`S3ObjectStorageClient.BuildConfig`는 프로필이 실제로 필요로 할 때만
(`S3HttpClientFactory.IsRequiredFor`) 이를 설치한다. 그 매핑은 `S3ConfigurationTests`가 덮고 있으며,
**비 AWS 게이트웨이를 상대로 조용히 깨지기 가장 쉬운 계층**이다.

제공자별 특이사항도 `BuildConfig`를 통과한다. `DisableRequestChecksums`는
`RequestChecksumCalculation.WHEN_REQUIRED`를 설정한다. **기본값이 `true`다** — AWS SDK v4는 기본으로
`x-amz-checksum-*` 헤더와 `aws-chunked` 본문을 보내는데, 이를 구현하지 않은 게이트웨이는 아무 설명
없이 `NotImplemented`로 답하고 결국 모든 업로드가 실패한다. 체크섬을 다시 켜는 프리셋은 Amazon S3
뿐이다. **이 기본값을 SDK에 맞추겠다고 "고치지" 말 것.**

여기에는 **두 번째, 독립적인** 호환성 위험이 있다: `aws-chunked` 업로드 본문. `UseChunkEncoding`은
`PutObjectRequest`와 `UploadPartRequest`에는 있지만 `TransferUtilityUploadRequest`에는 **없고**,
설정 수준의 스위치도 없다. 즉 업로드가 `TransferUtility`를 거치는 한 항상
`Content-Encoding: aws-chunked`와 `x-amz-content-sha256: STREAMING-AWS4-HMAC-SHA256-PAYLOAD`를
보내며, 같은 게이트웨이들이 이를 거부한다. 그래서 `DisableChunkedEncoding`(기본 `true`)은
TransferUtility를 설정하는 대신, `UploadAsync`가 16 MiB 미만에서는 `PutObject`를 직접 호출하고 그
이상에서는 멀티파트를 직접 구현하도록 만든다. `UploadRequestEncodingTests`가 로컬 `HttpListener`를
상대로 실제 요청을 포착하는 이유는, `AmazonS3Config`에 대한 어떤 단언으로도 요청 단위 결정을 볼 수
없기 때문이다.

직접 구현한 멀티파트 경로는 파트를 순차로 업로드하고 실패 시 업로드를 중단(abort)한다 — 버려진
파트에는 요금이 부과된다. `CalculatePartSize`가 파트 수를 S3의 10,000개 한도 안에 유지한다.

`S3ErrorGuidance`는 이런 게이트웨이가 반환하는 맨 오류 코드를 실행 가능한 문구로 매핑하고,
`S3ObjectStorageClient`가 SDK 호출을 감싸 실패가 그 문구를 담은 `StorageOperationException`으로
드러나게 한다. `FindS3Exception`이 `AggregateException`을 벗겨내는 이유는 `TransferUtility`가
멀티파트 실패를 중첩시키기 때문이다. `OperationCanceledException`은 **의도적으로 잡지 않는다.**
전송 큐가 "취소됨"과 "실패"를 계속 구분할 수 있어야 하기 때문이다.

### 오브젝트 키는 파일 경로가 아니다

`ObjectKey`는 평평한 `/` 구분 S3 네임스페이스와 플랫폼 파일 경로 사이를 변환하는 유일한 지점이다.
키는 `/`로 시작하지 않고, OS와 무관하게 항상 `/`를 쓰며, 끝의 `/`가 폴더 프리픽스임을 표시한다.
`ObjectKey.ToLocalPath`는 다운로드 디렉터리를 벗어나는 키를 거부한다 — 다운로드 경로를 추가할 때
이를 우회하지 말 것.

### 전송 큐 스레딩 계약

`TransferQueue`는 채널 기반이며 고정 크기 워커 풀을 쓰고, `ItemAdded`/`ItemUpdated`를 **워커
스레드에서** 발생시킨다. `Dispatcher.UIThread`로 마샬링하는 책임은 `TransferQueueViewModel`에 있고,
Core는 디스패처의 존재를 의도적으로 모른다. 진행률 이벤트는 항목당 초당 약 5회로 제한된다. 각 전송은
독립적이며, 한 건의 실패가 큐를 멈추는 일은 없다 — 그것이 실패/성공 탭을 의미 있게 만든다.

### 저장 위치와 마스터 비밀번호

두 파일 모두 모든 플랫폼에서 하나의 고정된 디렉터리에 있다 — `AppPaths.ConfigDirectory`, 즉
`$HOME/.devcode/object-storage-client/` (Windows에서는 `%USERPROFILE%`). 디렉터리째 머신 사이를
옮길 수 있게 하려고 플랫폼별 관례를 **의도적으로 무시한다.**

| 파일 | 내용 |
| --- | --- |
| `sites.json` | 저장된 접속 정보. 자격증명은 암호화됨 |
| `config.json` | 환경설정과 마스터 비밀번호 솔트·반복 횟수·검증값 |

`MasterPasswordVault`는 PBKDF2-HMAC-SHA256(600k회)으로 마스터 비밀번호에서 32바이트 AES 키를
파생한다. 키는 메모리에만 존재하고 비밀번호는 어디에도 기록되지 않으므로, `config.json`으로는 키를
복구할 수 없다. `TryUnlock`은 `Verifier` 블롭을 복호화해 비밀번호를 증명한다 — 틀린 비밀번호는 GCM
태그 검사에서 실패하고, `AesGcmSecretProtector`는 이를 빈 문자열로 보고한다.

**시작 순서가 중요하며**, `App.OnFrameworkInitializationCompleted`가 컨테이너를 직접 만들지 않는
이유가 그것이다. `JsonConnectionProfileStore`를 생성하기 *전에* `config.json`을 읽고, 비밀번호를
받고, 키를 파생해야 한다. 그래서 `StartAsync`는 게이트 창이 떠 있는 동안 `ShutdownMode.OnExplicitShutdown`
으로 두었다가(그러지 않으면 `MainWindow` 없이 창을 닫는 순간 앱이 종료된다) 이후
`OnMainWindowClose`로 전환한다. 프롬프트에서 종료하면 앱이 내려간다 — 키 없이는 쓸 수 있는 세션이
없다.

비밀번호를 잊은 경우 `MasterPasswordViewModel`이 새 vault를 만들고 `DiscardedPreviousVault`를
설정하는 초기화를 제공한다. 그러면 시작 시 `sites.json`을 삭제한다. 그 안의 비밀은 더 이상 복호화할
수 없기 때문이다. vault 정의가 손상된 `config.json`도 같은 경로로 처리된다.

`MasterPasswordViewModel.OnPasswordChanged`가 `ErrorMessage`를 지운다는 점에 유의할 것. 비밀번호
입력란을 비우면서 오류도 보고해야 하는 코드는 **입력란을 먼저** 비워야 한다.

`JsonConnectionProfileStore`는 `JsonIgnoreCondition.WhenWritingDefault`를 쓰면 안 된다. 그것은
`false`와 `0`을 생략하는데, `ForcePathStyle`, `DisableRequestChecksums`, `TimeoutSeconds`,
`MaxConcurrentTransfers`는 모두 `true`/0이 아닌 값으로 초기화된다. 생략된 속성은 로드 시 초기값으로
되돌아가므로, **저장한 "꺼짐"이 조용히 "켜짐"으로 되살아난다.**

**아무것도 암묵적으로 디스크에 기록되지 않는다.** 두 파일은 사용자가 요청할 때만 저장된다.
`config.json`은 최초 실행 시(새 vault 기록) 그리고 이후에는 설정 UI의 저장에서, `sites.json`은 Site
Manager의 저장과 삭제에서. 종료는 아무것도 저장하지 않고, *접속*도 아무것도 저장하지 않는다 — 예전에는
접속이 프로필을 저장했고, 그래서 매번 새 id로 만들어지는 Quickconnect가 조용히 사이트를 하나씩
늘렸다. `SiteManagerPersistenceTests`가 이를 못 박고 있다.

두 저장소 모두 자신의 쓰기를 검증한다. rename 후 파일을 다시 읽어 비교하고 일치하지 않으면 예외를
던진다. 저장이 성공했다고 보고했는데 파일에 새 값이 없는 경우 — 반쯤 쓰인 임시 파일이나 속성을
빠뜨린 직렬화기 — 를 잡아내는 장치다.

### sites.json 계약

`Core/Persistence`가 디스크상의 형태(`SiteDocument`/`StoredSite`)를 담으며, UI가 바인딩하는
`ConnectionProfile`과 의도적으로 분리되어 있다. `SiteMapper`가 둘이 만나는 유일한 지점이다. 그 상태를
유지할 것. 도메인 모델이 곧 직렬화 계약이었을 때는 모든 public getter가 저장 필드가 되었고, 파생
속성인 `Preset`이 제공자 카탈로그의 낡은 사본을 모든 사이트에 기록했으며, 프록시의 계산된 플래그도
같은 방식으로 새어 나갔다.

엔드포인트에 도달하는 방법을 기술하는 모든 것 — URL, 리전, 계정과 액세스 키, 시크릿, 세션 토큰,
버킷, 프리픽스, 프록시 전체 — 은 함께 직렬화되어 단일 `connection` 블롭으로 암호화된다. Site
Manager가 사이트를 나열하는 데 필요한 것(id, name, providerId), 민감하지 않은 동작 스위치, 타임스탬프만
평문으로 남는다. **따라서 접속 설정을 추가할 때 그것이 비밀인지 판단할 필요도, 암호화 필드를 새로
만들 필요도 없다.**

저장소가 `CreatedAt`(최초 저장)과 `LastModifiedAt`(매 저장)을 소유한다. `LastUsedAt`은 최근 사용
순서 정렬을 위해 예약되어 있고 아직 아무것도 기록하지 않는다.

`SiteDocument.Version`은 1이고 읽어야 할 레이아웃은 언제나 하나뿐이다 — 아직 배포된 것이 없었기에
이전의 사전 릴리즈 형태는 변환한 뒤 그 리더를 남기지 않고 삭제했다.

`StoredSite`의 호환성 스위치는 `ConnectionProfile`과 같은 기본값을 유지해야 한다(`ForcePathStyle`,
`DisableRequestChecksums`, `DisableChunkedEncoding` 모두 `true`). `bool`의 기본값은 `false`이므로,
이 중 하나가 빠진 저장 사이트는 체크섬과 chunked 본문이 켜진 채로 돌아온다 — 그것이 바로 S3 호환
게이트웨이가 모든 업로드를 거부하게 만드는 조건이다.

종료는 **`provider.DisposeAsync()` 그것뿐이다.** 컨테이너가 뷰모델과 전송 큐를 비롯한 나머지를
소유하며 싱글턴을 등록 역순으로 폐기한다. 그중 무엇이든 명시적으로 한 번 더 폐기하면 이중 폐기가
되고, 그것이 큐의 취소 토큰 소스에서 `ObjectDisposedException`을 일으켜 종료 시 앱을 죽였다. 같은
이유로 뷰모델은 자신이 만든 것만 해제해야 하며(자신의 `TransferQueueViewModel`과 팩토리로 만든
클라이언트), 주입받은 의존성은 결코 해제하지 않는다. 여기의 모든 `DisposeAsync`는 멱등해야 한다.

`ShutdownRequested`는 **동기** 이벤트다. `async` 핸들러는 첫 `await`에서 반환하고 런타임은 작업이
진행 중인 채로 프로세스를 무너뜨린다. 그래서 `App.ShutdownAsync`는 블로킹으로 기다리되 —
직접 await하지 않고 `Task.Run`을 거친다. `await using` 폐기는 `ConfigureAwait(false)`를 달고 있지
않으므로 `FileStream.DisposeAsync`가 계속(continuation)을 블로킹된 UI 스레드로 되돌려 보내 앱을
멈춰 세운다. `Task.Run`은 동기화 컨텍스트를 지워서, await를 하나씩 고치는 대신 이 문제 부류 전체를
해결한다.

저장소들 역시 UI 스레드에서 블로킹으로 호출되므로, 그 안의 **모든** await는 —
`stream.ConfigureAwait(false)` 형태가 필요한 `await using` 폐기를 포함해 — 컨텍스트를 포획하지 않아야
한다. `BlockingCallerTests`가 펌프할 수 없는 컨텍스트로 교착을 재현하고, 실패 메시지에 문제가 되는
await의 이름을 담는다.

두 저장소 모두 `.tmp` 파일에 쓴 뒤 rename한다. 이때 반드시 `AppPaths.CreateOwnerOnlyFile`로 열 것.
`File.Create`는 안 된다. 후자는 umask(일반적인 유닉스에서 0644)를 적용하는데, 그러면 이후 chmod가
이뤄질 때까지 자격증명 파일이 노출된다. 그 헬퍼가 모드를 두 번 설정하는 것은 의도적이다 —
`UnixCreateMode`가 새 파일을 덮고, 명시적 chmod가 중단된 저장이 남긴 낡은 임시 파일을 덮는다. 후자의
모드는 `FileMode.Create`가 그대로 보존하기 때문이다.

## 이 코드베이스만의 관례

- 뷰는 `.axaml`이고 컴파일된 바인딩이 기본으로 켜져 있다(`AvaloniaUseCompiledBindingsByDefault`).
  따라서 모든 뷰와 `DataTemplate`에 `x:DataType`이 필요하다.
- `MainWindowViewModel`이 `ITransferCoordinator`를 구현한다. 업로드에는 원격 패널의 프리픽스가,
  다운로드에는 로컬 패널의 디렉터리가 필요하므로, 두 패널을 모두 소유한 계층만이 전송을 큐에 넣을 수
  있다 — 패널들은 서로를 모르는 상태로 남는다. 전송 후 자동 새로고침도 이쪽이 소유한다. 완료는 워커
  스레드에서 도착하므로 핸들러가 디스패처로 마샬링하고, 전송이 도달한 위치가 *현재* 위치인 패널만
  새로고침하며, 폴더 하나가 파일마다 완료를 하나씩 만들어내므로 `RefreshDebouncer`를 거친다.
- 행을 활성화하면(`OpenCommand`, 더블클릭에 바인딩) 디렉터리와 프리픽스는 들어가고 그 외에는 전송한다.
  두 패널이 이 구분을 나란히 유지해야 한다.
- 마스터 비밀번호 입력란은 출력 가능한 ASCII만 받는다. 여기서 중요한 것이 세 가지이며 모두
  `MasterPasswordInputTests`(headless, 실제 입력 파이프라인 구동)가 검증한다.
  - **`InputMethod.IsInputMethodEnabled="False"`를 설정하지 말 것.** 올바른 도구처럼 보이지만
    아니다. 입력 컨텍스트를 끄면 macOS가 활성 레이아웃을 통해 매핑된 원시 키 이벤트를 전달하는데,
    한글 레이아웃에서는 Shift가 대문자를 만들지 못하게 된다. 그러면 같은 키 입력이 입력 모드에 따라
    *다른* 비밀번호를 만들어낸다 — 마스킹된 입력란에서 눈에 보이지 않게. 그것이 사용자가 재현할 수
    없는 비밀번호로 vault가 만들어지는 경로다. IME는 돌게 두고 그 결과를 거부할 것.
  - `TextInput` 핸들러는 코드비하인드에서 `RoutingStrategies.Tunnel`로 붙여야 한다.
    `TextInputEvent`는 `Tunnel, Bubble`로 라우팅되고 `TextBox.OnTextInput`은 **버블 단계의 클래스
    핸들러**다. 따라서 XAML의 `TextInput="..."` 핸들러는 텍스트가 이미 삽입된 *뒤에* 실행되며 거기서
    `Handled`를 설정해도 아무 효과가 없다. 실제로 방어가 성립하는 계층이 이곳이다.
  - `TextChanged` 보정이 `TextInput`을 아예 발생시키지 않은 것(붙여넣기)을 걷어낸다. 그래서 입력란이
    보여주는 것이 실제로 쓰이는 비밀번호와 항상 같다.

  뷰모델에서만 정제하는 것은 **동작하지 않는다.** 바인딩이 대상에서 소스로 갱신되는 중에는 강제된
  값이 `TextBox`로 되돌아 전파되지 않아 입력란에 거부된 문자가 그대로 남는다.
  `MasterPasswordViewModel.RemoveDisallowed`는 공유 규칙이자, 속성을 직접 설정하는 코드에 대한
  최후 방어선으로 남는다. `OnPasswordChanged`가 `ErrorMessage`를 지우므로 그곳의 "재할당 후 보고"
  순서는 의도적이다.
- 코드비하인드는 MVVM으로 대응할 수 없는 뷰 상태 배선에 한정한다. `DataGrid.SelectedItems`는 바인딩
  가능한 속성이 아니므로 `LocalPaneView`/`RemotePaneView`가 선택을 뷰모델로 동기화하고 더블클릭
  활성화를 처리한다. 비즈니스 로직은 그곳에 두지 않는다. `TransferQueueView`는 추가로 우클릭한 행을
  선택한다. Avalonia의 `DataGrid`가 그렇게 하지 않기 때문이며, 그러지 않으면 컨텍스트 메뉴 명령이
  이전 선택에 대해 동작한다.
- Core의 버킷 타입은 `BucketInfo`가 아니라 `StorageBucket`이다. 전자는
  `Amazon.S3.Model.BucketInfo`와 충돌한다.
- 로그 색상은 `LogLevelConverters`가 구동하는 스타일 클래스(`Classes.command`, `Classes.response`,
  `Classes.error`)로 처리하므로 팔레트는 `AppStyles.axaml`에 머문다.
- 파일 패널의 행 아이콘은 이모지가 아니라 그려진 도형이다. `📁`/`📄`는 Windows와 macOS에서는 멀쩡해
  보이지만, 번들된 폰트는 Inter뿐이고 Inter에는 이모지가 없다. 이모지 폰트가 없는 머신에서는
  fontconfig가 고른 대체 글리프가 나오며 실제로는 줄무늬 상자로 보인다. self-contained 빌드가 특정
  폰트의 존재에 의존해서는 안 된다 — 시스템 라이브러리에 의존해서 안 되는 것과 같은 이유다.
  기하 도형은 `ListingConverters`에 있다.
- 값이 없는 셀은 0을 출력하지 않는다. 디렉터리와 프리픽스의 `Size`는 `-`로(`ByteSize.Format`의
  `isContainer` 오버로드), 타임스탬프가 없는 행의 Modified는 빈 칸으로 나온다. `StringFormat`
  바인딩은 null을 값 타입의 기본값으로 렌더링해 `0001-01-01 00:00`을 만들기 때문에 컨버터를 쓴다.
  `FilePaneColumnTests`가 실제 패널을 headless로 렌더링해 셀을 읽어 이를 고정한다.
