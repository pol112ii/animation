import functools
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 区域标签是中文，需要一个覆盖 CJK 的字体。按 Windows / macOS / Linux 依次探测，
# 找不到就退回 PIL 内置位图字体（中文会显示为方块，但不至于让脚本崩掉）。
# 可用环境变量 WHITEBOARD_FONT 指定字体文件，优先级最高。
_FONT_CANDIDATES = (
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
)


def _fc_match_cjk() -> str | None:
    """借 fontconfig 找一个能显示中文的字体（Linux/macOS 上通常可用）。"""
    try:
        out = subprocess.run(
            ["fc-match", "-f", "%{file}", ":lang=zh"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    path = out.stdout.strip()
    return path if out.returncode == 0 and path and Path(path).exists() else None


@functools.lru_cache(maxsize=1)
def _font_file() -> str | None:
    """按候选列表逐个探测，返回第一个能被 PIL 打开的字体文件路径。"""
    override = os.environ.get("WHITEBOARD_FONT")
    candidates = [override] if override else []
    candidates += [*_FONT_CANDIDATES]
    matched = _fc_match_cjk()
    if matched:
        candidates.append(matched)

    for candidate in candidates:
        if not candidate or not Path(candidate).exists():
            continue
        try:
            ImageFont.truetype(candidate, 16)
        except OSError:
            continue
        return candidate

    print(
        "[warn] 未找到可用的中文字体，改用 PIL 内置字体（中文标签会显示为方块）。\n"
        "       可设置环境变量 WHITEBOARD_FONT=<字体文件路径> 指定字体。",
        file=sys.stderr,
    )
    return None


def resolve_font(size: int):
    """返回指定字号的字体；没有可用 TrueType 字体时退回 PIL 内置位图字体。"""
    path = _font_file()
    if path is not None:
        return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size)  # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def main(image_path: str, annotation_path: str, output_path: str) -> None:
    image = Image.open(image_path).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = resolve_font(28)
    small_font = resolve_font(18)
    colors = [(38, 103, 255, 225), (255, 105, 92, 225), (41, 167, 102, 225), (181, 100, 255, 225)]

    data = json.loads(Path(annotation_path).read_text(encoding="utf-8"))
    for index, element in enumerate(data["elements"], start=1):
        region = element["region"]
        x, y = region["x"], region["y"]
        right, bottom = x + region["width"], y + region["height"]
        color = colors[(index - 1) % len(colors)]
        fill = (*color[:3], 24)
        draw.rounded_rectangle((x, y, right, bottom), radius=12, outline=color, width=4, fill=fill)
        draw.ellipse((x + 8, y + 8, x + 44, y + 44), fill=color)
        draw.text((x + 19, y + 8), str(index), anchor="ma", font=small_font, fill="white")
        label = f"{index}. {element['label']}  {element['reveal']['direction']}"
        draw.rounded_rectangle((x + 52, y + 8, min(right - 8, x + 52 + len(label) * 19), y + 46), radius=6, fill=(255, 255, 255, 225))
        draw.text((x + 60, y + 12), label, font=small_font, fill=color)
        start = tuple(element["handPath"]["start"])
        end = tuple(element["handPath"]["end"])
        draw.line((start, end), fill=color, width=4)
        draw.polygon((end, (end[0] - 13, end[1] - 7), (end[0] - 13, end[1] + 7)), fill=color)

    result = Image.alpha_composite(image, overlay).convert("RGB")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path, quality=95)


if __name__ == "__main__":
    main(*sys.argv[1:4])
