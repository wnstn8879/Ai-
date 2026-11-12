# Android 네이티브 빌드·QA

`StoryVerse checks`의 `android-native` 작업은 PR에서 실행합니다. 기존 JS/Hermes 번들 검사와 별도로 Android SDK, Java 17, Expo prebuild, Gradle을 사용해 debug APK를 빌드합니다. APK 생성이 성공하면 `storyverse-android-debug` 아티팩트에 업로드합니다.

## 자동 에뮬레이터 검증

Pixel 2 프로필의 Android API 35 x86_64 에뮬레이터 두 대에서 다음을 실행하도록 확장했습니다. 실제 스마트폰 두 대와는 구분합니다.

1. 격리된 SQLite DB와 QA용 FastAPI/Metro를 시작합니다. 외부 AI 키와 운영 DB를 사용하지 않습니다.
2. 테스트 계정 2개와 멀티플레이 방을 만듭니다.
3. 소유자 계정으로 네이티브 앱에서 로그인하고 프로세스를 종료·재실행하여 보안 저장 세션 복원을 확인한 뒤 스토리를 엽니다.
4. 실제 Android 텍스트 입력과 소프트 키보드 표시를 확인하고 화면을 캡처합니다.
5. 초안 저장 완료 후 프로세스를 종료·재실행하여 메시지 입력을 복원합니다.
6. 서버를 일시 정지한 상태에서 메시지를 기기 큐에 저장하고 앱을 강제 종료한 뒤, 서버/앱 재개 후 한 번만 저장되는지 확인합니다.
7. 두 번째 에뮬레이터에서 다른 계정으로 로그인하고 네이티브 UI로 메시지를 보냅니다. 첫 기기에서 그 메시지의 실시간 수신을 확인합니다.
8. 첫 기기가 공용 저장·복원을 제안하고, 두 번째 기기가 네이티브 UI로 명시적으로 동의합니다.
9. 첫 기기가 복원을 실행하고 두 기기가 복원된 공용 방을 엽니다. 원본 보존·복원 위치·두 참가자 유지를 확인합니다.

검증 스크립트는 `mobile/scripts/android_smoke.py`입니다. 에뮬레이터 작업을 추가한 사실과 실제 통과 여부는 구분해야 합니다. [검증 실행 #19](https://github.com/wnstn8879/Ai-/actions/runs/42755850593)에서 전체 시나리오가 통과했습니다. 마지막 실행 결과는 `docs/implementation-status.md`와 GitHub Actions에서 확인합니다. 이전 실행 #19는 한 에뮬레이터와 별도 API 계정으로 검증했습니다. [실행 #27](https://github.com/wnstn8879/Ai-/actions/runs/43239165687)에서는 두 에뮬레이터의 로그인·동시 채팅·동의·복원과 초안 재시작 복원, 응답 유실 후 메시지 단일 저장까지 통과했습니다. 실기기 검증은 별도입니다.

`storyverse-android-qa-evidence` 아티팩트에는 실행 결과 JSON, 키보드/복원 화면 PNG, 마지막 UI 계층 XML, logcat과 QA 서비스 로그를 보관합니다. 테스트에 실패하면 가능한 경우 실패 화면도 캡처합니다. 테스트 계정만 사용하며 토큰을 결과 파일에 기록하지 않습니다.

## 로컬 실행

Android SDK/에뮬레이터와 Java 17을 준비하고 `README.md`대로 백엔드 의존성과 DB 마이그레이션을 적용하세요.

```sh
cd mobile
npm ci
npx expo prebuild --platform android --no-install
./android/gradlew -p android assembleDebug --no-daemon --max-workers=2
```

debug APK는 Metro가 필요한 개발용 빌드입니다. 운영 서명 APK/AAB 또는 독립 배포용 릴리스 빌드가 아닙니다. 실제 기기에서 USB로 확인할 때는 다음과 같이 앱이 기기 루프백을 통해 개발 PC에 접근하도록 설정할 수 있습니다.

```sh
adb reverse tcp:8081 tcp:8081
adb reverse tcp:8000 tcp:8000
EXPO_PUBLIC_API_URL=http://127.0.0.1:8000 npx expo start --localhost --port 8081
adb install -r -t android/app/build/outputs/apk/debug/app-debug.apk
```

릴리스 앱의 HTTPS 요구사항은 유지합니다. EAS 운영 빌드는 계정·프로젝트·HTTPS API와 서명을 별도로 설정해야 합니다. 생성된 `mobile/android/`는 Expo가 관리하는 네이티브 산출물이므로 이번 변경에 커밋하지 않습니다.

## 실제 기기에서 남은 확인

- 서로 다른 두 Android 기기로 동시 채팅·동의·복원, Wi-Fi/모바일 데이터 전환과 재연결.
- 작은 화면·큰 글꼴·키보드 종류 변경 시 입력창과 버튼이 가려지지 않는지.
- 백그라운드 복귀·프로세스 종료·재실행·토큰 만료 이후 세션과 대화 복원.
- 앱 화면의 로딩·오류·동의 만료·진행 변경 안내를 실제 사용자 관점에서 확인.

에뮬레이터 결과를 실기기 검증 완료로 표시하지 않습니다.
