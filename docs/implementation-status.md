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

## 2. 변경 파일

- `backend/app/database.py`: 기존 SQLAlchemy 모델과 연결 설정 분리, SQLite 외래키 활성화.
- `backend/app/security.py`: 계정·세션·친구·멤버십·초대·권한·AI 한도.
- `backend/app/main.py`: 모든 스토리 API 인증/ACL, 최근 기록, 개인 저장/분기, 요청 영수증, WebSocket.
- `backend/app/story_ai.py`: 기존 어댑터 보존, 코드 포맷 정리.
- `backend/migrations/`, `backend/alembic.ini`, `backend/requirements.txt`, `backend/.env.example`: 마이그레이션과 실행 설정.
- `backend/tests/`: 기존 분기·AI·영속성 테스트를 인증 흐름에 연결, 권한/세션/동시성/WebSocket/마이그레이션/AI 한도 회귀 테스트.
- `mobile/App.js`, `mobile/api.js`: 모바일 화면과 인증·자동 갱신·친구·초대·실시간 클라이언트.
- `mobile/session.test.cjs`, `mobile/package.json`, `mobile/package-lock.json`: 세션 회귀 테스트와 호환 버전 고정.
- `mobile/app.json`, `mobile/eas.json`: Android 패키지·키보드·보안 저장·내부 APK/운영 AAB 프로필.
- `.github/workflows/backend-tests.yml`, `.gitignore`, `README.md`, `docs/`: CI와 실행/보존/제한 문서.

## 3. DB 변경

기존 `rooms`, `messages`, `saves`와 기록을 유지합니다. `users`, `user_sessions`, `room_members`, `save_owners`, `friendships`, `invitations`, `message_receipts`, `ai_usage`를 추가하고 외래키/검색 인덱스와 메시지 위치 고유 인덱스를 도입했습니다. 소유자가 불명인 과거 방은 그대로 보존하며 계정에 자동 배정하지 않습니다. 마이그레이션은 001→002→003 순서입니다.

## 4. 테스트 결과

- 변경 전 기준 코드: pytest **5개 통과**.
- 최종 기능 검증: SQLite pytest **15개 통과**, 로컬 테스트 전용 PostgreSQL 17 pytest **15개 통과**.
- 모바일 세션: Node 테스트 **4개 통과**. 동시 갱신, 갱신 폐기, 로그아웃/계정 전환, 네트워크 장애를 검증했습니다. 실제 OS SecureStore 대신 테스트 대역을 사용합니다.
- Expo 호환성 검사 통과. React Native를 Expo SDK 54에 맞는 0.81.5로 수정했습니다.
- Android JS/Hermes 번들 생성 성공. 네이티브 프로젝트 prebuild 성공.
- 초기 중복 메시지 테스트가 영수증 저장 누락을 발견했고 수정 후 통과했습니다. 최종 실패 테스트는 없습니다. FastAPI/Starlette의 TestClient 의존성 사용 중단 안내 경고가 1개 있습니다.
- 새 CI는 SQLite/PostgreSQL, 모바일 세션, 호환성 검사, Android 번들 검증을 포함합니다. 원격 실행 결과는 PR에서 별도로 확인해야 합니다.

## 5. Android와 외부 서비스

Android 네이티브 APK 빌드는 임시 프로젝트에서 `gradlew assembleDebug`로 시도했지만 Gradle 배포본 다운로드 중 `java.net.ConnectException: Connection refused`로 중단되었습니다. 이 환경에는 Android SDK도 준비되어 있지 않습니다. APK/AAB 빌드 성공, 에뮬레이터/실기기 실행, 키보드·작은 화면·백그라운드 복귀 동작을 검증했다고 주장하지 않습니다.

실제 LLM 키와 운영 PostgreSQL 접속 정보는 제공되지 않았습니다. AI는 테스트 대역으로 실패/원자적 저장을 검증했고 PostgreSQL은 로컬 격리 컨테이너로 검증했습니다. 실제 AI 응답과 운영 DB 연결 성공은 미확인입니다. EAS 빌드에는 사용자의 Expo/EAS 계정·프로젝트 및 HTTPS API 설정이 필요합니다.

## 6. 아직 구현하지 않은 기능

- 공용 체크포인트와 참가자 동의에 따른 공용 진행 되돌리기.
- 메시지 시점별 동적 세계관·캐릭터 상태 스냅샷, 장기 사건/관계 메모리.
- 사용자 사전 동의/방 설정에 따른 AI 캐릭터 대역.
- 초대 링크/딥링크, 방장 위임, 강제 퇴장, 친구 삭제/차단.
- 이메일 소유 확인, 비밀번호 찾기, 전체 기기 세션 관리, 운영용 공유 레이트리미터.
- 미완료 동일 AI 요청의 중복 외부 호출 차단, 실제 토큰 비용 정산, 여러 LLM 공급자 선택.
- 앱 종료에도 보존되는 발신 큐, 증분 이벤트·페이지네이션·대규모 동시접속 부하 검증.
- 커뮤니티와 창작자 수익화.

## 7. GitHub

저장소: https://github.com/wnstn8879/Ai-

기준: `develop/storyverse-foundation` → 작업: `feat/storyverse-auth-library-social`.

변경은 기능별 커밋으로 기록하며 이 브랜치에서 기준 개발 브랜치로 PR을 생성합니다. 커밋·PR의 정확한 링크는 최종 작업 보고에 제공합니다. `main` 병합과 공개 배포는 수행하지 않습니다.

## 8. 다음 우선순위

1. Android SDK/EAS 환경에서 APK 빌드 후 두 계정·두 기기 채팅/초대/재연결/키보드 QA.
2. 세계관/캐릭터 상태 버전과 체크포인트 스냅샷, 공용 저장·동의 절차.
3. 이메일 확인/복구와 공유 제한, 전체 세션 관리, 운영 로그·보존·부하 검증.
4. 실제 AI 연결·장기 메모리·요청 큐·토큰별 비용 관리, 동의 기반 대역.
