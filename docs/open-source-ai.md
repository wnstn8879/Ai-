# IMAGINE의 오픈소스 AI 연결

## 선택과 출처

기존 앱/서버를 다른 채팅 앱으로 교체하지 않고, 서버의 모델 실행 계층을 연결했습니다. 2026-11-17 공식 자료를 확인한 1차 구성은 **Qwen3 + Ollama**입니다.

- [Qwen3 4B Instruct (Ollama 모델)](https://ollama.com/library/qwen3:4b-instruct): 공식 레지스트리에 Apache 2.0으로 표시된 약 2.5GB 양자화 모델. 기본 Ollama 설정값입니다.
- [Qwen3 1.7B](https://ollama.com/library/qwen3:1.7b): 약 1.4GB 경량 모델. 이 작업 환경의 CPU 전체 경로 실증에 사용했습니다.
- [Qwen3-4B-Instruct-2507 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507): Apache 2.0, 원본 실행과 모델 정보. vLLM 등의 OpenAI 호환 서버 설정 예시에 사용합니다.
- [Ollama 코드/라이선스](https://github.com/ollama/ollama), [Chat API](https://docs.ollama.com/api/chat): 로컬 추론 서비스와 비스트리밍 응답 형식 확인.

공개 가중치/라이선스가 있다는 사실과 스토리 품질이 좋다는 사실은 다릅니다. 한국어·캐릭터 일관성·플레이어 행동을 대신 확정하지 않는지는 실제 플레이로 평가해야 합니다. 실행 도구와 모델의 라이선스를 각각 확인하며 모델을 재배포한다면 해당 LICENSE/NOTICE 조건을 따릅니다. 모델 가중치나 실행 바이너리는 이 저장소/APK에 포함하지 않았습니다.

## 실행 설정

기존 OpenAI 동작은 기본값으로 보존했습니다. 서버 환경변수 `AI_PROVIDER`로 공급자를 선택하며 모바일/사용자가 임의의 모델 URL이나 키를 전달할 수 없습니다.

```dotenv
AI_PROVIDER=ollama
AI_BASE_URL=http://127.0.0.1:11434
AI_MODEL=qwen3:4b-instruct
AI_MAX_OUTPUT_TOKENS=500
AI_REQUEST_TIMEOUT_SECONDS=40
```

Ollama는 별도로 설치해 `ollama serve`, `ollama pull qwen3:4b-instruct`로 준비합니다. 모델은 API 요청마다 자동 다운로드하지 않습니다. Docker 사용 시 저장소 루트에서 다음 구성도 사용할 수 있습니다. 이 Compose 예시는 실제 Docker 실행 검증은 아직 하지 않았으며, 이 작업에서는 공식 바이너리로 Ollama를 실행했습니다.

```sh
docker compose -f deploy/ollama.compose.yml up -d ollama
docker compose -f deploy/ollama.compose.yml run --rm model-init
```

위 Compose는 모델 포트를 루프백에만 엽니다. IMAGINE 백엔드도 컨테이너라면 같은 네트워크에서 `AI_BASE_URL=http://ollama:11434`로 연결해야 합니다. Ollama 자체를 인터넷에 공개하지 마세요. 일반 이용자는 휴대폰에서 HTTPS IMAGINE API만 사용하고 서버가 모델을 호출합니다. 사용자의 PC를 요구하는 구조가 아닙니다.

서버 환경변수를 설정한 뒤 기존 README대로 마이그레이션/백엔드를 실행합니다. `.env`를 쓴다면 일반 uvicorn에는 `--env-file .env`가 필요합니다. 기존 Windows 전용 서버 실행 도구도 새 AI 환경변수를 허용하도록 갱신했습니다.

vLLM/다른 OpenAI 호환 실행 서버:

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=http://127.0.0.1:8001/v1
AI_MODEL=Qwen/Qwen3-4B-Instruct-2507
AI_API_KEY=your-server-token-if-required
```

`AI_BASE_URL`은 `/v1`까지 설정하며 `/chat/completions`는 어댑터가 추가합니다. Ollama URL은 `/api/chat`을 제외한 서버 기본 주소입니다. 원격 연결에는 TLS와 서버 인증을 구성하세요. `AI_API_KEY`는 해당 서비스에만 사용하고 기존 OpenAI 키를 타 공급자에 자동 전달하지 않습니다. `AI_PROVIDER=openai`는 기존 `OPENAI_API_KEY`, `OPENAI_MODEL`을 유지하며 선택적으로 `AI_MODEL`이 우선합니다.

## 오류와 데이터 보존

- 기존 세계관·캐릭터·최근 대화·장면 진행 지침을 공통 메시지로 전달합니다. Ollama 문맥 창은 8192로 설정하며 매우 긴 세계관/기록에 대한 모델별 토큰 예산·요약은 후속 과제입니다.
- Ollama는 `stream=false`, `think=false`로 호출하고 이야기 본문만 저장합니다. 사고 출력 필드는 저장하지 않으며 `<think>` 태그가 본문으로 나오면 실패 처리합니다.
- 설정 오류/누락은 503, 연결/시간 초과·이상 응답·빈 응답·출력 길이 한도에 걸린 응답은 502입니다. 내부 응답과 키를 사용자 오류에 노출하지 않습니다.
- 자동 공급자 전환·외부 AI 자동 재시도는 하지 않습니다. 서버의 기존 일일 요청 제한·멤버십·원자적 턴 저장·요청 ID 재사용 검사가 유지됩니다. 실패 시 반쪽 대화가 저장되지 않습니다.
- 모델 호출 제한은 40초 이하로 두어 기존 모바일 45초 요청 제한과 맞춥니다. 모델 서버가 준비되지 않았거나 느리면 결과를 저장하지 않으며 클라이언트의 기존 확인 후 재시도를 사용합니다.

## 실제 검증

Ollama 0.40.16 공식 CPU 바이너리로 모델을 내려받고 레지스트리의 SHA-256 검증을 통과했습니다.

- `qwen3:4b-instruct`: 짧은 직접 API 호출에서 한국어 응답 성공(약 11.1초). 최초 전체 IMAGINE 프롬프트 호출은 CPU에서 40초를 초과해 실패했습니다. 실패를 성공으로 표시하지 않습니다.
- `qwen3:1.7b`: IMAGINE 인증 API에서 실제 생성 성공(24.45초). 사용자+AI 원자적 저장, 동일 요청 ID 캐시, 체크포인트 재개, 원본을 보존하는 분기까지 성공했습니다. 한국어 문장에 어색함이 있어 품질 검증을 완료한 모델로 보지 않습니다.
- OpenAI/vLLM 호환 형식, 키 분리, 잘못된 설정, 빈/불완전/사고 응답, upstream 실패의 무손상 처리는 HTTP 전송 대역으로 자동 검증합니다. 실제 vLLM 서버나 OpenAI 유료 호출은 이번에 실행하지 않았습니다.

재현 명령(backend 디렉터리에서 실행, 별도 임시 SQLite 사용):

```sh
PYTHONPATH=. AI_PROVIDER=ollama AI_MODEL=qwen3:1.7b AI_MAX_OUTPUT_TOKENS=256 \
  ../.venv/bin/python scripts/verify_open_model.py --output /tmp/imagine-model-result.json
```

테스트는 생성 결과·소요 시간만 기록하고 사용자 토큰/키는 출력하지 않습니다. 기본 pytest는 가중치 다운로드나 실제 AI 호출 없이 실행됩니다.

## 남은 배포 작업

이는 백엔드의 실제 모델 연결입니다. 공개 상시 HTTPS 서버, GPU 용량/동시 요청, 개인정보 보존 정책, 한국어 장편 품질과 실제 Android 네트워크 검증은 남아 있습니다. 이전 기기 체험 APK는 여전히 작성된 시나리오로 동작하며 이번 변경으로 실제 AI 앱이 되지 않습니다. 모델을 바꿨다는 이유로 오프라인 체험판을 AI 연결 완료 앱으로 표시하지 않습니다.

최종 자동 검증: 백엔드 pytest **56개 통과**. Compose는 `docker compose config --quiet` 설정 검사만 수행했고 컨테이너 실행은 검증하지 않았습니다. [실제 생성/저장/분기 결과](validation/qwen-real-smoke.json)를 함께 보관합니다.
