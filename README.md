# StoryVerse AI

사용자가 만든 세계관에서 혼자 또는 초대한 친구와 이야기를 진행하는 Android 우선 Expo 앱입니다. 기존 방·메시지·체크포인트·평행세계·서버 LLM 어댑터를 유지하면서 계정과 비공개 접근 권한을 추가했습니다. 현재 개발 단계이며 공개 배포하지 않았습니다.

## 실행

Python 3.12+, Node 22+, Android용 Expo Go 또는 Android 개발 환경을 사용합니다.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
# 기존 DB를 사용한다면 먼저 백업하세요.
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0
```

기본 DB는 `backend/storyverse.db` SQLite입니다. PostgreSQL은 `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB`로 설정한 뒤 **동일한 환경변수로** 마이그레이션과 서버를 실행합니다. `.env` 파일을 사용할 때는 `uvicorn --env-file`을 지정하고, Alembic에도 환경변수를 전달해야 합니다. 환경 파일은 자동으로 로드되지 않습니다.

```sh
cd mobile
npm ci
npm start
```

Android 에뮬레이터 기본 주소는 `http://10.0.2.2:8000`입니다. 실기기에서는 `mobile/.env.example`을 참고해 `EXPO_PUBLIC_API_URL`을 LAN 서버 주소로 설정하세요. 릴리스 앱은 HTTPS 주소가 필요합니다. Expo 환경변수 변경 후 Metro를 다시 실행하세요.

AI 기능만 서버의 `OPENAI_API_KEY`가 필요합니다. `OPENAI_MODEL`로 모델을 선택하고, `AI_USER_DAILY_LIMIT` / `AI_ROOM_DAILY_LIMIT`으로 UTC 기준 일일 요청 시도 한도를 조정합니다(기본 100/300). 실패한 호출도 한도에 포함됩니다. 키 없이도 인증·친구·초대·참가자 메시지·저장·분기를 사용할 수 있습니다. 비밀키를 `EXPO_PUBLIC_*`에 넣지 마세요.

## 구현된 흐름

- 이메일 회원가입·로그인·로그아웃, scrypt 비밀번호 해싱, 토큰 해시만 저장하는 서버 세션.
- 15분 접근 토큰과 회전하는 30일 갱신 토큰. 모바일은 SecureStore를 사용하며 갱신 실패 시 계정 화면과 이전 데이터를 비웁니다.
- 소유·참여 권한이 있는 방만 보관함에 표시. 최근 플레이 순 정렬, 혼자/함께 필터, 마지막 장면 재개.
- 개인 체크포인트와 독립된 개인 평행세계 생성. 멀티플레이에서 분기해도 원본 참가자에게 개인 분기가 공개되지 않습니다.
- 이름/ID 사용자 검색, 친구 요청·수락·거절, 친구 목록. 검색 결과에 이메일을 공개하지 않습니다.
- 방장만 발급하는 24시간 유효 1회용 초대 코드, 참가자 역할·캐릭터 배정, 나가기·새 초대로 재참여.
- 인증된 WebSocket 스냅샷과 재연결, DB 메시지 순서·요청 ID 중복 방지. 모델 생성 중 대화가 변경되면 오래된 응답은 저장하지 않고 409를 반환합니다.
- 다크 UI, 하단 내비게이션, 키보드 대응 설정, 로딩·오류·빈 상태·저장 결과 표시.

## 테스트와 빌드

```sh
cd backend
PYTHONPATH=. python -m pytest -q
# 별도의 빈 테스트 DB에서만 실행하세요. 테스트가 계정/방을 생성합니다.
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/TEST_DB PYTHONPATH=. python -m pytest -q
cd ../mobile
npm test
npx expo install --check
npm run check
```

`npm run check`는 Android JS/Hermes 번들 검증이며 APK 빌드가 아닙니다. `eas.json`에는 내부 APK와 운영 AAB 빌드 프로필이 있습니다. EAS 계정·프로젝트와 HTTPS API 주소를 설정한 후 `eas build --platform android --profile preview`로 빌드할 수 있습니다. 네이티브 로컬 빌드는 Android SDK가 필요합니다.

GitHub Actions에서 SQLite/PostgreSQL 회귀 테스트, 모바일 세션 테스트, Expo 의존성 검사, Android 번들 생성을 실행합니다. 실기기 동작과 실제 AI 호출은 자동 테스트 결과와 별개입니다.

## 데이터와 남은 작업

기존 무인증 방은 보존되지만 소유자 정보를 알 수 없어 기본적으로 접근이 차단됩니다. 첫 가입자에게 자동 귀속시키지 않습니다. [저장·마이그레이션 안내](docs/persistence.md)와 [구현 결과 및 남은 작업](docs/implementation-status.md)을 확인하세요.

공용 체크포인트·참가자 동의에 의한 롤백, 세계/캐릭터 상태 스냅샷과 장기 메모리, 사전 동의 기반 AI 대역, 계정 복구·이메일 확인, 운영 수준 분산 제한과 부하 검증, Android 실기기 QA는 후속 단계입니다. 공개 서비스 배포는 이 검증이 끝나기 전 진행하지 않습니다.
