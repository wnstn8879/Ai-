# 개발 결과 — 2026-11-10

## 1. 실제 구현

이번 변경은 `develop/storyverse-foundation`의 기존 기능을 유지하며 인증·개인 보관함·친구·멀티플레이 기반을 구현한 검증 단위입니다. 공개 서버에는 배포하지 않았습니다.

- 이메일 가입/로그인/로그아웃, 사용자 ID/프로필, scrypt 해싱, 해시 기반 서버 세션과 원자적 토큰 회전.
- Expo SecureStore 세션 보관, 갱신 요청 합치기, 만료 시 로그인 이동과 계정 데이터 초기화.
- 사용자별 소유/참여 스토리, 최근 플레이 순 정렬, 자동 메시지 저장, 개인 체크포인트, 마지막 장면 재개, 독립 분기와 부모 표시.
- 친구 검색·요청·수락·거절, 친구 목록, 일회용 초대 코드와 방장 검사, 참가자 캐릭터 배정, 나가기와 재초대 참여.
- WebSocket 인증/재연결/DB 기록 복원, 메시지 위치 잠금과 고유 인덱스, 요청 ID로 저장 중복 방지, 멀티플레이 발언자 위조 차단.
- 기존 AI 턴 유지, 실패 시 메시지 미저장, 오래된 생성 결과의 충돌 거부, 사용자/방별 일일 AI 시도 한도.
- 다크 모드, 홈/보관함/친구/설정 탭, 키보드 대응과 로딩/오류/빈 상태, 저장 성공 표시.
- 장면·중요 사실·캐릭터 성격/말투/목표/관계/상태/기억 편집과 변경 이력, 상태 버전 충돌 검사.
- 체크포인트를 정확한 스냅샷에 고정하고 분기에 과거 상태 이력까지 복사. 같은 메시지 위치에서 나중에 설정을 바꿔도 저장 당시 상태로 복원.
- AI 문맥에 편집한 상태와 기억을 포함하고 생성 중 상태가 바뀌면 응답 저장 차단. 모델의 실제 기억 준수율은 미검증.
- 새로고침·저장 시 대사 초안 보존, 상태 편집 중 외부 변경 충돌 표시, 단일 WebSocket 재연결 컨트롤러.
- 계정 전환/로그아웃 뒤 지연된 HTTP·토큰 갱신 응답 폐기, 이전 토큰의 늦은 401로 인한 불필요한 재갱신 방지.
- 개인/공용 저장 구분, 저장 당시 캐릭터 배정 고정, 현재 참가자 전원 동의 후 방장이 실행하는 비파괴 공용 복원.
- 동의 철회/거절/취소/만료, 진행·상태·참가자 출입·배정 변경에 따른 동의 무효화, 동시/중복 복원 단일 결과 보장.
- 원본은 유지하며 저장 시점의 새 멀티플레이 방에 현재 참가자와 역할을 복사. 원래 방 ID 안의 파괴적 롤백은 제공하지 않음.

## 2. 변경 파일

- `backend/app/database.py`: 기존 SQLAlchemy 모델과 연결 설정 분리, SQLite 외래키 활성화.
- `backend/app/security.py`: 계정·세션·친구·멤버십·초대·권한·AI 한도.
- `backend/app/main.py`: 모든 스토리 API 인증/ACL, 최근 기록, 개인 저장/분기, 요청 영수증, WebSocket.
- `backend/app/shared_restores.py`: 공용 복원 제안·동의·철회·유효성·실행과 권한.
- `backend/app/story_state.py`: 상태 스키마·편집 권한·이력·충돌 검사·상태 복사.
- `backend/app/story_ai.py`: 기존 어댑터를 유지하며 캐릭터/장면/기억 문맥 추가.
- `backend/migrations/`, `backend/alembic.ini`, `backend/requirements.txt`, `backend/.env.example`: 마이그레이션과 실행 설정.
- `backend/tests/`: 기존 분기·AI·영속성 테스트를 인증 흐름에 연결, 권한/세션/동시성/WebSocket/마이그레이션/AI 한도 회귀 테스트.
- `mobile/App.js`, `mobile/api.js`: 모바일 화면과 인증·자동 갱신·친구·초대·실시간 클라이언트.
- `mobile/SharedRestores.js`: 공용 저장·동의 상태·철회·복원 화면.
- `mobile/scripts/android_smoke.py`: Android 네이티브 로그인/키보드/메시지/공용 복원 QA 스크립트.
- `mobile/StoryStateEditor.js`, `mobile/liveRoom.js`: 상태 편집 화면과 단일 재연결 컨트롤러.
- `mobile/session.test.cjs`, `mobile/liveRoom.test.cjs`, `mobile/package.json`, `mobile/package-lock.json`: 세션 회귀 테스트와 호환 버전 고정.
- `mobile/app.json`, `mobile/eas.json`: Android 패키지·키보드·보안 저장·내부 APK/운영 AAB 프로필.
- `.github/workflows/backend-tests.yml`, `.gitignore`, `README.md`, `docs/`: CI와 실행/보존/제한 문서.

## 3. DB 변경

기존 `rooms`, `messages`, `saves`와 기록을 유지합니다. `users`, `user_sessions`, `room_members`, `save_owners`, `friendships`, `invitations`, `message_receipts`, `ai_usage`, `scene_states`, `save_snapshots`를 추가하고 외래키/검색 인덱스와 메시지 위치 고유 인덱스를 도입했습니다. 소유자가 불명인 과거 방은 그대로 보존하며 계정에 자동 배정하지 않습니다. 마이그레이션은 001→002→003→004→005 순서입니다. 005는 기존 저장을 private로 보존하면서 saves.scope와 공용 저장 당시 캐릭터 배정/참가자 세대/복원 제안/투표를 추가합니다. 004는 기존 세계관 규칙과 캐릭터 이름을 상태 버전 0으로 보존하고 기존 체크포인트에 연결합니다.

## 4. 테스트 결과

- 변경 전 기준 코드: pytest **5개 통과**.
- 최종 기능 검증: SQLite pytest **33개 통과**, GitHub Actions PostgreSQL 17 pytest **33개 통과**.
- 모바일 세션: Node 테스트 **12개 통과**. 동시/지연 갱신, 계정 변경 후 지연 응답, 깨진 세션, 네트워크 장애, 중복 WebSocket·재연결·중지·권한 상실을 검증했습니다. 실제 OS SecureStore 대신 테스트 대역을 사용합니다.
- Expo 호환성 검사 통과. React Native를 Expo SDK 54에 맞는 0.81.5로 수정했습니다.
- Android JS/Hermes 번들, 네이티브 prebuild, GitHub Actions debug APK 빌드 성공. 에뮬레이터 결과는 아래에 기록합니다.
- 초기 중복 메시지 테스트가 영수증 저장 누락을 발견했고 수정 후 통과했습니다. 백엔드와 모바일 회귀 테스트 실패는 없습니다. Android 네이티브 작업 결과는 아래에 별도로 기록합니다. FastAPI/Starlette의 TestClient 의존성 사용 중단 안내 경고가 1개 있습니다.
- 기존 원격 CI는 PostgreSQL 상태 확인 명령의 따옴표 처리 오류로 테스트 시작 전에 실패했습니다. 명령을 수정하고 SQLite 작업에서는 컨테이너를 생략했으며 매트릭스 실패 전파도 해제했습니다. 수정 후 [GitHub Actions 실행 #11](https://github.com/wnstn8879/Ai-/actions/runs/42742302320)에서 SQLite·PostgreSQL·모바일 세 작업이 모두 성공했습니다.

## 5. Android와 외부 서비스

이 작업 환경의 로컬 Gradle 다운로드 오류와 SDK 부재를 피하기 위해 GitHub Actions에 Android SDK·Java 17·Gradle 빌드 작업을 추가했습니다. SDK 설치가 폐기된 `tools` 패키지를 요청하던 문제를 수정한 뒤 **debug APK 빌드가 성공**했습니다. [APK 아티팩트](https://github.com/wnstn8879/Ai-/actions/runs/42755850593/artifacts/13735931713)는 Metro가 필요한 개발용 APK입니다.

초기 에뮬레이터 QA에서 로그인·키보드·메시지 저장이 확인되었고, 상태 편집/공용 복원 영역의 중복 React 키가 오류 배너를 띄워 공용 저장 터치를 가리는 문제를 발견했습니다. 키를 영역별로 분리하고 폐기된 SafeAreaView를 Safe Area Provider로 교체했습니다. 수정본 APK 빌드와 회귀 테스트가 통과했고, **Android API 35 에뮬레이터 QA도 통과**했습니다. 네이티브 로그인, 프로세스 종료/재실행 후 SecureStore 세션 유지, 스토리 불러오기, 소프트 키보드/입력창, 메시지 저장, 공용 체크포인트 생성, 다른 계정의 명시적 동의, 전원 동의 복원 실행, 복원 방 화면 이동, 원본 기록과 두 참가자 유지를 확인했습니다. 두 번째 계정은 API로 참여했으며 두 대의 Android 기기를 동시에 검증한 것은 아닙니다. 키보드가 입력창을 가리지 않는 화면과 복원 방 화면을 직접 확인했습니다.

[최종 코드 검증 실행 #19](https://github.com/wnstn8879/Ai-/actions/runs/42755850593)의 SQLite·PostgreSQL·모바일·Android 네 작업이 모두 성공했습니다. [QA 증거 아티팩트](https://github.com/wnstn8879/Ai-/actions/runs/42755850593/artifacts/13736116621)에 결과 JSON과 화면/로그를 보관했습니다. 검증 코드 커밋은 `ef66208`입니다. 운영 서명 APK/AAB와 실제 기기 테스트는 미완료입니다. 검증 절차와 로컬 실행법은 [Android QA 안내](android-qa.md)에 있습니다.

실제 LLM 키와 운영 PostgreSQL 접속 정보는 제공되지 않았습니다. AI는 테스트 대역으로 실패/원자적 저장을 검증했고 PostgreSQL은 로컬 격리 컨테이너로 검증했습니다. 실제 AI 응답과 운영 DB 연결 성공은 미확인입니다. EAS 빌드에는 사용자의 Expo/EAS 계정·프로젝트 및 HTTPS API 설정이 필요합니다.

## 6. 아직 구현하지 않은 기능

- 원본 방의 같은 ID 안에서 기록을 잘라내는 파괴적 롤백은 제공하지 않습니다. 전원 동의에 따른 새 공용 방 복원은 구현했습니다.
- AI가 자동으로 사건을 추출·요약하고 장기 기억을 검색하는 기능. 현재 상태와 기억은 사용자가 명시적으로 편집합니다.
- 사용자 사전 동의/방 설정에 따른 AI 캐릭터 대역.
- 초대 링크/딥링크, 방장 위임, 강제 퇴장, 친구 삭제/차단.
- 이메일 소유 확인, 비밀번호 찾기, 전체 기기 세션 관리, 운영용 공유 레이트리미터.
- 미완료 동일 AI 요청의 중복 외부 호출 차단, 실제 토큰 비용 정산, 여러 LLM 공급자 선택.
- 앱 종료에도 보존되는 발신 큐, 증분 이벤트·페이지네이션·대규모 동시접속 부하 검증.
- 커뮤니티와 창작자 수익화.

## 7. GitHub

저장소: https://github.com/wnstn8879/Ai-

기준: `develop/storyverse-foundation` → 작업: `feat/storyverse-auth-library-social`.

[초안 PR #1](https://github.com/wnstn8879/Ai-/pull/1)에 변경을 반영했습니다. 최근 단계 커밋은 `c36716a`(공용 저장/전원 동의 복원), `d5ad72f`(공용 UI), `6ef8318`(Android QA), `3da622b`(SDK 패키지 수정), `ef66208`(실행 중 발견한 중복 키/안전 영역 수정)입니다. 기준 개발 브랜치로 검토하며 main으로 병합하지 않습니다. `main` 병합과 공개 배포는 수행하지 않습니다.

## 8. 다음 우선순위

1. 실제 Android 두 기기에서 채팅/공용 동의/상태 편집/재연결/키보드 QA, 운영 서명 빌드 환경 준비.
2. 앱 종료에도 보존되는 초안과 전송 큐, 큰 대화 기록의 페이지네이션.
3. 이메일 확인/복구와 공유 제한, 전체 세션 관리, 운영 로그·보존·부하 검증.
4. 실제 AI 연결·장기 메모리·요청 큐·토큰별 비용 관리, 동의 기반 대역.
