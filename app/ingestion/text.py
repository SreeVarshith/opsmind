"""Text normalization applied to every document (and later to every user query).

LLMs and web pages use typographic characters (non-breaking hyphens, curly quotes,
non-breaking spaces). They look identical to humans but break keyword search:
"reporting-etl" would not match "reporting‑etl". We map them all to plain ASCII.
"""
import unicodedata

_PUNCTUATION = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    " ": " ", " ": " ", " ": " ", "​": "",
    "…": "...",
})


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text).translate(_PUNCTUATION)
