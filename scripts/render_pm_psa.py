#!/usr/bin/env python3
"""
개인형 이동장치(PM) 단속 30초 숏폼 렌더러 · 서울경찰청 컨셉

스토리보드를 그대로 구현한다. 장면은 외부 이미지 없이 코드로 그린다.

  0.0- 3.0s  훅      주행 장면 → 정지 → 경광등 톤 + "단속하겠습니다"
  3.0- 4.0s  문제제시 위반 4건 도장
  4.0- 9.0s  관찰    장면 유지 + 5초 카운트다운 (나레이션 없음)
  9.0-25.0s  적발    4건 × 4초, 확대 + 빨간 원
 25.0-30.0s  마무리  숫자 합산 → 26만원 + 슬로건

사용:
  <ENV_PY> scripts/render_pm_psa.py [-o 출력.mp4] [--fps 30] [--landscape]
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ── 캔버스 ────────────────────────────────────────────────────
W, H = 1080, 1920          # 9:16 세로 (숏폼 기본)
GROUND_Y = 1400            # 지면 라인
HORIZON_Y = 980            # 하늘/도로 경계
RIDER_S = 1.34             # 인물 스케일 (세로 프레임을 채우도록 크게)

# 상단 배지/하단 자막이 차지하는 영역을 피해 인물을 배치한다.
#   상단 안전선 ~420 / 하단 안전선 ~1440

# ── 팔레트 ────────────────────────────────────────────────────
SKY_TOP     = (14, 21, 41)
SKY_BOT     = (32, 48, 78)
BUILDING    = (9, 15, 30)
ROAD        = (38, 43, 54)
ROAD_LINE   = (222, 226, 233)
INK         = (17, 20, 28)      # 외곽선
SKIN        = (240, 194, 156)
HAIR        = (26, 26, 30)
JACKET_A    = (232, 93, 74)     # 운전자
JACKET_B    = (74, 144, 217)    # 동승자
PANTS       = (68, 84, 116)     # 어두운 도로 위에서 실루엣이 죽지 않게 밝게
BOARD       = (200, 205, 214)
BOTTLE      = (86, 166, 106)
POLICE_RED  = (230, 57, 70)
POLICE_BLUE = (43, 108, 212)
WARN        = (255, 210, 63)
WHITE       = (245, 247, 250)

# ── 폰트 ──────────────────────────────────────────────────────
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
)


def _fc_match_ko() -> str | None:
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", ":lang=ko"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    p = r.stdout.strip()
    return p if r.returncode == 0 and p and Path(p).exists() else None


def _font_file() -> str:
    override = os.environ.get("PSA_FONT")
    cands = ([override] if override else []) + list(_FONT_CANDIDATES)
    m = _fc_match_ko()
    if m:
        cands.append(m)
    for c in cands:
        if c and Path(c).exists():
            try:
                ImageFont.truetype(c, 16)
                return c
            except OSError:
                continue
    raise SystemExit("[err] 한글 렌더링 가능한 폰트를 찾지 못했습니다. PSA_FONT=<경로> 로 지정하세요.")


FONT_PATH = _font_file()
_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def F(size: int) -> ImageFont.FreeTypeFont:
    if size not in _font_cache:
        _font_cache[size] = ImageFont.truetype(FONT_PATH, size)
    return _font_cache[size]


# ── 보간 ──────────────────────────────────────────────────────
def clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def lerp(a, b, t):
    return a + (b - a) * t


def ease_out(t):
    return 1 - (1 - clamp(t)) ** 3


def ease_in_out(t):
    t = clamp(t)
    return 3 * t * t - 2 * t * t * t


def text(d, xy, s, size, fill=WHITE, anchor="mm", bold=0, stroke_fill=INK):
    d.text(xy, s, font=F(size), fill=fill, anchor=anchor,
           stroke_width=bold, stroke_fill=stroke_fill)


# ══════════════════════════════════════════════════════════════
# 장면 그리기
# ══════════════════════════════════════════════════════════════
def draw_background() -> Image.Image:
    """야간 도심 배경 (건물 실루엣 + 도로). 한 번만 그려 캐시한다."""
    img = Image.new("RGB", (W, H), SKY_TOP)
    d = ImageDraw.Draw(img)

    # 하늘 그라데이션
    for y in range(0, HORIZON_Y):
        t = y / HORIZON_Y
        d.line([(0, y), (W, y)], fill=tuple(int(lerp(a, b, t)) for a, b in zip(SKY_TOP, SKY_BOT)))

    # 건물 실루엣
    rng = np.random.default_rng(7)
    x = -40
    while x < W + 40:
        bw = int(rng.integers(90, 190))
        bh = int(rng.integers(180, 460))
        top = HORIZON_Y - bh
        d.rectangle([x, top, x + bw, HORIZON_Y], fill=BUILDING)
        # 창문
        for wy in range(top + 26, HORIZON_Y - 30, 46):
            for wx in range(x + 18, x + bw - 24, 40):
                if rng.random() < 0.45:
                    glow = (255, 214, 130) if rng.random() < 0.7 else (150, 190, 255)
                    d.rectangle([wx, wy, wx + 16, wy + 24], fill=glow)
        x += bw + int(rng.integers(8, 26))

    # 도로
    d.rectangle([0, HORIZON_Y, W, H], fill=ROAD)
    # 인도 경계
    d.rectangle([0, HORIZON_Y, W, HORIZON_Y + 14], fill=(58, 64, 78))
    # 중앙 점선 (원근감: 아래로 갈수록 길고 두껍게)
    y = HORIZON_Y + 90
    seg = 26
    while y < H:
        t = (y - HORIZON_Y) / (H - HORIZON_Y)
        length = seg * (0.6 + 2.4 * t)
        thick = int(lerp(4, 16, t))
        d.rectangle([W // 2 - thick // 2, y, W // 2 + thick // 2, y + length], fill=(92, 98, 112))
        y += length + lerp(40, 130, t)

    return img


def _limb(d, pts, color, s, taper=1.0):
    """어깨→팔꿈치→손 처럼 꺾인 팔다리. 관절을 둥글게 이어 자연스럽게."""
    wide = int(26 * s * taper)
    for a, b in zip(pts, pts[1:]):
        d.line([a, b], fill=INK, width=wide + int(9 * s))
    for a, b in zip(pts, pts[1:]):
        d.line([a, b], fill=color, width=wide)
    for p in pts[1:-1]:
        r = wide // 2
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color)


def draw_rider(d: ImageDraw.ImageDraw, cx: int, deck_y: int, jacket, *,
               scale: float = 1.0, lean: int = 0):
    """킥보드 위에 선 사람. cx=몸 중심, deck_y=발판 윗면(발이 닿는 높이)."""
    s = scale
    hip_y = deck_y - int(150 * s)
    sh_y = hip_y - int(140 * s)
    head_r = int(46 * s)
    head_y = sh_y - int(56 * s)
    lw = max(2, int(5 * s))

    # 신발: 발판 윗면에 딛고 선다
    for dx in (-int(30 * s), int(26 * s)):
        d.rounded_rectangle([cx + dx - int(28 * s), deck_y - int(16 * s),
                             cx + dx + int(28 * s), deck_y + int(4 * s)],
                            radius=int(7 * s), fill=INK)
    # 다리 (무릎에서 살짝 굽힘)
    for dx in (-int(30 * s), int(26 * s)):
        knee = (cx + int(dx * 0.75) + lean // 3, deck_y - int(78 * s))
        _limb(d, [(cx + dx, deck_y - int(10 * s)), knee, (cx + int(dx * 0.3) + lean // 2, hip_y)],
              PANTS, s, taper=1.15)

    # 몸통 (진행 방향으로 살짝 기울임)
    d.polygon([(cx - int(48 * s) + lean, sh_y),
               (cx + int(48 * s) + lean, sh_y),
               (cx + int(44 * s), hip_y + int(18 * s)),
               (cx - int(44 * s), hip_y + int(18 * s))],
              fill=jacket, outline=INK)
    d.rounded_rectangle([cx - int(48 * s) + lean, sh_y - int(12 * s),
                         cx + int(48 * s) + lean, sh_y + int(30 * s)],
                        radius=int(20 * s), fill=jacket, outline=INK, width=lw)

    # 목
    d.line([(cx + lean, sh_y), (cx + lean, head_y + head_r - int(6 * s))],
           fill=SKIN, width=int(26 * s))

    # 머리 (헬멧 없음 — 맨머리)
    hx = cx + lean
    d.ellipse([hx - head_r, head_y - head_r, hx + head_r, head_y + head_r],
              fill=SKIN, outline=INK, width=lw)
    # 머리카락
    d.chord([hx - head_r, head_y - head_r, hx + head_r, head_y + head_r],
            178, 362, fill=HAIR)
    d.arc([hx - head_r, head_y - head_r, hx + head_r, head_y + head_r],
          178, 362, fill=INK, width=lw)
    # 눈
    ex = int(16 * s)
    for dx in (-ex, ex):
        d.ellipse([hx + dx - int(5 * s), head_y + int(2 * s),
                   hx + dx + int(5 * s), head_y + int(13 * s)], fill=INK)

    return {"head": (hx, head_y, head_r),
            "shoulder": (cx + lean, sh_y + int(8 * s)),
            "hip": (cx, hip_y)}


ANCHORS: dict[str, tuple] = {}     # 확대 대상 좌표 (draw_scene 이 채운다)


def draw_scene(offset_x: int = 0, speed_lines: float = 0.0) -> Image.Image:
    """전체 장면. offset_x 로 좌우 이동(주행 연출), speed_lines 로 속도선 농도."""
    img = _BG.copy()
    d = ImageDraw.Draw(img)

    s = RIDER_S
    cx = W // 2 + offset_x
    deck_y = GROUND_Y - 46
    wheel_r = int(44 * s)

    # 피사체 뒤 은은한 글로우 (시선 유도)
    glow = Image.new("RGB", img.size, (60, 78, 120))
    gm = Image.new("L", img.size, 0)
    ImageDraw.Draw(gm).ellipse([cx - 430, deck_y - 640, cx + 430, deck_y + 180], fill=90)
    img.paste(glow, (0, 0), gm.filter(ImageFilter.GaussianBlur(120)))
    d = ImageDraw.Draw(img)

    # 속도선
    if speed_lines > 0:
        for i, (ly, ll) in enumerate([(deck_y - 380, 300), (deck_y - 250, 380),
                                      (deck_y - 120, 330), (deck_y - 20, 250)]):
            x2 = cx - 250 - i * 20
            d.line([(x2, ly), (x2 - ll * speed_lines, ly)],
                   fill=(150, 172, 205), width=int(7 * s))

    # ── 킥보드 (진행 방향: 오른쪽) ──
    rear_x, front_x = cx - int(165 * s), cx + int(165 * s)
    for wx in (rear_x, front_x):
        d.ellipse([wx - wheel_r, GROUND_Y - wheel_r, wx + wheel_r, GROUND_Y + wheel_r],
                  fill=(26, 28, 34), outline=INK, width=int(5 * s))
        d.ellipse([wx - wheel_r // 3, GROUND_Y - wheel_r // 3,
                   wx + wheel_r // 3, GROUND_Y + wheel_r // 3], fill=(122, 128, 140))
    # 발판
    d.rounded_rectangle([rear_x - int(24 * s), deck_y, front_x + int(20 * s), deck_y + int(26 * s)],
                        radius=int(10 * s), fill=BOARD, outline=INK, width=int(5 * s))
    # 스템 + 핸들 (가슴 높이)
    bar_y = deck_y - int(268 * s)
    d.line([(front_x, deck_y), (front_x + int(16 * s), bar_y)], fill=INK, width=int(26 * s))
    d.line([(front_x, deck_y), (front_x + int(16 * s), bar_y)], fill=BOARD, width=int(15 * s))
    d.rounded_rectangle([front_x - int(52 * s), bar_y - int(13 * s),
                         front_x + int(86 * s), bar_y + int(13 * s)],
                        radius=int(12 * s), fill=(74, 80, 94), outline=INK, width=int(4 * s))
    d.ellipse([front_x + int(44 * s), bar_y + int(16 * s),
               front_x + int(80 * s), bar_y + int(52 * s)], fill=WARN, outline=INK, width=int(4 * s))

    # ── 동승자(뒤) → 운전자(앞) 순서로 그려 앞사람이 위에 오게 ──
    psg_x, drv_x = cx - int(112 * s), cx + int(66 * s)
    psg = draw_rider(d, psg_x, deck_y, JACKET_B, scale=s * 0.95, lean=int(6 * s))
    drv = draw_rider(d, drv_x, deck_y, JACKET_A, scale=s, lean=int(10 * s))

    # 동승자 팔 → 운전자 어깨 붙잡기 (팔꿈치를 아래로 크게 꺾어 판자처럼 보이지 않게)
    _limb(d, [psg["shoulder"],
              (psg_x + int(62 * s), psg["shoulder"][1] + int(96 * s)),
              (drv_x - int(52 * s), drv["shoulder"][1] + int(16 * s))], JACKET_B, s * 0.95)

    # 운전자 오른팔 → 핸들 (앞으로 뻗음)
    grip = (front_x + int(30 * s), bar_y)
    _limb(d, [drv["shoulder"],
              (drv_x + int(78 * s), drv["shoulder"][1] + int(74 * s)),
              grip], JACKET_A, s)
    d.ellipse([grip[0] - int(21 * s), grip[1] - int(21 * s),
               grip[0] + int(21 * s), grip[1] + int(21 * s)],
              fill=SKIN, outline=INK, width=int(4 * s))

    # 운전자 왼팔 → 술병을 머리 위로 (음주운전). 동승자와 겹치지 않도록 오른쪽 위로.
    hand = (drv_x + int(96 * s), drv["head"][1] - int(112 * s))
    _limb(d, [drv["shoulder"], (drv_x + int(104 * s), drv["shoulder"][1] - int(56 * s)), hand],
          JACKET_A, s)
    d.ellipse([hand[0] - int(20 * s), hand[1] - int(20 * s),
               hand[0] + int(20 * s), hand[1] + int(20 * s)],
              fill=SKIN, outline=INK, width=int(4 * s))
    # 병 (손 위)
    bx, by = hand[0], hand[1] - int(58 * s)
    d.rounded_rectangle([bx - int(23 * s), by - int(52 * s), bx + int(23 * s), by + int(50 * s)],
                        radius=int(11 * s), fill=BOTTLE, outline=INK, width=int(5 * s))
    d.rounded_rectangle([bx - int(9 * s), by - int(92 * s), bx + int(9 * s), by - int(44 * s)],
                        radius=int(5 * s), fill=BOTTLE, outline=INK, width=int(5 * s))
    d.rectangle([bx - int(23 * s), by - int(18 * s), bx + int(23 * s), by + int(16 * s)],
                fill=(238, 238, 232), outline=INK, width=int(4 * s))

    # ── 확대 대상 좌표 기록 (그린 위치에서 직접 유도) ──
    # r 은 빨간 원의 반지름 = 대상이 실제로 차지하는 크기. 과하게 잡으면
    # 크롭 박스가 프레임을 넘어 확대가 되지 않으므로 물체 치수에 맞춘다.
    ANCHORS["bottle"] = (bx, by - int(12 * s), int(86 * s))
    ANCHORS["license"] = (drv_x + int(6 * s), drv["hip"][1] - int(26 * s), int(104 * s))
    ANCHORS["deck"] = ((psg_x + drv_x) // 2, deck_y - int(16 * s),
                       int(abs(drv_x - psg_x) / 2 + 78 * s))
    hx1, hy1, hr1 = psg["head"]
    hx2, hy2, hr2 = drv["head"]
    ANCHORS["heads"] = ((hx1 + hx2) // 2, (hy1 + hy2) // 2,
                        int(abs(hx2 - hx1) / 2 + hr1 + 26 * s))
    return img


# ══════════════════════════════════════════════════════════════
# 포돌이 (경찰 캐릭터)
# ══════════════════════════════════════════════════════════════
PODORI_FILE = Path(__file__).resolve().parent.parent / "assets" / "pm-enforcement" / "podori.png"


def load_podori(size: int) -> Image.Image:
    """포돌이 레이어를 얻는다.

    assets/pm-enforcement/podori.png (배경 투명 PNG) 가 있으면 **그 파일을
    그대로** 쓰고, 없을 때만 아래 draw_podori() 의 대역을 그린다.
    경찰청 공식 포돌이 파일을 그 경로에 넣고 다시 렌더하면 코드 수정 없이
    공식 캐릭터로 교체된다.
    """
    if PODORI_FILE.exists():
        im = Image.open(PODORI_FILE).convert("RGBA")
        w = max(1, int(round(im.width * size / im.height)))
        print(f"  포돌이: {PODORI_FILE.name} 사용 ({im.width}x{im.height} → {w}x{size})")
        return im.resize((w, size), Image.LANCZOS)
    print(f"  포돌이: 대역 캐릭터 사용 (공식 파일을 {PODORI_FILE} 에 넣으면 교체됨)")
    return draw_podori(size)


def draw_podori(size: int = 640) -> Image.Image:
    """경찰 캐릭터를 RGBA 레이어로 그려 반환 (공식 파일이 없을 때의 대역).

    좌표는 전체 높이 대비 비율(u)이며, 공식 포돌이 일러스트의 실측 비율을
    따랐다: 모자+머리가 위쪽 약 63%, 몸통·다리가 나머지인 2등신 체형.
    """
    T = size

    def u(f):
        return int(round(f * T))

    OL = (17, 17, 19)
    SKIN_C = (247, 221, 190)
    NAVY = (26, 33, 54)
    GOLD = (238, 186, 47)
    MOUTH_C = (231, 65, 40)
    BLUSH_C = (243, 150, 96)      # 포돌이는 주황 계열 볼터치
    NOSE_C = (183, 133, 74)
    SHIRT_C = (255, 255, 255)

    lw = u(0.74)
    lay = Image.new("RGBA", (lw, T), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    cx = lw // 2
    LW = max(3, u(0.012))

    hcy, R = u(0.451), u(0.196)

    # ── 신발 · 바지 ──
    for sgn in (-1, 1):
        d.ellipse([cx + sgn * u(0.078) - u(0.086), u(0.912),
                   cx + sgn * u(0.078) + u(0.086), u(0.996)], fill=OL)
    for sgn in (-1, 1):
        x_in, x_out = cx + sgn * u(0.014), cx + sgn * u(0.118)
        d.rounded_rectangle([min(x_in, x_out), u(0.780), max(x_in, x_out), u(0.936)],
                            radius=u(0.014), fill=NAVY, outline=OL, width=LW)

    # ── 팔: 흰 반팔 소매 → 흰 장갑 ──
    for sgn in (-1, 1):
        ax = cx + sgn * u(0.192)
        d.rounded_rectangle([ax - u(0.048), u(0.644), ax + u(0.048), u(0.746)],
                            radius=u(0.022), fill=SHIRT_C, outline=OL, width=LW)
        d.ellipse([ax - u(0.052), u(0.730), ax + u(0.052), u(0.824)],
                  fill=SHIRT_C, outline=OL, width=LW)

    # ── 몸통: 흰 제복 ──
    d.rounded_rectangle([cx - u(0.170), u(0.632), cx + u(0.170), u(0.792)],
                        radius=u(0.026), fill=SHIRT_C, outline=OL, width=LW)
    # 옷깃 V
    d.polygon([(cx - u(0.086), u(0.630)), (cx, u(0.700)), (cx + u(0.086), u(0.630))],
              fill=NAVY, outline=OL)
    # 앞여밈 (지퍼 선 + 띠)
    d.rectangle([cx - u(0.011), u(0.694), cx + u(0.011), u(0.790)],
                fill=(238, 240, 244), outline=OL, width=max(2, u(0.005)))
    # 왼가슴 노란 표장 · 오른가슴 태극 흉장 · 견장
    d.rounded_rectangle([cx - u(0.122), u(0.664), cx - u(0.070), u(0.690)],
                        radius=u(0.006), fill=GOLD, outline=OL, width=max(2, u(0.005)))
    d.ellipse([cx + u(0.052), u(0.660), cx + u(0.112), u(0.720)],
              fill=(240, 243, 248), outline=OL, width=max(2, u(0.006)))
    d.ellipse([cx + u(0.066), u(0.674), cx + u(0.098), u(0.706)], fill=(196, 52, 52))
    d.polygon([(cx + u(0.126), u(0.636)), (cx + u(0.170), u(0.642)),
               (cx + u(0.166), u(0.672)), (cx + u(0.126), u(0.664))],
              fill=(72, 78, 96), outline=OL)

    # ── 귀 (머리 뒤에 깔림). 포돌이의 상징: 크고 옆으로 활짝 ──
    for sgn in (-1, 1):
        ex = cx + sgn * u(0.229)
        d.ellipse([ex - u(0.072), hcy - u(0.080), ex + u(0.072), hcy + u(0.080)],
                  fill=SKIN_C, outline=OL, width=LW)
        d.arc([ex - u(0.038), hcy - u(0.046), ex + u(0.038), hcy + u(0.046)],
              100 if sgn > 0 else 260, 260 if sgn > 0 else 100,
              fill=OL, width=max(2, u(0.008)))

    # ── 머리 ──
    d.ellipse([cx - R, hcy - u(0.192), cx + R, hcy + u(0.192)],
              fill=SKIN_C, outline=OL, width=LW)
    # 볼터치
    for sgn in (-1, 1):
        bx = cx + sgn * u(0.152)
        d.ellipse([bx - u(0.030), hcy + u(0.028), bx + u(0.030), hcy + u(0.070)], fill=BLUSH_C)
    # 눈: 크고 세로로 긴 타원 + 큰 검은 눈동자
    for sgn in (-1, 1):
        ex = cx + sgn * u(0.072)
        d.ellipse([ex - u(0.052), hcy - u(0.076), ex + u(0.052), hcy + u(0.058)],
                  fill=(255, 255, 255), outline=OL, width=LW)
        d.ellipse([ex - u(0.030), hcy - u(0.052), ex + u(0.030), hcy + u(0.032)], fill=OL)
        d.ellipse([ex - u(0.022), hcy - u(0.044), ex - u(0.004), hcy - u(0.022)],
                  fill=(255, 255, 255))
    # 코 (둥글고 큼) · 웃는 입
    d.ellipse([cx - u(0.036), hcy + u(0.040), cx + u(0.036), hcy + u(0.096)],
              fill=NOSE_C, outline=OL, width=max(2, u(0.006)))
    d.chord([cx - u(0.062), hcy + u(0.084), cx + u(0.062), hcy + u(0.168)], 0, 180,
            fill=MOUTH_C, outline=OL, width=LW)

    # ── 정모 ──
    # 챙 (짙은 남색, 아래로 굽음)
    d.ellipse([cx - u(0.238), u(0.246), cx + u(0.238), u(0.318)],
              fill=NAVY, outline=OL, width=LW)
    # 격자 띠: 짙은 바탕에 흰 격자
    gx0, gx1, gy0, gy1 = cx - u(0.206), cx + u(0.206), u(0.196), u(0.252)
    d.rectangle([gx0, gy0, gx1, gy1], fill=(38, 46, 68), outline=OL, width=max(2, u(0.005)))
    d.line([(gx0, (gy0 + gy1) // 2), (gx1, (gy0 + gy1) // 2)],
           fill=(232, 236, 244), width=max(2, u(0.005)))
    step = max(4, u(0.026))
    for gx in range(gx0 + step, gx1, step):
        d.line([(gx, gy0), (gx, gy1)], fill=(232, 236, 244), width=max(1, u(0.004)))
    # 금색 띠
    d.rounded_rectangle([cx - u(0.212), u(0.176), cx + u(0.212), u(0.208)],
                        radius=u(0.010), fill=GOLD, outline=OL, width=max(2, u(0.006)))
    # 흰 크라운 (둥근 돔)
    d.pieslice([cx - u(0.196), u(0.012), cx + u(0.196), u(0.372)], 180, 360,
               fill=SHIRT_C, outline=OL, width=LW)
    # 독수리 엠블럼: 펼친 날개 + 몸통 + 태극
    ey = u(0.082)
    # 좌우로 펼친 날개 (끝이 위로 들리는 형태)
    for sgn in (-1, 1):
        d.polygon([(cx + sgn * u(0.012), ey - u(0.032)),
                   (cx + sgn * u(0.054), ey - u(0.052)),
                   (cx + sgn * u(0.106), ey - u(0.040)),
                   (cx + sgn * u(0.086), ey - u(0.004)),
                   (cx + sgn * u(0.034), ey + u(0.012))], fill=GOLD, outline=OL)
    # 몸통 · 머리
    d.ellipse([cx - u(0.019), ey - u(0.040), cx + u(0.019), ey + u(0.016)],
              fill=GOLD, outline=OL, width=max(2, u(0.005)))
    d.ellipse([cx - u(0.011), ey - u(0.058), cx + u(0.011), ey - u(0.034)],
              fill=GOLD, outline=OL, width=max(2, u(0.005)))
    # 태극
    d.ellipse([cx - u(0.014), ey + u(0.012), cx + u(0.014), ey + u(0.040)],
              fill=(240, 240, 244), outline=OL, width=max(2, u(0.005)))
    d.chord([cx - u(0.014), ey + u(0.012), cx + u(0.014), ey + u(0.040)], 180, 360,
            fill=(196, 52, 52))
    d.chord([cx - u(0.014), ey + u(0.012), cx + u(0.014), ey + u(0.040)], 0, 180,
            fill=(40, 68, 160))
    return lay


_PODORI: Image.Image | None = None

LOGO_FILE = Path(__file__).resolve().parent.parent / "assets" / "pm-enforcement" / "logo.png"
_LOGO: Image.Image | None = None


def load_logo(width: int) -> Image.Image | None:
    """마무리에 넣을 서울경찰청 로고. 없으면 None (로고 없이 렌더)."""
    if not LOGO_FILE.exists():
        print(f"  로고: 없음 ({LOGO_FILE} 에 넣으면 마무리에 표시)")
        return None
    im = Image.open(LOGO_FILE).convert("RGBA")
    h = max(1, int(round(im.height * width / im.width)))
    print(f"  로고: {LOGO_FILE.name} 사용 ({im.width}x{im.height} → {width}x{h})")
    return im.resize((width, h), Image.LANCZOS)


def speech_bubble(d: ImageDraw.ImageDraw, box, tail_to, lines):
    """포돌이 말풍선. lines = [(텍스트, 크기, 색)]"""
    x0, y0, x1, y1 = box
    d.polygon([tail_to, (x0 + 30, y0 + (y1 - y0) * 0.32), (x0 + 30, y0 + (y1 - y0) * 0.62)],
              fill=(10, 13, 22), outline=POLICE_RED)
    d.rounded_rectangle([x0, y0, x1, y1], radius=26, fill=(10, 13, 22))
    d.rounded_rectangle([x0, y0, x1, y1], radius=26, outline=POLICE_RED, width=5)
    total = sum(sz + 18 for _, sz, _ in lines)
    y = y0 + ((y1 - y0) - total) / 2 + lines[0][1] / 2 + 6
    for s, sz, col in lines:
        text(d, ((x0 + x1) // 2, int(y)), s, sz, fill=col, bold=0)
        y += sz + 18


# ══════════════════════════════════════════════════════════════
# 이펙트
# ══════════════════════════════════════════════════════════════
def beacon(img: Image.Image, t: float, strength: float = 1.0) -> Image.Image:
    """경광등: 위쪽에서 내려오는 적/청 교차 글로우."""
    if strength <= 0:
        return img
    col = POLICE_RED if int(t / 0.30) % 2 == 0 else POLICE_BLUE
    ov = Image.new("RGB", img.size, col)
    mask = Image.linear_gradient("L").resize(img.size).point(
        lambda v: int((255 - v) * 0.42 * strength))
    out = img.copy()
    out.paste(ov, (0, 0), mask)
    return out


def vignette(img: Image.Image, amount: float = 0.55) -> Image.Image:
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).ellipse([-int(W * 0.35), -int(H * 0.12),
                               W + int(W * 0.35), H + int(H * 0.12)], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(160)).point(lambda v: int(255 - (255 - v) * amount))
    black = Image.new("RGB", img.size, (0, 0, 0))
    return Image.composite(img, black, m)


def zoom_box(img: Image.Image, box, out_size=(W, H)):
    """box=(cx,cy,w,h) 영역을 잘라 화면 크기로 확대.

    반환: (확대 이미지, 실제 크롭 사각형 (x0, y0, w, h))
    빨간 원 좌표는 요청 박스가 아니라 이 '실제' 크롭으로 환산해야 한다.
    프레임을 벗어나는 박스는 축소·이동해 보정하므로 둘이 달라진다.
    """
    cx, cy, bw, bh = box
    ar = out_size[0] / out_size[1]
    if bw / bh > ar:
        bh = bw / ar
    else:
        bw = bh * ar
    # 프레임보다 큰 박스는 비율을 유지한 채 축소 (검은 여백 방지)
    k = min(1.0, img.width / bw, img.height / bh)
    bw, bh = bw * k, bh * k
    x0 = min(max(0.0, cx - bw / 2), img.width - bw)
    y0 = min(max(0.0, cy - bh / 2), img.height - bh)
    # crop() 으로 정수 픽셀에 스냅시키면 프레임마다 크롭 원점이 ±1px 튀어
    # 확대 구간이 떨린다. resize(box=...) 에 float 좌표를 그대로 넘겨
    # 서브픽셀 정밀도로 리샘플한다.
    out = img.resize(out_size, Image.LANCZOS, box=(x0, y0, x0 + bw, y0 + bh))
    return out, (x0, y0, bw, bh)


def stamp(d, xy, label, angle_seed=0, scale=1.0, alpha_col=POLICE_RED):
    """단속 도장 느낌의 사각 테두리 + 텍스트."""
    x, y = xy
    w, h = int(300 * scale), int(96 * scale)
    d.rounded_rectangle([x - w // 2, y - h // 2, x + w // 2, y + h // 2],
                        radius=int(10 * scale), outline=alpha_col, width=max(3, int(7 * scale)))
    d.rounded_rectangle([x - w // 2 + 10, y - h // 2 + 10, x + w // 2 - 10, y + h // 2 - 10],
                        radius=int(6 * scale), outline=alpha_col, width=max(2, int(3 * scale)))
    text(d, (x, y), label, int(46 * scale), fill=alpha_col, bold=0)


# ══════════════════════════════════════════════════════════════
# 타임라인
# ══════════════════════════════════════════════════════════════
VIOLATIONS = [
    # 자막, 금액, 근거 조문, 앵커 키, 확대 여유(반지름 배수)
    #
    # 조문 근거 (개인형 이동장치 기준):
    #   제44조     술에 취한 상태에서의 운전 금지
    #   제43조     무면허운전 등의 금지 (PM 은 원동기장치자전거 면허 이상 필요)
    #   제50조⑩   개인형 이동장치 승차정원 초과 금지 (전동킥보드 정원 1명)
    #   제50조④   자전거등의 운전자 인명보호 장구 착용 의무
    #             ※ 제50조③ 은 "개인형 이동장치는 제외한다" 이므로 PM 은 ④항이 근거
    ("음주운전", 100000, "도로교통법 제44조", "bottle", 1.55),
    ("무면허 운전", 100000, "도로교통법 제43조", "license", 1.55),
    ("승차정원 위반", 40000, "도로교통법 제50조제10항", "deck", 1.40),
    ("인명보호장구 미착용", 20000, "도로교통법 제50조제4항", "heads", 1.35),
]


def violation_target(key: str, pad: float):
    """앵커(cx, cy, r) → (확대 박스, 빨간 원). 화면 밖으로 나가지 않게 보정."""
    cx, cy, r = ANCHORS[key]
    half = r * pad
    cx = max(half, min(W - half, cx))
    cy = max(half, min(H - half, cy))
    return (cx, cy, half * 2, half * 2), (cx, cy, r * 0.92)

T_HOOK_MOVE = 1.2      # 주행 → 정지
T_HOOK_END = 4.5       # 포돌이 "단속하겠습니다" 구간을 TTS 길이에 맞춰 확보
T_PROBLEM_END = 5.4    # 도장 0.9s
T_OBSERVE_END = 9.4    # 카운트다운 4.0s
T_OBSERVE_DUR = T_OBSERVE_END - T_PROBLEM_END
T_CATCH_EACH = 3.9
T_CATCH_END = T_OBSERVE_END + T_CATCH_EACH * 4   # 25.0
T_TOTAL = 30.0


def won(v: int) -> str:
    return f"{v // 10000}만원"


def render_frame(t: float, scene_static: Image.Image) -> Image.Image:
    # ─────────────────────────── 0.0–3.0  훅
    if t < T_HOOK_END:
        if t < T_HOOK_MOVE:
            p = t / T_HOOK_MOVE
            off = int(lerp(-210, 0, ease_out(p)))
            img = draw_scene(offset_x=off, speed_lines=1.0 - ease_out(p) * 0.35)
        else:
            img = scene_static.copy()

        since = t - T_HOOK_MOVE
        if 0 <= since < 0.12:                       # 정지 순간 화이트 플래시
            img = Image.blend(img, Image.new("RGB", img.size, WHITE), 0.75 * (1 - since / 0.12))
        if since >= 0:
            img = beacon(img, t, strength=clamp(since / 0.25))
            img = vignette(img, 0.5)

        d = ImageDraw.Draw(img)
        if since >= 0.10:
            # 정지 배지
            a = ease_out((since - 0.10) / 0.35)
            bw2 = int(lerp(60, 300, a))
            d.rounded_rectangle([W // 2 - bw2, 300 - 54, W // 2 + bw2, 300 + 54],
                                radius=16, fill=POLICE_RED)
            if a > 0.6:
                text(d, (W // 2, 300), "단 속", 62, fill=WHITE, bold=0)
        # 포돌이 등장: 아래에서 튀어오르며 말풍선으로 단속 고지
        if since >= 0.40:
            k = ease_out(clamp((since - 0.40) / 0.45))
            pod = _PODORI
            px = 26
            py = int(lerp(H + 40, H - pod.height - 24, k))
            img.paste(pod, (px, py), pod)
            d = ImageDraw.Draw(img)
            if k > 0.55:
                head_y = py + int(pod.height * 0.30)
                speech_bubble(
                    d,
                    (px + pod.width - 40, head_y - 150, W - 34, head_y + 190),
                    (px + pod.width - 78, head_y + 10),
                    [("잠깐!", 50, WARN),
                     ("개인형 이동장치", 36, WHITE),
                     ("도로교통법 위반으로", 36, WHITE),
                     ("단속하겠습니다", 44, POLICE_RED)],
                )
        return img

    # ─────────────────────────── 3.0–4.0  문제 제시
    if t < T_PROBLEM_END:
        img = beacon(vignette(scene_static.copy(), 0.5), t, 0.55)
        d = ImageDraw.Draw(img)
        p = (t - T_HOOK_END) / (T_PROBLEM_END - T_HOOK_END)
        # 도장 4개가 순차로 쾅. 인물을 가리지 않도록 머리 위 빈 하늘에 2x2 배치.
        grid = [(W // 2 - 168, 424), (W // 2 + 168, 424),
                (W // 2 - 168, 542), (W // 2 + 168, 542)]
        for i, (gx, gy) in enumerate(grid):
            st = i * 0.18
            if p < st:
                continue
            k = clamp((p - st) / 0.16)
            sc = lerp(2.1, 1.0, ease_out(k)) * 0.98     # 크게 → 제자리
            stamp(d, (gx, gy), f"위반 {i + 1}", scale=sc)
        text(d, (W // 2, 300), "위반 사항  총 4건", 66, fill=WARN, bold=4)
        return img

    # ─────────────────────────── 4.0–9.0  관찰 타임
    if t < T_OBSERVE_END:
        img = scene_static.copy()
        img = beacon(img, t, 0.18)
        d = ImageDraw.Draw(img)
        left = T_OBSERVE_END - t
        n = int(math.ceil(left))                        # 4,3,2,1
        frac = 1.0 - (left - int(left))

        # 상단 링 카운트다운
        cxr, cyr, r = W // 2, 268, 92
        d.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], outline=(90, 100, 120), width=12)
        d.arc([cxr - r, cyr - r, cxr + r, cyr + r], -90,
              -90 + int(360 * (left / T_OBSERVE_DUR)), fill=WARN, width=12)
        pop = 1.0 + 0.28 * (1 - ease_out(min(1.0, frac * 3)))
        text(d, (cxr, cyr), str(n), int(96 * pop), fill=WHITE, bold=3)

        text(d, (W // 2, 430), "찾아보세요", 74, fill=WHITE, bold=4)
        text(d, (W // 2, 500), "위반 4건이 이 장면 안에 있습니다", 38, fill=(190, 200, 215), bold=2)
        return img

    # ─────────────────────────── 9.0–25.0  적발
    if t < T_CATCH_END:
        idx = int((t - T_OBSERVE_END) // T_CATCH_EACH)
        idx = min(idx, 3)
        local = (t - T_OBSERVE_END) - idx * T_CATCH_EACH
        label, amount, article, key, pad = VIOLATIONS[idx]
        box, circ = violation_target(key, pad)

        # 0.0-0.5 줌인 / 0.5-3.5 유지 / 3.5-4.0 살짝 더
        zp = ease_in_out(clamp(local / 0.5))
        cx0, cy0 = W // 2, (HORIZON_Y + GROUND_Y) // 2
        bcx, bcy, bw, bh = box
        cur_cx = lerp(cx0, bcx, zp)
        cur_cy = lerp(cy0, bcy, zp)
        cur_w = lerp(W, bw, zp)
        cur_h = lerp(H, bh, zp)
        # 줌인이 끝나면 완전히 고정한다. 예전의 느린 푸시인(drift)은 매 프레임
        # 크롭 크기를 조금씩 바꿔 화면이 미세하게 흔들리는 원인이었다.
        img, crop_rect = zoom_box(scene_static, (cur_cx, cur_cy, cur_w, cur_h))

        if local < 0.14:                                # 셔터 플래시
            img = Image.blend(img, Image.new("RGB", img.size, WHITE), 0.6 * (1 - local / 0.14))
        img = beacon(img, t, 0.14)
        img = vignette(img, 0.5)
        d = ImageDraw.Draw(img)

        # 빨간 원: 실제 크롭 사각형 기준으로 환산해야 대상 위에 정확히 얹힌다
        if local > 0.35:
            ox, oy, orad = circ
            rx0, ry0, rw, rh = crop_rect
            sx, sy = W / rw, H / rh
            px = (ox - rx0) * sx
            py = (oy - ry0) * sy
            pr = orad * sx
            k = ease_out(clamp((local - 0.35) / 0.4))
            pr_now = pr * lerp(1.9, 1.0, k)
            d.ellipse([px - pr_now, py - pr_now, px + pr_now, py + pr_now],
                      outline=POLICE_RED, width=int(lerp(4, 13, k)))

        # 무면허는 시각 단서가 없으므로 면허증 아이콘으로 표기
        if idx == 1 and local > 0.6:
            k = ease_out(clamp((local - 0.6) / 0.35))
            cardw, cardh = int(430 * k), int(268 * k)
            cx1, cy1 = W // 2, int(H * 0.44)
            d.rounded_rectangle([cx1 - cardw // 2, cy1 - cardh // 2,
                                 cx1 + cardw // 2, cy1 + cardh // 2],
                                radius=16, fill=(238, 240, 245), outline=INK, width=5)
            if k > 0.7:
                # 면허증 모양: 사진칸 + 정보 줄
                d.rounded_rectangle([cx1 - 178, cy1 - 86, cx1 - 68, cy1 + 62],
                                    radius=8, fill=(196, 202, 214), outline=(150, 156, 170), width=3)
                for i, ln in enumerate((150, 110, 150)):
                    d.rounded_rectangle([cx1 - 40, cy1 - 74 + i * 46,
                                         cx1 - 40 + ln, cy1 - 58 + i * 46],
                                        radius=6, fill=(178, 185, 198))
                text(d, (cx1, cy1 - 108), "운전면허증", 36, fill=(70, 76, 92), bold=0)
                # 빨간 X (글자보다 먼저 그려 가독성 유지)
                for a, b in (((-1, -1), (1, 1)), ((1, -1), (-1, 1))):
                    d.line([cx1 + a[0] * cardw // 2, cy1 + a[1] * cardh // 2,
                            cx1 + b[0] * cardw // 2, cy1 + b[1] * cardh // 2],
                           fill=POLICE_RED, width=18)
                text(d, (cx1, cy1 + cardh // 2 + 62), "미소지", 58,
                     fill=POLICE_RED, bold=5, stroke_fill=(12, 16, 26))

        # 하단 조서 카드
        if local > 0.5:
            k = ease_out(clamp((local - 0.5) / 0.3))
            y0 = int(lerp(H + 60, H - 520, k))
            d.rounded_rectangle([60, y0, W - 60, y0 + 348], radius=26,
                                fill=(16, 20, 30), outline=POLICE_RED, width=6)
            text(d, (110, y0 + 62), f"{idx + 1}", 76, fill=POLICE_RED, anchor="lm", bold=0)
            text(d, (194, y0 + 62), label, 58, fill=WHITE, anchor="lm", bold=0)
            # 근거 조문
            text(d, (110, y0 + 132), article, 34, fill=(146, 160, 186), anchor="lm")
            d.line([110, y0 + 178, W - 110, y0 + 178], fill=(58, 66, 84), width=4)
            text(d, (110, y0 + 258), "범칙금", 40, fill=(160, 170, 190), anchor="lm")
            text(d, (W - 110, y0 + 258), won(amount), 86, fill=WARN, anchor="rm", bold=0)

        # 진행 표시
        for i in range(4):
            col = POLICE_RED if i <= idx else (70, 78, 96)
            d.rounded_rectangle([W // 2 - 190 + i * 100, 96, W // 2 - 120 + i * 100, 108],
                                radius=6, fill=col)
        return img

    # ─────────────────────────── 25.0–30.0  마무리
    img = Image.new("RGB", (W, H), (12, 16, 26))
    d = ImageDraw.Draw(img)
    p = (t - T_CATCH_END) / (T_TOTAL - T_CATCH_END)   # 0..1 (5초)

    # 4개 항목 나열 (근거 조문 포함)
    for i, (label, amount, article, *_rest) in enumerate(VIOLATIONS):
        appear = clamp((p - i * 0.055) / 0.10)
        if appear <= 0:
            continue
        y = 402 + i * 126
        a = ease_out(appear)
        text(d, (110, y), label, 46, fill=(int(lerp(20, 235, a)),) * 3, anchor="lm", bold=0)
        text(d, (110, y + 40), article, 28,
             fill=(int(lerp(16, 140, a)), int(lerp(16, 152, a)), int(lerp(16, 178, a))),
             anchor="lm")
        text(d, (W - 110, y + 8), won(amount), 52, fill=(int(lerp(20, 255, a)),
                                                         int(lerp(20, 210, a)),
                                                         int(lerp(20, 63, a))), anchor="rm", bold=0)

    # 합계 롤업
    if p > 0.32:
        k = ease_out(clamp((p - 0.32) / 0.30))
        d.line([110, 900, W - 110, 900], fill=(70, 78, 96), width=5)
        text(d, (110, 985), "합계", 50, fill=(170, 180, 200), anchor="lm")
        rolling = int(lerp(0, 260000, k) / 10000) * 10000
        text(d, (W - 110, 985), won(rolling), int(lerp(70, 112, k)),
             fill=POLICE_RED, anchor="rm", bold=0)

    # 마지막 문장 (톤 다운 구간). 슬로건을 살리려고 한 단계 작게.
    if p > 0.50:
        k = ease_out(clamp((p - 0.50) / 0.20))
        c = int(214 * k)
        text(d, (W // 2, 1222), "하지만", 36, fill=(c, c, c))
        text(d, (W // 2, 1288), "돈으로 막을 수 없는 것도", 46, fill=(c, c, c), bold=0)
        text(d, (W // 2, 1346), "있습니다", 46, fill=(c, c, c), bold=0)

    # 슬로건: 이 영상의 결론이므로 노란색 + 굵게 강조
    if p > 0.64:
        k = ease_out(clamp((p - 0.64) / 0.20))
        col = (int(255 * k), int(210 * k), int(63 * k))
        text(d, (W // 2, 1476), "당신의 안전은", 50, fill=col, bold=4, stroke_fill=(12, 16, 26))
        text(d, (W // 2, 1544), "무엇과도 바꿀 수 없습니다", 50, fill=col, bold=4,
             stroke_fill=(12, 16, 26))

    # 로고: 맨 아래
    if p > 0.78:
        k = ease_out(clamp((p - 0.78) / 0.20))
        if _LOGO is not None:
            # 로고는 감청/금색의 진한 색이라 어두운 배경에서 묻힌다.
            # 원래 색을 살리려고 흰 패널 위에 올린다(리컬러 금지).
            lg = _LOGO
            pad = 40
            pw, ph = lg.width + pad * 2, lg.height + pad * 2
            panel = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
            ImageDraw.Draw(panel).rounded_rectangle(
                [0, 0, pw - 1, ph - 1], radius=24, fill=(255, 255, 255, int(242 * k)))
            faded = lg.copy()
            faded.putalpha(lg.getchannel("A").point(lambda v: int(v * k)))
            panel.paste(faded, (pad, pad), faded)
            img.paste(panel, ((W - pw) // 2, H - ph - 64), panel)
    return img


def sub_box(d: ImageDraw.ImageDraw, line1: str, line2: str | None = None):
    """하단 나레이션 자막 박스."""
    y0 = H - 430
    h = 150 if line2 else 96
    d.rounded_rectangle([56, y0, W - 56, y0 + h], radius=20, fill=(10, 13, 22))
    d.rounded_rectangle([56, y0, W - 56, y0 + h], radius=20, outline=POLICE_RED, width=5)
    if line2:
        text(d, (W // 2, y0 + 48), line1, 44, fill=WHITE, bold=0)
        text(d, (W // 2, y0 + 104), line2, 40, fill=WHITE, bold=0)
    else:
        text(d, (W // 2, y0 + h // 2), line1, 44, fill=WHITE, bold=0)


# ══════════════════════════════════════════════════════════════
def main(argv=None) -> int:
    global W, H, GROUND_Y, HORIZON_Y, _BG

    ap = argparse.ArgumentParser(description="PM 단속 30초 숏폼 렌더러")
    ap.add_argument("-o", "--output", default="assets/pm-enforcement/pm-enforcement.mp4")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seconds", type=float, default=T_TOTAL)
    ap.add_argument("--landscape", action="store_true", help="16:9 가로로 렌더")
    args = ap.parse_args(argv)

    if args.landscape:
        W, H = 1920, 1080
        HORIZON_Y, GROUND_Y = 560, 880

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 56)
    print("PM 단속 숏폼 렌더러")
    print(f"  해상도 {W}x{H} · {args.fps}fps · {args.seconds:.0f}초")
    print(f"  폰트   {FONT_PATH}")
    print("=" * 56)

    globals()["_PODORI"] = load_podori(int(700 * (H / 1920)))
    globals()["_LOGO"] = load_logo(int(560 * (W / 1080)))
    _BG = draw_background()
    scene_static = draw_scene(offset_x=0, speed_lines=0.0)

    total = int(round(args.seconds * args.fps))
    container = av.open(str(out), mode="w")
    stream = container.add_stream("h264", rate=args.fps)
    stream.width, stream.height = W, H
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": "20", "preset": "medium"}

    for i in range(total):
        t = i / args.fps
        frame = render_frame(t, scene_static)
        vf = av.VideoFrame.from_ndarray(np.asarray(frame), format="rgb24")
        for pkt in stream.encode(vf):
            container.mux(pkt)
        if i % 60 == 0:
            print(f"  {t:5.1f}s / {args.seconds:.0f}s  ({i}/{total})")

    for pkt in stream.encode(None):
        container.mux(pkt)
    container.close()

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"\n완료: {out}  ({size_mb:.2f} MB)")
    print(f"OUTPUT={out.resolve()}")
    return 0


_BG: Image.Image | None = None

if __name__ == "__main__":
    sys.exit(main())
