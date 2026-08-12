# CLAUDE.md

*한국어 · [English](CLAUDE.en.md)*

Claude Code(claude.ai/code)가 이 저장소에서 작업할 때 참고하는 지침이다.

## 뭐 하는 프로젝트인가

S3 호환 오브젝트 스토리지용 데스크톱 클라이언트다. Avalonia UI로 만들었고 화면 구성은 FileZilla를
따랐다. 위에 quick-connect 바, 그 아래 메시지 로그, 가운데 좌우로 로컬·원격 파일 패널, 맨 아래
대기·실패·성공 탭이 있는 전송 큐. 코드베이스 하나로 Windows 11과 데비안 계열 리눅스, macOS를
지원한다.

## 명령

```bash
dotnet build ObjectStorageClient.sln            # 전체 빌드
dotnet test  ObjectStorageClient.sln            # 전체 테스트
dotnet run --project src/ObjectStorageClient.App # GUI 실행

# 테스트 하나만, 클래스 하나만
dotnet test tests/ObjectStorageClient.Core.Tests --filter "FullyQualifiedName~TransferQueueTests"
dotnet test tests/ObjectStorageClient.Core.Tests --filter "FullyQualifiedName~ObjectKeyTests.ToLocalPath_RejectsKeysThatEscapeTheTargetDirectory"

# self-contained 데스크톱 빌드
dotnet publish src/ObjectStorageClient.App -c Release -r win-x64   --self-contained
dotnet publish src/ObjectStorageClient.App -c Release -r linux-x64 --self-contained
dotnet publish src/ObjectStorageClient.App -c Release -r osx-arm64 --self-contained
```

모든 프로젝트에 `TreatWarningsAsErrors`가 걸려 있다. **경고 하나에 빌드가 통째로 실패한다.**

## 버전을 고정해둔 이유

- **Avalonia는 12.x가 아니라 11.3 라인에 묶여 있다.** Avalonia 12의 Roslyn 분석기가 .NET 10
  SDK(컴파일러 4.14)를 요구하는데 이 저장소는 .NET 9 SDK로 빌드한다. SDK를 안 올린 채
  `Directory.Packages.props`의 `AvaloniaVersion`만 올리면 `CS9057`로 실패한다.
  12.x로 갈 때는 이것들도 같이 바뀐다. `Avalonia.Diagnostics`가
  `AvaloniaUI.DiagnosticsSupport`로, `App.axaml`의 DataGrid 테마 include가 `Themes/Fluent.xaml`에서
  `Themes/Fluent.axaml`로.
- `Avalonia.Controls.DataGrid`는 코어 패키지보다 릴리즈가 늦어서 버전을 따로
  (`AvaloniaDataGridVersion`) 관리한다.
- 패키지 버전은 전부 `Directory.Packages.props`에 있다(중앙 패키지 관리). csproj에는
  `<PackageReference Include="..." />`만 쓰고 `Version` 속성은 붙이지 않는다.

## 아키텍처

프로젝트는 둘. 그리고 지켜야 할 의존 규칙이 하나 있다. **Core는 Avalonia를 참조하지 않는다.**

```
src/ObjectStorageClient.Core   도메인 모델, S3 접근, 전송, 프로필 저장
src/ObjectStorageClient.App    Avalonia 뷰와 뷰모델 (MVVM, CommunityToolkit.Mvvm)
```

경계는 `IObjectStorageClient`(`Core/Abstractions`)다. `S3ObjectStorageClient`가 AWSSDK.S3 위에서
구현하고, 테스트에서는 `FakeObjectStorageClient`로 갈아 끼운다. 뷰모델은 인터페이스만 보고
`Amazon.*` 타입은 모른다.

### 프리셋과 직접 입력

`StorageProviderCatalog`에 내장 제공자가 들어 있다. AWS, MinIO, R2, B2, Wasabi, Spaces, GCS,
NAVER Cloud, Linode, 그리고 `custom` 항목. **프리셋은 양식을 채워줄 뿐이다. 모든 필드는 그대로 고칠
수 있고, 엔드포인트와 키, 리전, 버킷을 전부 손으로 넣은 프로필도 똑같이 일급이다.**

이걸 강제하는 쪽이 `ConnectionEditorViewModel`이다. `_suppressPresetSync`가 필드 변경 핸들러를
막아서, 저장된 프로필을 불러올 때 프리셋이 사용자 값을 덮어쓰지 못하게 한다. 제공자를 추가한다는
건 `StorageProviderCatalog.All`에 항목 하나 넣는 것이고 그 외에 할 일은 없다.

실효 엔드포인트를 정하는 곳은 `ConnectionProfile.ResolveEndpoint()` 한 군데뿐이다. 명시된
`ServiceUrl`이 프리셋의 `{region}`·`{account}` 템플릿을 언제나 이긴다.

### 프록시와 TLS 설정이 왜 커스텀 HttpClientFactory에 있나

AWS SDK v4에서 `ClientConfig`의 `ProxyBypassList`와 `ProxyBypassOnLocal`이 없어졌다. 그래서
`S3HttpClientFactory`가 `HttpClientHandler`를 직접 구성한다. 프록시 자격증명, glob을 정규식으로
바꾼 bypass 목록, "모든 TLS 인증서 허용" 옵트인 스위치가 전부 여기 있다.
`S3ObjectStorageClient.BuildConfig`는 프로필이 실제로 필요로 할 때만
(`S3HttpClientFactory.IsRequiredFor`) 이걸 붙인다. 이 매핑은 `S3ConfigurationTests`가 지키고 있는데,
**비 AWS 게이트웨이를 상대로 가장 조용히 깨지는 계층이 여기다.**

제공자별 특이사항도 `BuildConfig`를 지난다. `DisableRequestChecksums`는
`RequestChecksumCalculation.WHEN_REQUIRED`를 설정하고 **기본값이 `true`다.** AWS SDK v4가 기본으로
`x-amz-checksum-*` 헤더와 `aws-chunked` 본문을 보내는데, 이걸 구현하지 않은 게이트웨이는 설명도
없이 `NotImplemented`로 답하고 결국 업로드가 전부 실패한다. 체크섬을 다시 켜는 프리셋은 Amazon S3
하나뿐이다. **SDK 기본값에 맞추겠다고 이 값을 "고치지" 말 것.**

여기에는 **성격이 다른 두 번째 위험**이 하나 더 있다. `aws-chunked` 업로드 본문이다.
`UseChunkEncoding`은 `PutObjectRequest`와 `UploadPartRequest`에는 있는데
`TransferUtilityUploadRequest`에는 **없고**, 설정 수준의 스위치도 없다. 업로드가 `TransferUtility`를
거치는 한 `Content-Encoding: aws-chunked`와
`x-amz-content-sha256: STREAMING-AWS4-HMAC-SHA256-PAYLOAD`가 항상 나가고, 같은 게이트웨이들이 이걸
거부한다. 그래서 `DisableChunkedEncoding`(기본 `true`)은 TransferUtility를 설정하는 대신
`UploadAsync`의 동작을 바꾼다. 16 MiB 미만이면 `PutObject`를 직접 부르고, 그 이상이면 멀티파트를
직접 구현한다. `UploadRequestEncodingTests`가 로컬 `HttpListener`로 실제 요청을 받아보는 이유는,
`AmazonS3Config`를 아무리 단언해봐야 요청 단위 결정은 보이지 않기 때문이다.

직접 구현한 멀티파트는 파트를 순서대로 올리고 실패하면 업로드를 중단(abort)한다. 버려진 파트에도
요금이 붙는다. 파트 개수는 `CalculatePartSize`가 S3의 10,000개 한도 안에 묶어둔다.

`S3ErrorGuidance`는 이런 게이트웨이가 던지는 맨 오류 코드를 손댈 수 있는 문구로 바꾼다.
`S3ObjectStorageClient`가 SDK 호출을 감싸서 실패가 그 문구를 담은 `StorageOperationException`으로
나오게 한다. `FindS3Exception`이 `AggregateException`을 벗기는 이유는 `TransferUtility`가 멀티파트
실패를 겹겹이 싸기 때문이다. `OperationCanceledException`은 **일부러 잡지 않는다.** 전송 큐가
"취소됨"과 "실패"를 계속 구분해야 해서다.

### 오브젝트 키는 파일 경로가 아니다

평평한 `/` 구분 S3 네임스페이스와 플랫폼 파일 경로 사이를 오가는 곳은 `ObjectKey` 하나뿐이다. 키는
`/`로 시작하지 않고, OS와 무관하게 `/`만 쓰며, 끝에 붙은 `/`가 폴더 프리픽스를 뜻한다.
`ObjectKey.ToLocalPath`는 다운로드 디렉터리를 벗어나는 키를 거부한다. 다운로드 경로를 새로 만들 때
여길 우회하지 말 것.

### 전송 큐 스레딩 계약

`TransferQueue`는 채널 기반이고 고정 크기 워커 풀을 쓴다. `ItemAdded`와 `ItemUpdated`를 **워커
스레드에서** 던진다. `Dispatcher.UIThread`로 넘기는 건 `TransferQueueViewModel`의 몫이고, Core는
디스패처가 있는지조차 모르게 두었다. 진행률 이벤트는 항목당 초당 5회 정도로 제한한다. 전송은 서로
독립이라 하나가 실패해도 큐가 멈추지 않는다. 그래야 실패·성공 탭이 의미를 갖는다.

### 저장 위치와 마스터 비밀번호

두 파일 모두 플랫폼과 상관없이 한 디렉터리에 둔다. `AppPaths.ConfigDirectory`, 즉
`$HOME/.devcode/object-storage-client/`다. Windows에서는 `%USERPROFILE%` 아래. 플랫폼별 관례를
**일부러 무시했다.** 디렉터리째 다른 컴퓨터로 옮길 수 있게 하려는 것이다.

| 파일 | 내용 |
| --- | --- |
| `sites.json` | 저장된 접속 정보. 자격증명은 암호화 |
| `config.json` | 환경설정과 마스터 비밀번호 솔트·반복 횟수·검증값 |

`MasterPasswordVault`가 PBKDF2-HMAC-SHA256을 600k회 돌려 마스터 비밀번호에서 32바이트 AES 키를
뽑는다. 키는 메모리에만 있고 비밀번호는 어디에도 안 적으므로 `config.json`만으로는 키를 복구할 수
없다. `TryUnlock`은 `Verifier` 블롭을 풀어보는 것으로 비밀번호를 확인한다. 틀린 비밀번호는 GCM 태그
검사에서 걸리고, `AesGcmSecretProtector`가 이걸 빈 문자열로 돌려준다.

**시작 순서가 중요하다.** `App.OnFrameworkInitializationCompleted`가 컨테이너를 직접 만들지 않는
이유가 여기 있다. `JsonConnectionProfileStore`를 만들기 *전에* `config.json`을 읽고, 비밀번호를 받고,
키를 뽑아야 한다. 그래서 `StartAsync`는 게이트 창이 떠 있는 동안 `ShutdownMode.OnExplicitShutdown`을
쓴다. 안 그러면 `MainWindow`도 없는 상태에서 창을 닫는 순간 앱이 끝난다. 그다음
`OnMainWindowClose`로 바꾼다. 프롬프트에서 종료하면 앱이 내려간다. 키 없이는 할 수 있는 게 없다.

비밀번호를 잊었을 때는 `MasterPasswordViewModel`이 새 vault를 만들고 `DiscardedPreviousVault`를
세운다. 그러면 시작할 때 `sites.json`을 지운다. 그 안의 비밀을 더는 풀 수 없기 때문이다. vault
정의가 깨진 `config.json`도 같은 길로 간다.

`MasterPasswordViewModel.OnPasswordChanged`가 `ErrorMessage`를 지운다는 걸 기억할 것. 입력란을
비우면서 오류도 보여줘야 하는 코드는 **입력란을 먼저** 비워야 한다.

`JsonConnectionProfileStore`에 `JsonIgnoreCondition.WhenWritingDefault`를 쓰면 안 된다. 이 옵션은
`false`와 `0`을 빼먹는데, `ForcePathStyle`, `DisableRequestChecksums`, `TimeoutSeconds`,
`MaxConcurrentTransfers`는 전부 `true`나 0이 아닌 값으로 초기화된다. 빠진 속성은 로드할 때 초기값으로
돌아가므로, **꺼둔 설정이 조용히 다시 켜진다.**

**아무것도 저절로 디스크에 써지지 않는다.** 두 파일은 사용자가 시켜야 저장된다. `config.json`은 첫
실행에 새 vault를 기록할 때, 그다음부터는 설정 UI의 저장에서. `sites.json`은 Site Manager의 저장과
삭제에서. 종료할 때도 저장하지 않고, *접속*도 저장하지 않는다. 예전에는 접속이 프로필을 저장했는데,
Quickconnect가 매번 새 id를 만들다 보니 사이트가 하나씩 조용히 늘어났다.
`SiteManagerPersistenceTests`가 이걸 막고 있다.

두 저장소 다 자기가 쓴 걸 검증한다. rename한 뒤 파일을 다시 읽어 비교하고 다르면 예외를 던진다.
저장했다고 보고했는데 파일에 새 값이 없는 경우, 그러니까 반쯤 쓰인 임시 파일이나 속성을 빠뜨린
직렬화기를 잡으려는 장치다.

### sites.json 계약

디스크에 저장되는 모양(`SiteDocument`, `StoredSite`)은 `Core/Persistence`에 있고, UI가 바인딩하는
`ConnectionProfile`과 일부러 떼어놓았다. 둘이 만나는 곳은 `SiteMapper` 하나뿐이다. 이 상태를
유지하자. 도메인 모델이 곧 직렬화 계약이던 시절에는 public getter가 전부 저장 필드가 됐다. 파생
속성인 `Preset`이 제공자 카탈로그의 낡은 사본을 사이트마다 적어 넣었고, 프록시의 계산된 플래그도
같은 식으로 새어 나갔다.

엔드포인트에 닿는 방법을 담은 것은 전부 한 덩어리로 직렬화해 `connection` 블롭 하나로 암호화한다.
URL과 리전, 계정과 액세스 키, 시크릿, 세션 토큰, 버킷, 프리픽스, 프록시까지. 평문으로 남는 건 Site
Manager가 목록을 그리는 데 필요한 것(id, name, providerId)과 민감하지 않은 동작 스위치, 타임스탬프뿐이다.
**그래서 접속 설정을 추가할 때 이게 비밀인지 따질 필요도, 암호화 필드를 새로 만들 필요도 없다.**

`CreatedAt`(첫 저장)과 `LastModifiedAt`(매 저장)은 저장소가 직접 관리한다. `LastUsedAt`은 최근 사용
순 정렬을 위해 자리만 잡아뒀고 아직 아무도 쓰지 않는다.

`SiteDocument.Version`은 1이고 읽어야 할 레이아웃도 항상 하나다. 배포된 적이 없었으니 예전 사전
릴리즈 형태는 변환한 다음 그 리더를 남기지 않고 지웠다.

`StoredSite`의 호환성 스위치는 `ConnectionProfile`과 기본값이 같아야 한다. `ForcePathStyle`,
`DisableRequestChecksums`, `DisableChunkedEncoding` 전부 `true`다. `bool`의 기본값은 `false`이므로
이 중 하나가 빠진 채 저장된 사이트는 체크섬과 chunked 본문이 켜진 상태로 돌아온다. S3 호환
게이트웨이가 업로드를 전부 거부하게 만드는 바로 그 조건이다.

종료할 때 하는 일은 **`provider.DisposeAsync()` 하나뿐이다.** 뷰모델과 전송 큐를 비롯한 나머지는
컨테이너가 갖고 있고, 등록 역순으로 싱글턴을 폐기한다. 그중 뭐라도 한 번 더 명시적으로 폐기하면
이중 폐기가 되고, 그러면 큐의 취소 토큰 소스에서 `ObjectDisposedException`이 터져 종료할 때 앱이
죽는다. 같은 이유로 뷰모델은 자기가 만든 것만 정리한다. 자기 `TransferQueueViewModel`과 팩토리로
만든 클라이언트가 그렇다. 주입받은 의존성은 건드리지 않는다. 여기 있는 `DisposeAsync`는 전부 여러 번
불러도 괜찮아야 한다.

`ShutdownRequested`는 **동기** 이벤트다. `async` 핸들러는 첫 `await`에서 반환해버리고, 런타임은 일이
끝나지 않은 채로 프로세스를 내린다. 그래서 `App.ShutdownAsync`는 블로킹으로 기다리되 직접 await하지
않고 `Task.Run`을 거친다. `await using` 폐기에는 `ConfigureAwait(false)`가 붙어 있지 않아서
`FileStream.DisposeAsync`가 continuation을 블로킹된 UI 스레드로 돌려보내고, 그대로 멈춰버린다.
`Task.Run`이 동기화 컨텍스트를 지워주니 await를 하나씩 고치는 대신 이 문제를 통째로 없앨 수 있다.

저장소도 UI 스레드에서 블로킹으로 불린다. 그 안의 await는 **전부** 컨텍스트를 잡지 말아야 하고,
여기엔 `stream.ConfigureAwait(false)` 형태가 필요한 `await using` 폐기도 들어간다.
`BlockingCallerTests`가 펌프할 수 없는 컨텍스트로 교착을 재현하고, 실패 메시지에 문제가 된 await
이름을 담아준다.

두 저장소 다 `.tmp` 파일에 쓰고 rename한다. 이때 반드시 `AppPaths.CreateOwnerOnlyFile`로 연다.
`File.Create`는 안 된다. umask(흔한 유닉스에서 0644)가 적용돼서 뒤이어 chmod가 돌기 전까지
자격증명 파일이 열려 있게 된다. 그 헬퍼가 모드를 두 번 설정하는 건 의도한 것이다. `UnixCreateMode`가
새 파일을 덮고, 명시적 chmod가 중단된 저장이 남긴 낡은 임시 파일을 덮는다. `FileMode.Create`가 기존
파일의 모드를 그대로 두기 때문이다.

## 이 코드베이스의 관례

- 뷰는 `.axaml`이고 컴파일된 바인딩이 기본으로 켜져 있다(`AvaloniaUseCompiledBindingsByDefault`).
  뷰와 `DataTemplate` 전부에 `x:DataType`이 필요하다.
- `MainWindowViewModel`이 `ITransferCoordinator`를 구현한다. 업로드에는 원격 패널의 프리픽스가,
  다운로드에는 로컬 패널의 디렉터리가 필요하다. 그래서 두 패널을 다 가진 계층만 전송을 큐에 넣을 수
  있고, 패널끼리는 서로를 모른 채로 남는다. 전송 뒤 자동 새로고침도 여기서 한다. 완료가 워커
  스레드에서 오니 핸들러가 디스패처로 넘기고, 전송이 닿은 위치가 *지금* 보고 있는 위치인 패널만
  새로고침한다. 폴더 하나가 파일마다 완료를 하나씩 만들어내니 `RefreshDebouncer`를 거친다.
- 행을 활성화하면(`OpenCommand`, 더블클릭에 연결) 디렉터리와 프리픽스는 열고 나머지는 전송한다.
  두 패널이 이 구분을 똑같이 지켜야 한다.
- 마스터 비밀번호 입력란은 출력 가능한 ASCII만 받는다. 여기서 중요한 게 셋인데, 모두
  `MasterPasswordInputTests`가 headless로 실제 입력 파이프라인을 돌려 검증한다.
  - **`InputMethod.IsInputMethodEnabled="False"`를 설정하지 말 것.** 딱 맞는 도구처럼 보이지만
    아니다. 입력 컨텍스트를 끄면 macOS가 활성 레이아웃으로 매핑한 원시 키 이벤트를 보내는데, 한글
    레이아웃에서는 Shift로 대문자가 안 나온다. 그러면 같은 키를 눌러도 입력 모드에 따라 *다른*
    비밀번호가 만들어진다. 마스킹된 입력란이라 눈에 보이지도 않는다. 사용자가 다시 칠 수 없는
    비밀번호로 vault가 만들어지는 경로가 바로 이거다. IME는 돌게 두고 결과만 거르자.
  - `TextInput` 핸들러는 코드비하인드에서 `RoutingStrategies.Tunnel`로 붙여야 한다.
    `TextInputEvent`는 `Tunnel, Bubble`로 라우팅되고 `TextBox.OnTextInput`은 **버블 단계의 클래스
    핸들러**다. XAML에 `TextInput="..."`으로 달면 텍스트가 이미 들어간 *뒤에* 실행되고, 거기서
    `Handled`를 세워봐야 소용없다. 실제로 막을 수 있는 자리는 터널 단계뿐이다.
  - `TextChanged` 보정이 `TextInput`을 아예 일으키지 않는 경로, 즉 붙여넣기를 걷어낸다. 덕분에
    입력란에 보이는 것과 실제로 쓰이는 비밀번호가 항상 같다.

  뷰모델에서만 걸러내는 방식은 **먹히지 않는다.** 바인딩이 대상에서 소스로 갱신되는 중에는 고쳐 넣은
  값이 `TextBox`로 되돌아가지 않아서, 거부된 문자가 입력란에 그대로 남는다.
  `MasterPasswordViewModel.RemoveDisallowed`는 공유 규칙이자 속성을 직접 설정하는 코드에 대한 마지막
  방어선으로 남겨둔다. `OnPasswordChanged`가 `ErrorMessage`를 지우니 그쪽의 "다시 넣고 나서 보고"
  순서도 의도한 것이다.
- 코드비하인드는 MVVM으로 안 되는 뷰 상태 배선에만 쓴다. `DataGrid.SelectedItems`가 바인딩 가능한
  속성이 아니라서 `LocalPaneView`와 `RemotePaneView`가 선택을 뷰모델로 넘기고 더블클릭 활성화를
  처리한다. 비즈니스 로직은 여기 두지 않는다. `TransferQueueView`는 우클릭한 행을 선택하는 일도
  한다. Avalonia의 `DataGrid`가 그렇게 해주지 않아서인데, 안 하면 컨텍스트 메뉴 명령이 이전 선택을
  대상으로 돈다.
- Core의 버킷 타입 이름은 `BucketInfo`가 아니라 `StorageBucket`이다. 앞의 것은
  `Amazon.S3.Model.BucketInfo`와 부딪힌다.
- 로그 색은 `LogLevelConverters`가 붙이는 스타일 클래스(`Classes.command`, `Classes.response`,
  `Classes.error`)로 처리한다. 팔레트는 `AppStyles.axaml`에 남는다.
- 파일 패널의 행 아이콘은 이모지가 아니라 직접 그린 도형이다. `📁`와 `📄`는 Windows와 macOS에서는
  멀쩡해 보이지만, 번들된 폰트는 Inter뿐이고 Inter에는 이모지가 없다. 이모지 폰트가 없는 컴퓨터에서는
  fontconfig가 아무거나 골라 넣고, 실제로는 줄무늬 상자가 뜬다. self-contained 빌드가 특정 폰트가
  깔려 있기를 기대하면 안 된다. 시스템 라이브러리에 기대면 안 되는 것과 같은 이야기다. 도형은
  `ListingConverters`에 있다.
- 값이 없는 셀에 0을 찍지 않는다. 디렉터리와 프리픽스의 `Size`는 `-`로 나가고(`ByteSize.Format`의
  `isContainer` 오버로드), 타임스탬프가 없는 행의 Modified는 빈칸이다. `StringFormat` 바인딩이 null을
  값 타입 기본값으로 그려서 `0001-01-01 00:00`을 만들기 때문에 컨버터를 쓴다.
  `FilePaneColumnTests`가 실제 패널을 headless로 그려 셀을 읽는 것으로 이걸 고정한다.
