import re
from datetime import datetime, timedelta, timezone

_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks", "y": "days"}  # y считаем как 365 дней


def parse_duration(raw: str) -> tuple[datetime | None, str]:
    """Возвращает (ban_until, human_label). ban_until=None означает перманентный бан."""
    raw = raw.strip().lower()
    if raw in ("perm", "permanent", "forever", "навсегда"):
        return None, "навсегда"

    m = re.fullmatch(r"(\d+)([mhdwy])", raw)
    if not m:
        raise ValueError("Неверный формат длительности. Примеры: 30m, 12h, 7d, 2w, 1y, perm")

    amount, unit = int(m.group(1)), m.group(2)
    if unit == "y":
        delta = timedelta(days=amount * 365)
    else:
        delta = timedelta(**{_UNITS[unit]: amount})

    until = datetime.now(timezone.utc) + delta
    label = {"m": "мин", "h": "ч", "d": "дн", "w": "нед", "y": "лет"}[unit]
    return until, f"{amount}{label}"
