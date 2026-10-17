"""Normalise camp facts from the OSM and DataVic overlays.

Suits accept pipe, comma or semicolon lists, singular or plural, any case.
Fee text is only free, paid or donation. Dollar amounts are removed from
display text and are never turned into a fee.
"""
import datetime as dt
import re

_MONEY_PARENS = re.compile(r"\(\s*\$\s*\d[\d,]*(?:\.\d+)?[^)]*\)")
_MONEY = re.compile(r"\$\s*\d[\d,]*(?:\.\d+)?")
_WORDS = re.compile(r"[a-z]+")
_SUITS = (
    ("tent", {"tent", "tents"}),
    ("caravan", {"caravan", "caravans"}),
    ("motorhome", {"motorhome", "motorhomes", "campervan", "campervans"}),
)


def scrub_money(value):
    text = _MONEY_PARENS.sub(" ", str(value or ""))
    text = _MONEY.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip(" ;,-")


def yn_flag(value):
    if value is True or value is False:
        return value
    text = str(value or "").strip().lower()
    if not text or text == "unknown":
        return None
    if text == "yes" or text.startswith("yes"):
        return True
    if text == "no" or text.startswith("no"):
        return False
    return None


def suit_flags(suits):
    """Return (tents, caravans, motorhomes). True when named, else None.

    'tents, caravans' and 'tent|caravan' are the same fact. Campervans count
    as motorhomes, which is the third filter. A note with no vehicle word
    ('4WD only') leaves all three unset.
    """
    raw = str(suits or "").strip().lower()
    if not raw or raw == "unknown":
        return None, None, None
    found = set()
    for part in re.split(r"[|,;]", raw):
        words = set(_WORDS.findall(part))
        for key, names in _SUITS:
            if words & names:
                found.add(key)
    if not found:
        return None, None, None
    return tuple(True if key in found else None for key, _names in _SUITS)


def nights_from(value):
    if isinstance(value, int):
        return value if 0 < value <= 365 else None
    raw = str(value or "").strip()
    match = re.search(r"(\d+)", raw)
    if not match:
        return None
    number = int(match.group(1))
    if "hour" in raw.lower():
        return max(1, int(round(number / 24.0)))
    return number if 0 < number <= 365 else None


def stay_label(value, nights=None):
    raw = scrub_money(value)
    if not raw or raw.lower() == "unknown":
        raw = ""
    if raw.isdigit():
        number = int(raw)
        return f"{number} night" if number == 1 else f"{number} nights"
    if raw:
        return raw
    if isinstance(nights, int) and 0 < nights <= 365:
        return f"{nights} night" if nights == 1 else f"{nights} nights"
    return ""


def checked_phrase(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        day = dt.date.fromisoformat(raw[:10])
        shown = day.strftime("%-d %B %Y")
    except Exception:
        shown = raw[:10]
    return f"Checked against official source, {shown}"


def dogs_fields(value):
    text = scrub_money(value)
    low = text.lower()
    if not text or low == "unknown":
        return "", None
    if low == "yes":
        return "", True
    if low == "no":
        return "", False
    if low.startswith("no"):
        return text, False
    if low.startswith("yes") or low == "on lead" or "leash" in low or "on lead" in low:
        return text, True
    return text, None


def yes_no_label(value):
    text = scrub_money(value)
    low = text.lower()
    if not text or low == "unknown":
        return ""
    if low in ("yes", "true"):
        return "Yes"
    if low in ("no", "false"):
        return "No"
    return text


def toilet_label(value):
    text = scrub_money(value)
    low = text.lower()
    if not text or low == "unknown":
        return ""
    if low == "yes":
        return "Yes"
    if low == "no":
        return "No"
    if low.startswith("yes"):
        rest = text[3:].strip(" ()")
        return f"Yes ({rest})" if rest else "Yes"
    if low.startswith("no"):
        rest = text[2:].strip(" ()")
        return f"No ({rest})" if rest else "No"
    return text[:1].upper() + text[1:]


def drinking_label(value):
    return toilet_label(value)


def booking_label(value):
    text = scrub_money(value)
    low = text.lower()
    if not text or low == "unknown":
        return ""
    if low in ("yes", "required", "true") or low.startswith("required"):
        return "Yes"
    if low in ("no", "not required", "false") or low.startswith("not required") or low.startswith("no"):
        return "No"
    if "recommend" in low:
        return "Recommended"
    return ""


def fee_label(value):
    text = str(value or "").strip().lower()
    if text == "free":
        return "Free"
    if text == "paid":
        return "Paid – book ahead"
    if text == "donation":
        return "Donation"
    return ""
