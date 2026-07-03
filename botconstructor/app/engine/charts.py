import io

from PIL import Image, ImageDraw, ImageFont


def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def draw_bar_chart(labels: list[str], values: list[int], title: str) -> bytes:
    width, height = 640, 360
    padding = 50
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    title_font = _font(18)
    label_font = _font(13)
    value_font = _font(13)

    draw.text((padding, 15), title, fill=(30, 30, 30), font=title_font)

    chart_top = 50
    chart_bottom = height - 50
    chart_left = padding
    chart_right = width - 20
    max_val = max(values) if values and max(values) > 0 else 1

    draw.line([(chart_left, chart_top), (chart_left, chart_bottom)], fill=(200, 200, 200), width=1)
    draw.line([(chart_left, chart_bottom), (chart_right, chart_bottom)], fill=(200, 200, 200), width=1)

    n = max(len(values), 1)
    bar_area_w = chart_right - chart_left
    bar_w = bar_area_w / n * 0.6
    gap = bar_area_w / n

    for i, (label, val) in enumerate(zip(labels, values)):
        bar_h = (val / max_val) * (chart_bottom - chart_top - 20)
        x0 = chart_left + i * gap + (gap - bar_w) / 2
        x1 = x0 + bar_w
        y1 = chart_bottom
        y0 = chart_bottom - bar_h
        color = (66, 133, 165) if val > 0 else (220, 220, 220)
        draw.rectangle([x0, y0, x1, y1], fill=color)
        draw.text((x0, y0 - 16), str(val), fill=(30, 30, 30), font=value_font)
        draw.text((x0, chart_bottom + 5), label, fill=(80, 80, 80), font=label_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
