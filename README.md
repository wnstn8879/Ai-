# IMAGINE

**Your Story, Your World, Your Choice.**

AI 기반 참여형 스토리 창작·게임 플랫폼. 내 상상을 세계로 만들고 친구와 함께 탐험하는 것이 핵심입니다. [제품 방향과 구현 상태](docs/imagine-product-direction.md)를 참고하세요. 저장소/내부 패키지 이름은 기존 StoryVerse를 유지합니다.

사용자가 만든 세계관에서 혼자 또는 초대한 친구와 이야기를 진행하는 Android 우선 Expo 앱입니다. 기존 방·메시지·체크포인트·평행세계·서버 LLM 어댑터를 유지하면서 계정과 비공개 접근 권한을 추가했습니다. 현재 개발 단계이며 소유자 전용 온라인 창작실을 배포했습니다. 불특정 다수 대상의 공개 서비스는 아닙니다.

## 휴대폰에서 온라인 체험

[IMAGINE 온라인 창작실 열기](https://imagine-story-world.angksehdfur2468.chatgpt.site) — 휴대폰 브라우저에서 이 사이트를 만든 ChatGPT 계정으로 로그인합니다. APK 설치 없이 자유 주제 소설·인물 기억·구절 분기·저장 지점을 확인할 수 있습니다. 실제 AI는 임시 개발 서버에 연결하므로 서버가 멈추면 생성이 중단되고 마지막 동기화 기록만 읽을 수 있습니다. [이용·운영·검증 범위](docs/online-preview.md)를 확인하세요.

이전에 만든 [기기 단독 체험 APK](docs/phone-preview.md)는 미리 작성한 이야기로 UI·저장을 확인하는 과거 데모입니다. 현재 자유 창작 체험은 위 온라인 창작실을 사용합니다.

## 이용자 경험의 목표

출근길에는 짧은 사건을 즐기고 자연스럽게 쉬며, 원하면 혼자 오래 이어갑니다. 플레이 기록을 보존하고 원하는 과거 장면에서 원본을 남긴 채 새 분기를 만듭니다. 이용자용 앱은 PC 없이 휴대폰에서 실행하는 것이 목표입니다. 온라인 debug APK는 개발용이며 실제 AI/멀티플레이 이용에는 상시 HTTPS 서버와 배포 설정이 필요합니다. UI·저장·분기용 단독 체험 APK는 위 안내에서 받을 수 있습니다. [모바일 플레이 흐름과 검증 범위](docs/mobile-play-loop.md)를 참고하세요.

## 개발 환경 실행

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

OpenAI 공급자 사용 시에만 서버의 `OPENAI_API_KEY`가 필요합니다. Ollama의 오픈소스 Qwen 모델은 외부 API 키 없이 사용할 수 있습니다. `OPENAI_MODEL`로 모델을 선택하고, `AI_USER_DAILY_LIMIT` / `AI_ROOM_DAILY_LIMIT`으로 UTC 기준 일일 요청 시도 한도를 조정합니다(기본 100/300). 실패한 호출도 한도에 포함됩니다. 키 없이도 인증·친구·초대·참가자 메시지·저장·분기를 사용할 수 있습니다. 비밀키를 `EXPO_PUBLIC_*`에 넣지 마세요.

## 구현된 흐름

- 이메일 회원가입·로그인·로그아웃, scrypt 비밀번호 해싱, 토큰 해시만 저장하는 서버 세션.
- 15분 접근 토큰과 회전하는 30일 갱신 토큰. 모바일은 SecureStore를 사용하며 갱신 실패 시 계정 화면과 이전 데이터를 비웁니다.
- 소유·참여 권한이 있는 방만 보관함에 표시. 최근 플레이 순 정렬, 혼자/함께 필터, 마지막 장면 재개.
- 개인 체크포인트와 독립된 개인 평행세계 생성. 멀티플레이에서 분기해도 원본 참가자에게 개인 분기가 공개되지 않습니다.
- 이름/ID 사용자 검색, 친구 요청·수락·거절, 친구 목록. 검색 결과에 이메일을 공개하지 않습니다.
- 방장만 발급하는 24시간 유효 1회용 초대 코드, 참가자 역할·캐릭터 배정, 나가기·새 초대로 재참여.
- 장면·중요 사실·캐릭터 성격/말투/목표/관계/상태/기억 편집, 버전 충돌 검사, 개인 체크포인트에 고정된 상태 복원.
- 편집한 상태와 기억을 AI 대화 문맥에 전달하고 생성 중 설정 변경 시 오래된 응답 저장 차단.
- 인증된 WebSocket 스냅샷과 중복 연결을 방지하는 재연결, DB 메시지 순서·요청 ID 중복 방지. 모델 생성 중 대화가 변경되면 오래된 응답은 저장하지 않고 409를 반환합니다.
- 공용 체크포인트, 현재 참가자 전원 동의와 방장 실행에 따른 새 멀티플레이 방 복원. 원본과 저장 당시 캐릭터 배정 보존, 동의 철회·만료·진행 변경·중복 실행 검사.
- 기기 SQLite 초안·전송 큐, 서버/계정/방 분리, 동일 요청 ID 재전송, 일반 메시지 자동 재시도와 AI 수동 확인. [큐 동작과 제한](docs/outbox.md).
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

GitHub Actions에서 SQLite/PostgreSQL 회귀 테스트, 모바일 세션 테스트, Expo 의존성 검사, Android 번들 생성을 실행합니다. PR에는 debug APK 빌드와 네이티브 에뮬레이터 QA 작업도 추가했습니다. [Android QA 안내](docs/android-qa.md)에서 실행 방식과 검증 범위를 확인하세요. 실기기 동작과 실제 AI 호출은 자동 테스트 결과와 별개입니다.

## 데이터와 남은 작업

기존 무인증 방은 보존되지만 소유자 정보를 알 수 없어 기본적으로 접근이 차단됩니다. 첫 가입자에게 자동 귀속시키지 않습니다. [저장·마이그레이션 안내](docs/persistence.md)와 [구현 결과 및 남은 작업](docs/implementation-status.md)을 확인하세요.

원래 방 안에서 기록을 잘라내는 롤백, 자동 사건 요약과 장기 기억 검색, 사전 동의 기반 AI 대역, 계정 복구·이메일 확인, 운영 수준 분산 제한과 부하 검증, Android 실기기 QA는 후속 단계입니다. 공개 서비스 배포는 이 검증이 끝나기 전 진행하지 않습니다.

## Windows PC + Android USB 실행

[다운로드와 실행 안내](docs/windows-android.md)를 따라 `Start-StoryVerse-Windows.cmd`를 실행하세요. 개인용 서버와 Metro를 시작하고 휴대폰에 개발 APK를 설치합니다. USB 연결을 유지해야 합니다.

## 오픈소스 스토리 AI

Qwen3를 Ollama 또는 OpenAI 호환 서버로 연결할 수 있습니다. 기존 OpenAI 동작을 유지하며 환경변수로 선택합니다. 실제 경량 Qwen 모델로 인증된 생성→저장→분기를 확인했습니다. [설치·모델 선택·검증 결과·남은 배포 작업](docs/open-source-ai.md)을 확인하세요. 기존 기기 체험 APK에는 실제 AI 연결이 포함되지 않습니다.

## 짧은 싱글플레이 우선 개선

새 기기 체험은 네 번 이내의 선택으로 끝나는 미스터리와 네 가지 결말을 제공합니다. 보관함에 장면 요약·저장 시각·원본 연결을 추가했고 이전 저장 기록은 유지합니다. [비공개 테스트 준비와 남은 출시 조건](docs/closed-beta.md)을 참고하세요. 실제 AI/클라우드 서비스의 출시 완료를 의미하지 않습니다.

## 자유 주제로 소설 만들기

온라인 앱의 첫 화면에서 장르 선택 없이 상상을 입력하고 소설 장면을 생성·읽기·이어 쓰기·분기할 수 있습니다. [현재 구현과 한계](docs/free-concept-novels.md)를 참고하세요. 기존 DB는 `alembic upgrade head`로 006 마이그레이션을 적용해야 합니다. 기존 기기 체험 APK와 새 온라인 화면은 구분합니다.

온라인 브라우저 어댑터의 테스트와 배포 빌드는 `cd web && npm ci && npm test && npm run build`로 실행합니다. 자세한 구조는 [온라인 창작실](docs/online-preview.md)에 기록했습니다.

## 장편 기록과 과거 사건 기억

온라인 창작실에 원문 위치를 가진 과거 사건 검색, 실제 생성에 참고한 구절 표시, 장면/보관함 페이지 읽기를 추가했습니다. 생성은 확정 설정과 지시를 몰래 자르지 않고 모델 입력 한도를 확인합니다. [구조·한계·검증](docs/long-story-memory.md)을 참고하세요. 기존 DB는 `007_story_memory`까지 마이그레이션해야 합니다.
