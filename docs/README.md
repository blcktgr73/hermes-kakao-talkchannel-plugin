# hermes-kakao-talkchannel-plugin — 설계 문서

Nous Research **Hermes Agent**용 카카오톡 채널 플랫폼 어댑터 플러그인의 설계 문서
모음입니다. 기존 [`openclaw-kakao-talkchannel-plugin`](../../openclaw-kakao-talkchannel-plugin)
(TypeScript / OpenClaw)을 Hermes(Python / asyncio)로 이식하는 것을 목표로 합니다.

**현재 상태: 설계 단계. 코드 없음.**

## 읽는 순서

| 문서 | 내용 |
|---|---|
| [00-hermes-plugin-sdk.md](00-hermes-plugin-sdk.md) | Hermes 플러그인 SDK 조사 결과 — 플랫폼 어댑터 계약 (검증된 사실) |
| [01-architecture.md](01-architecture.md) | 아키텍처 설계 — 모듈 구조, 인바운드/아웃바운드 경로, 핵심 결정 |
| [02-openclaw-port-map.md](02-openclaw-port-map.md) | OpenClaw 플러그인 → Hermes 이식 대응표 |
| [03-implementation-plan.md](03-implementation-plan.md) | 단계별 구현 계획과 열린 질문 |

## 한 줄 결론

**만들 수 있습니다.** Hermes에는 `ctx.register_platform()`이라는 1급 플랫폼 어댑터
확장점이 있고, 번들 플러그인 `plugins/platforms/line/`이 카카오톡과 구조적으로 거의
동일한 참조 구현(웹훅 기반, 서명 검증, 무료 reply token vs 과금 push)을 제공합니다.
OpenClaw 버전의 순수 도메인 계층(`src/kakao/**`)은 거의 1:1로 이식 가능하고,
호스트 어댑터 계층은 전면 재작성이 필요합니다.
