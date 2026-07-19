# 구현 계획

전제: [01-architecture.md](01-architecture.md)의 D1~D5 결정.
각 단계는 그 자체로 검증 가능한 단위입니다.

## 단계 0 — 착수 전 필수 확인 (코드 작성 없음)

이 단계를 건너뛰면 설계가 틀린 채로 1600줄을 쓰게 됩니다.

| 항목 | 확인 대상 | 왜 |
|---|---|---|
| P0-1 | `plugins/platforms/line/adapter.py` 통독 (1654줄) | reply-token 상태 기계가 카카오 콜백/푸시 경제학과 동형. 설계의 절반이 여기 있음 |
| P0-2 | `gateway/platforms/base.py`에서 `handle_message`, `build_source`, `send` 실제 본문 | 요약이 아닌 원문으로 계약 확정 |
| P0-3 | 카카오 오픈빌더 스킬 서버 현행 스펙 | OpenClaw 판이 만들어진 이후 변경 여부. 콜백 타임아웃 실제 값 |
| P0-4 | 카카오 채널 메시지 API의 선제 발송(push) 가능 여부·비용 | ack-then-push가 성립하는지의 근본 전제 |
| P0-5 | 릴레이(`k.tess.dev`) 소유·운영 주체, 자체 호스팅 경로 | 제3자가 평문 메시지를 보는 신뢰 경계 문제 |
| P0-6 | Hermes 플러그인 설치 실경로 검증 (`hermes plugins install user/repo`) | 배포 형태 확정 |

**P0-4가 부정이면 설계 전면 재검토가 필요합니다.** 카카오가 선제 발송을 막고
콜백 응답만 허용한다면, 3~30분 걸리는 에이전트 세션을 카카오톡에 태울 방법이
근본적으로 제약됩니다. 릴레이가 이 문제를 어떻게 우회하고 있는지가
OpenClaw 판이 실제로 동작하는 이유일 가능성이 높습니다 — P0-5와 함께 확인하십시오.

## 단계 1 — 골격 + 등록 (동작하는 no-op 플러그인)

산출물: `plugin.yaml`, `__init__.py`, `registration.py`, 최소 `adapter.py`.

- `hermes plugins`에 `kakaotalk`이 뜨고 enable/disable 된다.
- `hermes status`가 미설정 상태를 정확히 보고한다 (`env_enablement_fn` 경로).
- `connect()`는 True를 반환하고, `send()`는 `SendResult(success=False, error="not implemented")`.

검증: `hermes plugins enable kakao-talkchannel && hermes status`.

## 단계 2 — 카카오 순수 도메인 이식

산출물: `kakao/` 패키지 전체 + 단위 테스트.

- `payload.py`, `response.py`, `limits.py`, `markdown.py`, `chunking.py`
- OpenClaw `tests/unit/kakao/**`의 케이스를 pytest로 1:1 이식
- **불변식 테스트**: `kakao/**`가 `hermes*`를 import하지 않음을 AST로 검사

Hermes 없이도 독립적으로 테스트 가능한 유일한 단계입니다. 병렬 작업 가능.

## 단계 3 — 트랜스포트 (릴레이)

산출물: `transport/__init__.py`(Protocol), `transport/relay.py`, `transport/models.py`.

- SSE 구독 + `Last-Event-ID` 재개 + 지수 백오프 재접속
- 토큰 해결 순서와 401/410 재발급
- `POST reply`
- 테스트는 릴레이를 목킹 (실서버 의존 금지)

## 단계 4 — 어댑터 결선

산출물: 완성된 `adapter.py`.

- `connect(is_reconnect=)`: 트랜스포트 기동. `is_reconnect=True`면 큐 보존
- 인바운드: `InboundMessage` → `build_source` → `MessageEvent` → `handle_message`
- `send()`: 마크다운 제거 → 카드/텍스트 결정 → limits 강제 → 트랜스포트
- `disconnect()`: 깨끗한 종료, `_mark_disconnected()`
- 오류: `_set_fatal_error(code, message, retryable=)`

첫 실제 왕복(사용자 메시지 → 에이전트 → 응답)이 여기서 성립합니다.

## 단계 5 — 지연 UX

- 즉시 ACK + 플레이스홀더
- `_keep_typing` 오버라이드로 N초 시점 "계속 보기" 퀵리플라이
- `PENDING → READY → DELIVERED/ERROR` 상태 기계
- `_SYSTEM_BYPASS_PREFIXES` 통과 보장 테스트

LINE 어댑터가 청사진입니다 (P0-1).

## 단계 6 — 명령어 + 대화형 설치

- `ctx.register_command()`로 `/card` 등 (어댑터에서 하이재킹하지 않음)
- `setup_fn`: 릴레이 URL·토큰 대화형 입력, 페어링 코드 안내

## 단계 7 — 배포

- pip 패키지 + `hermes_agent.plugins` 엔트리포인트
- `~/.hermes/plugins/` 직접 설치 경로 문서화
- README(한/영), 스크린샷

## 열린 질문

| ID | 질문 | 막는 단계 |
|---|---|---|
| Q1 | 릴레이를 그대로 쓸까, 포크할까, 자체 호스팅할까? | 3 |
| Q2 | `max_message_length` 계수 단위가 카카오 기준과 맞나? `message_len_fn` 오버라이드 필요? | 4 |
| Q3 | 카카오 채널이 1:1 외 그룹/오픈채팅을 지원하나? (`chat_type` 확장) | 4 |
| Q4 | 미디어(이미지) 인바운드를 v1에 넣을까? `media_urls`는 로컬 경로여야 함 | 4 |
| Q5 | 릴레이의 `POST {relay}openclaw/reply` 경로명을 호스트 중립으로 바꿀 수 있나? | 3 |
| Q6 | 다중 카카오 채널 요구가 실제로 있나? 있다면 프로필 분리로 충분한가? | 설계 재검토 |
| Q7 | 라이선스·저장소 공개 범위 (Hermes는 MIT) | 7 |

## 명시적 비목표 (v1)

- 다중 계정 (`accounts.<id>`) — 프로필로 대체
- 자체 페어링/DM 정책 구현 — Hermes 것 사용
- 직접 웹훅 서버 — v0.2
- 메모리 provider / context engine 등 다른 플러그인 종류
- 데스크톱 표면

## 품질 게이트 (제안)

| 게이트 | 내용 |
|---|---|
| `lint` | ruff |
| `typecheck` | pyright 또는 mypy — **테스트 포함** (원본의 부채 반복 금지) |
| `test` | pytest, `kakao/**` 커버리지 90%+, 전체 80%+ |
| `invariants` | AST 검사: `kakao/**`의 호스트 import 0, `register()`의 최상단 무거운 import 0 |
