# Origin 일해 MCP (origin-ilhae-mcp)

Claude Code·Claude Desktop에서 **한국어로 지시해 OriginLab Origin을 다루는** MCP 서버입니다.
Windows와 Origin/OriginPro 2021 이상에서 동작합니다.

> 상태: v0.1.0, 개발 중
> Windows 실기 검증(Phase 0)을 하기 전입니다. [docs/설계서.md](https://github.com/ilhae-ai/origin-ilhae-mcp/blob/main/docs/설계서.md)의 "Phase 0 검증 항목"을 먼저 확인하세요.

## 무엇이 다른가

| | 일반 Origin MCP | origin-ilhae-mcp |
|---|---|---|
| 한글 | 고려 안 함 | 한글 경로·CP949 CSV·한글 열 이름과 단위·맑은 고딕 자동 처리, 한글 왕복 점검(`doctor`) |
| 결과 확인 | "성공" 응답만 | 실행 후 다시 읽어 `verify.status`(verified, mismatch 등)로 보고, 미리보기 이미지 |
| 그림 규격 | Nature 등 해외 기준 | 학위논문·국내 학회지·HWP 보고서·발표 프리셋, `그림1_제목.emf` 형식 내보내기 |
| 분야 | 범용 | 범용 + 물리·전자공학(I-V, 트랜지스터, C-V, FFT, 피크 피팅, Bode, 아레니우스) |
| 연결 | COM 또는 브리지 중 하나 | 하이브리드: 브리지 우선, 안 되면 COM으로 자동 전환, 대화상자 감시와 복구 |
| 보안 | 제각각 | 허용 폴더, 토큰 인증, LabTalk 기본 꺼짐(켜도 승인과 차단 목록), 위험 작업 전 자동 백업 |

## 빠른 시작 (Windows)

```powershell
# 1. 설치 (uv 필요: https://docs.astral.sh/uv/)
uv tool install "origin-ilhae-mcp[windows,encoding]"

# 2. 브리지 설치와 Claude Desktop 등록
origin-ilhae-mcp install --claude-desktop --root "$HOME\Documents" --root "D:\측정데이터"

# 3. Origin 스크립트 창에서 안내된 한 줄 실행 (브리지 시작)

# 4. 점검
origin-ilhae-mcp doctor
```

Claude Code에 등록하는 명령은 `origin-ilhae-mcp config`로 확인합니다.
자세한 절차는 [docs/설치가이드.md](https://github.com/ilhae-ai/origin-ilhae-mcp/blob/main/docs/설치가이드.md)를 보세요.

## 이렇게 말하면 됩니다

- "D:\측정데이터\다이오드_0315.csv 불러와서 I-V 분석하고 로그 그래프로 보여줘"
- "이 전달특성 데이터로 문턱전압이랑 SS 구해줘. Vd는 0.1V야"
- "그래프를 학위논문 규격으로 바꾸고 한글 보고서에 넣을 그림으로 저장해줘. 그림 3번, 제목은 소자 전달특성"
- "Y축 로그로 바꾸고 축 제목을 '전류 (A)'로 해줘"

## 툴 묶음

`ILHAE_TOOLSETS` 환경 변수로 고릅니다. 기본값은 `core,korea,physics`입니다.
툴 전체 목록은 [docs/툴목록.md](https://github.com/ilhae-ai/origin-ilhae-mcp/blob/main/docs/툴목록.md)에 있습니다.

## 설정 (환경 변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ILHAE_ALLOWED_ROOTS` | 문서·바탕화면·다운로드 | 파일을 읽고 쓸 수 있는 폴더. 여러 개면 `;`로 구분 |
| `ILHAE_BACKEND` | `auto` | `auto`, `bridge`, `com`, `fake`(Origin 없이 시험) |
| `ILHAE_TIMEOUT` | `60` | 툴 한 번의 시간 제한(초) |
| `ILHAE_ENABLE_LABTALK` | `0` | 임의 LabTalk 실행 툴 켜기 |
| `ILHAE_AUTO_DISMISS` | `0` | 시간 초과 때 Origin 대화상자 자동 닫기 |
| `ILHAE_AUTO_BACKUP` | `1` | 위험 작업 전에 프로젝트 백업 |
| `ILHAE_KR_PATH_MODE` | `auto` | 한글 경로 처리: `auto`, `direct`, `stage` |
| `ILHAE_BRIDGE_PORT` | `47021` | 브리지 포트 |

## 개발 (macOS·Linux에서도 가능)

```bash
uv sync
uv run pytest                                       # 가짜 Origin으로 전체 테스트
ILHAE_BACKEND=fake uv run origin-ilhae-mcp          # Origin 없이 서버 실행
```

## 참고한 공개 구현 (모두 MIT 라이선스, 아이디어 참고)

[youngminsw/Origin-Pro-MCP](https://github.com/youngminsw/Origin-Pro-MCP),
[garethbeaumo/originlab-mcp](https://github.com/garethbeaumo/originlab-mcp),
[Ge-Shun/origin-mcp](https://github.com/Ge-Shun/origin-mcp),
[Yike-Ye/OriginLab-MCP](https://github.com/Yike-Ye/OriginLab-MCP)

## 라이선스

MIT. Origin을 쓰는 PC마다 Origin 라이선스가 따로 필요합니다.
