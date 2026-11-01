---
name: origin-ilhae
description: 사용자가 한국어로 Origin(OriginLab) 그래프·측정 데이터 분석·논문/보고서 그림을 요청할 때 origin-ilhae MCP 툴을 올바른 순서로 쓰게 한다. "Origin으로 그려줘", "측정 데이터 분석", "I-V", "문턱전압", "C-V", "FFT", "피크 피팅", "논문용 그림", "학위논문 규격", "한글 보고서에 넣을 그림", "축 로그로" 같은 요청에 쓴다.
---

# Origin 일해 MCP 사용법

## 기본 원칙

1. **처음에는 상태부터 확인한다**: `origin_status`. 연결이 실패하면 사용자에게 Origin을 켜고 브리지를 시작하라고 안내한다(설치가이드 4단계).
2. **결과를 추측해서 보고하지 않는다**: 상태를 바꾸는 툴의 `verify.status`를 확인한다.
   - `verified`가 아니면 그 사실을 그대로 알리고 `graph_preview`로 실제 그림을 확인한다.
   - 물리 분석 툴은 `plot.axis_verify`를 확인한다.
3. **경로**: 허용 폴더 안의 절대 경로만 쓸 수 있다. 사용자가 파일명만 말하면 전체 경로를 물어본다.
4. **축 제목**: `물리량 (단위)` 형식의 한글로 쓴다. 예: `전압 (V)`, `|드레인 전류| (A)`
5. **파괴적인 작업**: `project_new`, `labtalk_run`은 사용자 확인을 받은 뒤 `confirm=true`로 호출한다.

## 한국어 표현과 툴 대응

| 사용자 표현 | 툴 |
|---|---|
| CSV 불러와줘, 측정 파일 열어줘 | `import_data_file` (인코딩 자동. 깨지면 `encoding="cp949"`) |
| 로그로, 로그 스케일 | `graph_set_axis(scale="log10")` |
| 이중 Y축, 오른쪽 축 | `graph_create(template="doubley")`, 두 번째 플롯은 `layer=1` |
| 오차막대 | `graph_create(plots=[{..., "yerr": 열}])` |
| 한글이 깨져, 네모로 나와 | `kr_apply_font(font="맑은 고딕")` |
| 논문용, 학위논문 규격, 학회지 규격 | `kr_list_presets` → `kr_apply_preset` |
| 한글 문서(HWP)에 넣을 그림 | `kr_export_for_hwp` |
| 다이오드, 이상계수, 직렬저항 | `iv_diode_analyze` |
| 문턱전압, Vth, SS, 온오프비, 이동도 | `transistor_analyze` (선형 영역이면 `mode="linear"`와 `vd`, 포화 영역이면 `mode="saturation"`) |
| 모트-쇼트키, 도핑농도, 평탄대전압 | `cv_mott_schottky` (면적 cm²와 비유전율이 필요하면 질문) |
| FFT, 주파수 성분 | `spectrum_fft` |
| 피크 피팅, 가우시안, 로렌츠 | `spectrum_peaks_fit` |
| 노이즈 제거, 스무딩, 필터 | `signal_filter` |
| 보드 선도, 차단 주파수 | `bode_plot` |
| 활성화 에너지, 아레니우스 | `arrhenius_fit` |

## 표준 작업 흐름: 측정 파일에서 논문·보고서 그림까지

1. `import_data_file`로 불러와 열 이름·단위·역할(role)·인코딩을 사용자에게 한 줄로 요약한다.
2. 분석 툴을 고른다. 데이터가 어떤 측정인지 애매하면 **추측하지 말고 질문**한다.
   - 예: 열이 V와 I뿐이면 다이오드 측정인지 트랜지스터 측정인지 묻는다.
3. 분석 결과는 숫자와 단위를 함께 보고한다. 예: `이상계수 n = 1.62, 직렬저항 Rs = 4.9 Ω`
   - R²가 낮거나 경고(`warning`)가 있으면 함께 알린다.
4. `kr_apply_preset`으로 규격을 적용한다. `warning`(초깃값 프리셋)이 있으면 투고 규정을 확인하라고 안내한다.
5. `graph_preview`로 확인한 뒤 `kr_export_for_hwp` 또는 `graph_export`로 저장한다. 저장 경로와 캡션 제안을 보고한다.

## 오류 대응

| 오류 코드 | 대응 |
|---|---|
| `TIMEOUT` | Origin 화면의 대화상자 제목이 메시지에 나온다. 사용자에게 닫아 달라고 한 뒤 다시 시도한다 |
| `PATH_NOT_ALLOWED` | 허용 폴더를 추가하는 방법(`ILHAE_ALLOWED_ROOTS`)을 안내한다 |
| `COLUMN_AMBIGUOUS` | 오류 메시지의 열 목록을 보여주고 어느 열인지 묻는다 |
| `mismatch` | 요청한 값과 실제 반영된 값을 보여주고, 다른 방법(예: `graph_preview`로 확인 후 재시도)을 제안한다 |
