"""Session-based image captcha. Zero external services; Pillow draws a PNG."""
import random
from io import BytesIO

from django.http import HttpResponse
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# No 0/O/1/I — avoids user confusion.
CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SESSION_KEY = "captcha_code"
WIDTH, HEIGHT = 160, 55


def captcha_image(request):
    code = "".join(random.choices(CHARS, k=5))
    # ponytail: keep the last 3 issued codes — browsers can fetch the image
    # more than once per page view (prefetch, back-nav reload); storing a
    # single code would then never match what the user actually sees.
    codes = request.session.get(SESSION_KEY) or []
    request.session[SESSION_KEY] = (codes if isinstance(codes, list) else [codes])[-2:] + [code]

    img = Image.new("RGB", (WIDTH, HEIGHT), "#ffffff")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=34)
    for i, ch in enumerate(code):
        # navy-to-slate tones to match the portal palette
        draw.text(
            (12 + i * 28 + random.randint(-4, 4), random.randint(0, 10)),
            ch,
            font=font,
            fill=(random.randint(16, 60), random.randint(40, 80), random.randint(90, 140)),
        )
    for _ in range(5):  # noise lines
        draw.line(
            [(random.randint(0, WIDTH), random.randint(0, HEIGHT)) for _ in range(2)],
            fill="#C7CDD6",
            width=1,
        )
    img = img.filter(ImageFilter.SMOOTH)

    buf = BytesIO()
    img.save(buf, "PNG")
    return HttpResponse(
        buf.getvalue(),
        content_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


def check(request, answer):
    """One-time check: all stored codes are consumed either way."""
    expected = request.session.pop(SESSION_KEY, None) or []
    return answer.strip().upper() in expected
