# Windows PC에서 Android 앱 열기

현재 앱은 **Windows PC에 USB로 연결해서 쓰는 개발용 APK**입니다. 휴대폰에서 앱이 실행되고 PC에서 개인용 백엔드와 Metro가 실행됩니다. 공개 서버 없이 사용할 수 있습니다. PC 브라우저용 웹 앱이나 독립 배포판은 아닙니다.

## 준비와 실행

1. PC에 [Node.js 22 이상](https://nodejs.org/)과 [Python 3.12 또는 3.13](https://www.python.org/downloads/windows/)을 설치하세요. Python 설치 시 Launcher 또는 PATH 옵션을 선택하세요.
2. [프로젝트 ZIP](https://github.com/wnstn8879/Ai-/archive/refs/heads/feat/storyverse-auth-library-social.zip)을 다운로드하고 압축을 푸세요. [APK 다운로드](https://github.com/wnstn8879/Ai-/actions/runs/43239165687/artifacts/13952529971)도 압축을 풀어 `app-debug.apk`를 프로젝트의 `Start-StoryVerse-Windows.cmd` 옆에 놓으세요. GitHub 로그인이 필요할 수 있습니다. 아티팩트 만료 시 PR의 최신 Android 빌드에서 받으세요.
3. 휴대폰 설정의 빌드 번호를 7번 눌러 개발자 옵션을 활성화하고 **USB 디버깅**을 켜세요. 데이터 전송 USB 케이블로 연결하고 잠금을 푼 뒤 ‘이 컴퓨터에서 USB 디버깅 허용’을 누르세요. 제조사별 메뉴 이름은 다를 수 있습니다.
4. **`Start-StoryVerse-Windows.cmd`를 더블 클릭**하세요. 의존성 설치 → 기기 확인 → 백엔드/Metro 시작 → APK 설치 → 앱 실행을 처리합니다. 초기 설치에는 인터넷과 수 분이 필요합니다. APK를 찾지 못하면 선택 창이 열립니다. Android Studio는 필요하지 않으며 필요한 Google 공식 Platform Tools만 프로젝트 안에 다운로드합니다.

앱에서 회원가입한 후 이야기를 만드세요. **USB와 백엔드·Metro 창 두 개를 유지**해야 합니다. 종료할 때 두 창에서 `Ctrl+C`를 누르세요. 재실행 시 포트 충돌이 나면 이전 창을 닫으세요. 다른 프로그램은 자동 종료하지 않습니다.

계정·이야기는 `.runtime/windows/storyverse-local.db`에 보존됩니다. 폴더를 삭제하면 기록도 사라집니다. 외부 `DATABASE_URL` 대신 전용 SQLite DB를 마이그레이션합니다. DB·가상환경·APK는 Git에서 제외합니다. PowerShell 정책 우회는 실행 프로세스에만 적용하며 PC의 영구 설정을 바꾸지 않습니다.

AI 대화는 `backend/.env`에 `OPENAI_API_KEY`와 선택적으로 `OPENAI_MODEL`을 설정한 뒤 백엔드를 재시작해야 합니다. 키를 채팅이나 GitHub에 올리지 마세요. 키가 없어도 회원가입·사람 간 채팅·저장·분기는 사용할 수 있습니다.

## 문제 해결과 검증 범위

- 기기를 찾지 못하면 USB 허용 창·데이터 케이블·제조사 USB 드라이버를 확인하고 여러 기기 중 한 대만 연결하세요.
- JS 서버 연결 오류가 나면 Metro 창과 USB 연결을 확인하세요.
- APK 서명 충돌 시 기존 앱과 서명이 다른 경우입니다. 앱 삭제 시 기기 초안과 세션이 사라지므로 기록을 확인하세요. 도구는 자동 삭제하지 않습니다.
- 반복 실행은 `Start-StoryVerse-Windows.cmd -NoInstall`, 연결 점검은 `Start-StoryVerse-Windows.cmd -Mode Check`를 명령 프롬프트에서 사용할 수 있습니다.

API와 Metro는 `127.0.0.1`에서만 열고 ADB reverse로 휴대폰에 연결합니다. 공유기 포트 개방이나 방화벽 전체 해제는 필요하지 않습니다. 실제 Windows+휴대폰 USB 조합은 미검증입니다. Windows 자동 검증은 PowerShell 문법·기기 목록·필수 프로그램·포트 확인·전용 DB 마이그레이션·서버 응답을 검사합니다.
