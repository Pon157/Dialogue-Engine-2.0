import io
import random
import string

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_ALPHABET = string.ascii_uppercase.replace("O", "").replace("I", "") + string.digits.replace("0", "").replace("1", "")


def _random_font(size: int) -> ImageFont.FreeTypeFont:
    # DejaVuSans-Bold есть почти во всех Linux-окружениях с Pillow из коробки
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def generate_captcha(length: int = 5) -> tuple[str, bytes]:
    """Возвращает (правильный_ответ, png_bytes)."""
    answer = "".join(random.choices(_ALPHABET, k=length))

    width, height = 240, 100
    img = Image.new("RGB", (width, height), color=(245, 245, 245))
    draw = ImageDraw.Draw(img)

    # шумовые линии
    for _ in range(6):
        xy = [(random.randint(0, width), random.randint(0, height)) for _ in range(2)]
        draw.line(xy, fill=(random.randint(150, 200),) * 3, width=2)

    # шумовые точки
    for _ in range(200):
        x, y = random.randint(0, width - 1), random.randint(0, height - 1)
        draw.point((x, y), fill=(random.randint(120, 190),) * 3)

    x_cursor = 15
    for ch in answer:
        size = random.randint(34, 44)
        font = _random_font(size)
        char_img = Image.new("RGBA", (size + 10, size + 10), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_img)
        color = (random.randint(20, 90), random.randint(20, 90), random.randint(20, 90))
        char_draw.text((5, 0), ch, font=font, fill=color)

        angle = random.randint(-30, 30)
        char_img = char_img.rotate(angle, expand=True, resample=Image.BICUBIC)

        y_cursor = random.randint(10, 30)
        img.paste(char_img, (x_cursor, y_cursor), char_img)
        x_cursor += size - random.randint(2, 8)

    img = img.filter(ImageFilter.SMOOTH)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return answer, buf.getvalue()
