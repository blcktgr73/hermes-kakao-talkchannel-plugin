# 페어링 운영 가이드

카카오톡 채널 페어링 코드를 **SSH + `hermes` CLI**로 얻는 방법입니다.

> **전제: 게이트웨이가 먼저 떠 있어야 합니다.** 페어링 코드는 게이트웨이 프로세스의
> 메모리에 존재하며, 게이트웨이가 이를 파일로 발행할 때만 CLI가 읽을 수 있습니다.

## CLI가 게이트웨이와 통신하는 방식

**Hermes에는 실행 중인 게이트웨이로 들어가는 제어 채널이 아예 없습니다.** 저장소가
직접 그렇게 적어두었습니다 — `gateway/drain_control.py`:

> *"there is NO external control channel into a running gateway"*

`register_cli_command`의 핸들러는 argparse 네임스페이스 하나만 받습니다. 런타임도,
게이트웨이 핸들도 없습니다. CLI 프로세스와 게이트웨이 프로세스가 공유하는 것은
파일시스템뿐입니다.

그래서 Hermes 자신이 쓰는 방식을 그대로 따릅니다 — `gateway/pairing.py`는 CLI와
게이트웨이가 **캐시 없이 같은 파일을 읽고 쓰는** 방식이고, 드레인 제어는 **마커 파일 +
폴링**입니다.

| 파일 | 쓰는 쪽 | 읽는 쪽 |
|---|---|---|
| `~/.hermes/kakao-talkchannel/pairing-state.json` | 게이트웨이 | CLI |
| `~/.hermes/kakao-talkchannel/pairing-request.json` | CLI | 게이트웨이 (1초 폴링) |

파일마다 쓰는 쪽이 하나뿐입니다. 원자적 교체는 찢어진 읽기는 막지만 갱신 유실은 막지
못하므로, 프로세스 간 read-modify-write를 하는 코드가 없습니다. 두 파일 모두 `0600`.

이 설계는 **OpenClaw 판에서 먼저 실기 검증을 마친 뒤** 이식했습니다.

## 배달 모델 — 인바운드 1건 = 답변 1건

카카오톡 채널은 **인바운드 메시지 1건당 1회용 콜백 하나**만 줍니다. 그 콜백을 쓰면
그 턴에는 더 보낼 수 없습니다. Hermes는 한 턴에 여러 메시지를 보내도록 만들어졌으니,
어댑터가 그 차이를 흡수합니다.

| 동작 | 이유 |
|---|---|
| 발신을 1.5초 버퍼링 후 **한 번만** 배달 | 콜백이 하나뿐. 여러 번 보내면 첫 건만 도착 |
| 말풍선 최대 3개로 합침 | 카카오 응답 하나에 담을 수 있는 최대치 |
| 초과분은 `…(잘림)` 표시 | 두 번째 콜백이 없으니 조용히 버리면 거짓말 |
| 전환 알림(`⚡ Interrupting` 등) 억제 | 그 하나뿐인 콜백을 답변에 써야 함 |
| 배달 실패 알림 억제 | 망가진 전송으로 "전송 실패"를 알리는 건 순환 |
| 이미 처리한 relay 메시지 id 무시 | 릴레이가 재연결마다 큐를 다시 흘림 |

마지막 항목이 특히 중요합니다. 2026-07-20 실기에서 **인바운드 1건이 94번 재전송되어
94개 턴이 시작**된 적이 있습니다(SSE 정상 종료 후 백오프 없는 재연결 + 릴레이의
재flush가 곱해진 결과). 두 곳 모두 고쳤습니다.

전환 알림을 굳이 보려면 `KAKAO_SEND_STATUS_NOTICES=1`.

## 명령어

```bash
# 현재 페어링 코드 조회 (게이트웨이 재시작 불필요)
hermes kakao pairing status

# 세션을 버리고 새 코드 발급 (게이트웨이 재시작 불필요)
hermes kakao pairing new
```

| 옵션 | 대상 | 설명 |
|---|---|---|
| `--account <id>` | 둘 다 | 계정 지정. 생략 시 실행 중인 첫 계정 |
| `--json` | 둘 다 | 원본 JSON 출력 (스크립트용) |
| `--timeout <초>` | `new` | 릴레이 응답 대기 시간 (기본 30) |

## 표준 절차

```bash
hermes status                  # 게이트웨이가 떠 있는지
hermes kakao pairing status
```

출력:

```
account: default (default)

  페어링 코드: VZ4Q-3E8Q
  카카오톡에서 입력: /pair VZ4Q-3E8Q
  남은 시간: 4분 12초
```

카카오톡 채널에 `/pair VZ4Q-3E8Q`를 입력한 뒤 다시 `status`로 확인하면 `state: paired`가
됩니다.

## 재페어링 — `/unpair`가 먼저입니다

이미 연결된 상태에서 새 코드로 다시 붙이려면 **순서가 있습니다.**

```bash
hermes kakao pairing new          # 1. 새 코드 발급 (게이트웨이 재시작 없음)
```
```
/unpair                            # 2. 카카오톡에서 기존 연결 해제
/pair XXXX-XXXX                    # 3. 새 코드로 연결
```

**2번을 건너뛰면 3번이 거부됩니다.** 릴레이가 이미 페어링된 대화의 `/pair`를 막습니다
(`internal/handler/kakao.go`):

> 이미 OpenClaw에 연결되어 있습니다. 다른 봇에 연결하려면 먼저 `/unpair` 로 연결을 해제하세요.

`pairing new`는 **게이트웨이 쪽 세션만** 버립니다. 릴레이의 `conversation_mappings`는
카카오톡의 `/unpair`로만 풀리고, 플러그인에는 그걸 건드릴 경로가 없습니다.

2026-07-20 실기 확인 절차입니다.

## 상태 파일이 오래됐을 때

CLI는 상태 파일이 의심스러우면 **경고만 하고 내용은 그대로 보여줍니다.** 판정이 틀릴
수 있기 때문입니다 — OpenClaw 판에서 실제로 틀렸고, 그때 명령을 아예 막아버려서
정당한 작업이 차단됐습니다.

경고는 **실제로 확인한 이유만** 말합니다:

- `pid N wrote it and that process is no longer running` — pid를 검사해서 죽어 있었음
- `pid N still appears to be running but has not refreshed it in Xs` — 프로세스는 살아
  있으나 파일이 오래됨

이 구분이 중요합니다. OpenClaw 판은 나이만 보고 판정하면서 메시지로는 "프로세스가
죽었다"고 단언했고, 그 거짓 단서 때문에 일어나지도 않은 게이트웨이 크래시를 추적하는
데 시간을 썼습니다. **코드가 확인하지 않은 것을 진단이 주장하면 진단이 없는 것보다
나쁩니다.**

생존 판정의 주 신호는 pid이고, 나이는 10분 backstop입니다. 게이트웨이가 30초마다
파일을 갱신하므로(하트비트) 안정된 페어링도 stale로 보이지 않습니다.

## 문제 해결

**`No KakaoTalk pairing state found`**
게이트웨이가 상태를 발행하고 있지 않습니다 — 게이트웨이가 내려가 있거나 카카오 채널
계정이 시작되지 않았습니다. `hermes status`로 확인하십시오.

**`Timed out … waiting for a new pairing code`**
게이트웨이가 요청 파일을 집어가지 못했거나 릴레이가 응답하지 않았습니다.

```bash
journalctl --user -u hermes-gateway --since "2 min ago" | grep -i kakao
```

로그에 `Re-issue requested via CLI`가 없으면 게이트웨이가 요청을 못 본 것이고,
`CLI re-issue failed`가 있으면 그 사유가 실제 원인입니다.

**`This account uses a configured relay token, so it never pairs`**
`KAKAO_RELAY_TOKEN`이 설정되어 있으면 `create_session`이 호출되지 않아 페어링 코드
자체가 존재하지 않습니다. 해제하십시오.

## 알려진 제약

- 페어링 상태는 게이트웨이 프로세스 메모리에 있고 파일은 그 사본입니다. 재시작하면
  저장된 세션 토큰으로 페어링은 복원되지만 대기 중이던 미완료 코드는 사라집니다.
- 게이트웨이는 기동 시 남아 있던 요청 파일을 **버립니다.** 죽어 있는 동안 쌓인 요청이
  엉뚱한 시점에 코드를 발급하는 것을 막기 위함입니다(Hermes의 NS-570 좀비 마커와 같은
  유형의 문제).
- `pairing new`는 게이트웨이의 1초 폴링 주기만큼 지연될 수 있습니다.
- 상태 파일은 `0600`이지만 **평문**입니다. 게이트웨이를 돌리는 계정에 접근할 수 있는
  사람은 대기 중인 페어링 코드를 볼 수 있습니다.
