# animation

SRT 자막을 화이트보드 손그림 애니메이션(MP4)으로 만드는 작업용 저장소입니다.

[geeklee/srt-whiteboard-animation](https://github.com/geeklee/srt-whiteboard-animation) 스킬을
Claude Code 스킬로 설치해 두었습니다. 이 저장소에서 Claude Code를 실행하면 자동으로 인식됩니다.

## 구성

```text
.claude/skills/srt-whiteboard-animation/
├── SKILL.md          # 워크플로 정의 (Claude Code가 읽는 파일)
├── scripts/          # 자막 파싱 · 렌더링 · 병합 스크립트
├── assets/
│   ├── preview.html      # 브라우저 편집 프리뷰 (구역/순서/타이밍 조정)
│   └── drawing-hand.png  # 손 이미지 소스
└── agents/           # Codex 메타데이터
```

## 최초 1회 환경 준비

렌더링 스크립트는 격리된 `.venv`(opencv-python / numpy / av / Pillow)에서 실행됩니다.

```bash
cd .claude/skills/srt-whiteboard-animation
python3 scripts/prepare_env.py
```

마지막 줄에 `ENV_PY=<경로>` 가 출력됩니다. 이후 렌더링은 이 인터프리터로 실행하세요.
이미 만들어져 있는지 확인만 하려면 `python3 scripts/prepare_env.py --check`.

시스템 ffmpeg은 필요 없습니다. PyAV가 H.264 인코딩을 처리하고,
장면 병합도 ffmpeg이 없으면 PyAV로 폴백합니다.

## 사용법

자막 파일을 준비한 뒤 Claude Code에게 요청하면 스킬이 트리거됩니다.

```
이 SRT 자막으로 화이트보드 손그림 애니메이션 만들어줘
```

스킬은 7단계로 진행하며 **각 단계마다 멈추고 확인을 기다립니다**:

| 단계 | 내용 |
|---|---|
| 1 | 자막 파싱 → 25~35초 단위 장면 분할 + 구성 전략 제시 |
| 2 | 장면별 선화(線畵) 생성 (`#F5EBD7` 종이 바탕, 16:9) |
| 3 | 자막·이미지 기반 구역 주석(`annotation.json`) 작성 → 프리뷰 자동 오픈 |
| 4 | 구역 번호·방향 검수 이미지 생성 |
| 5 | 프리뷰에서 구역/순서/타이밍 조정 후 저장 |
| 6 | 장면별 MP4 렌더링 |
| 7 | (다장면) 최종 병합 |

## 산출물 규칙

이미지와 주석 파일은 **이름이 같아야** 프리뷰가 자동으로 짝지어 읽습니다.

```text
assets/whiteboard/<프로젝트명>/
├── scene-01-<이름>.png
├── scene-01-<이름>.annotation.json
└── scene-01-<이름>-whiteboard.mp4
```

## 수동 실행 명령

```bash
S=.claude/skills/srt-whiteboard-animation
ENV_PY=$S/.venv/bin/python

# 자막 파싱 + 장면 분할 제안 (표준 라이브러리만 사용)
python3 $S/scripts/parse_srt.py <자막.srt> --target-sec 30 --min-sec 25 --max-sec 35

# 구역 번호 검수 이미지
$ENV_PY $S/scripts/render_annotation_preview.py <이미지> <주석> <출력.png>

# 단일 장면 렌더링
$ENV_PY $S/scripts/render_stream_whiteboard.py <이미지> <주석> <출력.mp4> \
    $S/assets/drawing-hand.png --ink-path grid --color-fill contour-wipe

# 다장면 병합
$ENV_PY $S/scripts/merge_scenes.py --inputs 1.mp4 2.mp4 --output final.mp4
```

편집 프리뷰는 `assets/preview.html`을 Chrome/Edge로 직접 열어 사용합니다
(원본 파일 덮어쓰기에 File System Access API가 필요).

## 제작물: PM 단속 30초 숏폼

`assets/pm-enforcement/` — 개인형 이동장치 도로교통법 위반 단속 콘텐츠.
화이트보드 스킬과는 별개로, 코드로 장면을 그려 렌더링합니다.

```bash
.claude/skills/srt-whiteboard-animation/.venv/bin/python scripts/render_pm_psa.py
# 가로(16:9)가 필요하면
... scripts/render_pm_psa.py --landscape -o assets/pm-enforcement/pm-16x9.mp4
```

| 파일 | 내용 |
|---|---|
| `assets/pm-enforcement/pm-enforcement.mp4` | 완성본 (1080x1920, 30fps, 30초) |
| `assets/pm-enforcement/script.srt` | 자막 (TTS 큐와 동일 타이밍) |
| `assets/pm-enforcement/tts-script.md` | TTS 대본 · 톤 지시 · 숫자 읽기 주의 · 효과음 큐 |
| `scripts/render_pm_psa.py` | 렌더러 |

구성 (30초):

| 구간 | 내용 |
|---|---|
| 0.0–3.0 | 훅 — 주행 → 정지(화이트 플래시) → 경광등 + "단속하겠습니다" |
| 3.0–4.0 | 위반 4건 도장 |
| 4.0–9.0 | 관찰 타임 — 5초 카운트다운, **나레이션 없음** |
| 9.0–25.0 | 적발 4건 × 4초 — 확대 + 빨간 원 + 조서 카드 |
| 25.0–30.0 | 합산 26만원 → 슬로건 |

범칙금은 도로교통법상 PM 위반 기준(음주 10만 / 무면허 10만 / 승차정원 4만 /
인명보호장구 2만)입니다. 배포 전 최신 개정 여부를 확인하세요.

### 근거 조문

적발 카드와 마지막 합산 화면에 각 위반의 근거 조문이 표시됩니다.

| 위반 | 근거 | 범칙금 |
|---|---|---|
| 음주운전 | 도로교통법 제44조 | 10만원 |
| 무면허 운전 | 도로교통법 제43조 | 10만원 |
| 승차정원 위반 | 도로교통법 제50조제10항 | 4만원 |
| 인명보호장구 미착용 | 도로교통법 제50조제4항 | 2만원 |

인명보호장구는 제50조**제3항이 아니라 제4항**입니다. 제3항은 이륜자동차·
원동기장치자전거 대상이면서 괄호로 "개인형 이동장치는 제외한다"를 명시하고
있고, 개인형 이동장치를 포함하는 "자전거등"의 착용 의무가 제4항입니다.
전동킥보드 승차정원 1명은 도로교통법 시행규칙 제33조의3 기준입니다.

### 포돌이 이미지 교체

훅 구간에 등장하는 포돌이는 **파일을 넣으면 자동으로 교체**됩니다.

```text
assets/pm-enforcement/podori.png   ← 배경 투명 PNG 를 이 경로에 두면 끝
```

파일이 있으면 그 이미지를 그대로 쓰고, 없으면 `render_pm_psa.py` 의
`draw_podori()` 가 그린 대역 캐릭터가 사용됩니다. 렌더 시작 로그에 어느
쪽을 썼는지 출력됩니다. 세로 크기만 맞춰 리사이즈하므로 가로세로 비율은
원본이 유지됩니다.

현재 커밋된 영상은 **대역 캐릭터** 버전입니다. 이 작업 환경의 이그레스
정책상 외부 이미지를 내려받을 수 없어 공식 파일을 넣지 못했습니다.

### 그 밖에 교체가 필요한 부분

- **로고**: 마무리의 원형 배지는 플레이스홀더입니다. 서울경찰청 공식 BI 파일로
  교체하세요 (`render_pm_psa.py` 의 `NOTE:` 주석 위치).
- **폰트**: 현재 시스템에 한글 전용 폰트가 없어 `wqy-zenhei`로 렌더링됩니다.
  본 제작에서는 나눔고딕/Noto Sans KR을 설치하고 `PSA_FONT=<경로>`로 지정하면
  자모 균형이 개선됩니다.
- **음성**: 영상에 TTS가 포함되어 있지 않습니다. `tts-script.md`로 합성한 뒤
  편집 단계에서 입히세요.

## 업스트림 대비 수정 사항

설치본에 로컬 수정 2건이 적용되어 있습니다. 둘 다 리눅스/macOS 환경에서
스크립트가 실행되지 않던 문제입니다.

1. **`scripts/render_annotation_preview.py` — 폰트 경로**
   윈도우 전용 경로(`C:/Windows/Fonts/msyh.ttc`)가 하드코딩되어 있어 다른 OS에서는
   `OSError: cannot open resource`로 항상 실패했습니다. 윈도우/macOS/리눅스 후보를
   순서대로 탐색하고, `fc-match`로 보조 탐색한 뒤, 그래도 없으면 PIL 기본 폰트로
   폴백하도록 바꿨습니다. `WHITEBOARD_FONT` 환경변수로 직접 지정할 수도 있습니다.

2. **`scripts/merge_scenes.py` — PyAV 폴백 타임스탬프**
   ffmpeg이 없어 PyAV 폴백을 타면 병합이 `av.error.ArgumentError`로 실패했습니다.
   각 입력 클립의 PTS가 0부터 다시 시작해 두 번째 클립에서 타임스탬프가 역행하기
   때문입니다. 출력 프레임레이트 기준으로 PTS를 다시 매겨 단조 증가하도록 수정했습니다.

## 라이선스

스킬 원본은 MIT License입니다. `.claude/skills/srt-whiteboard-animation/LICENSE` 참조.
