"""Deterministic judge pre-pass — ported from the UI prototype.

Cheap, instant, catches the highest-frequency calques. Findings are merged
with the LLM judge and used to filter its false positives (architecture.md §7.3).
"""

from __future__ import annotations

import re

# (regex, wrong label, right label, category, explanation)
RULES: tuple[tuple[str, str, str, str, str], ...] = (
    (r"\bi\s+am\s+agree\b", "I am agree", "I agree", "grammar", '"Agree" is already a verb — no "am".'),
    (r"\binformations\b", "informations", "information", "word_choice", '"Information" is uncountable — never plural.'),
    (r"\bi\s+have\s+(\d+|twenty[- ]?five|thirty|forty)\s+years?\b", "I have … years", "I am … years old", "grammar", "Age uses 'to be', not 'to have' (calque from Italian)."),
    (r"\ba\s+([aeiou]\w+)", "a + vowel…", "an + vowel…", "articles", 'Use "an" before a vowel sound.'),
    (r"\bpeoples\b", "peoples", "people", "word_choice", '"People" is already plural.'),
    (r"\bdidn'?t\s+went\b", "didn't went", "didn't go", "tense", "After 'did/didn't' the verb goes back to base form."),
    (r"\bmore\s+better\b", "more better", "better", "grammar", '"Better" is already comparative.'),
    (r"\bexplain\s+me\b", "explain me", "explain to me", "grammar", '"Explain" needs "to" before the person.'),
    (r"\bi\s+want\s+that\s+you\b", "I want that you…", "I want you to…", "grammar", 'English uses "want + object + to + verb".'),
    (r"\bdepend\s+of\b", "depend of", "depend on", "grammar", '"Depend" takes "on".'),
    (r"\bi\s+am\s+here\s+since\b", "I am here since…", "I've been here since…", "tense", "An action continuing until now takes the present perfect."),
    (r"\bmake\s+a\s+(photo|picture|selfie)\b", "make a photo", "take a photo", "word_choice", "Collocation: take a photo."),
    (r"\bsuggest\s+me\b", "suggest me", "suggest (to me)", "grammar", '"Suggest" never takes a person directly.'),
    (r"\bfor\s+to\s+\w+\b", "for to …", "to …", "grammar", 'Purpose is "to + verb"; "for to" does not exist.'),
)

_STANDALONE_I = re.compile(r"(^|\s)i([\s,.'!?]|$)")


def rules_scan(text: str) -> list[dict]:
    """Deterministic findings, same shape as judge errors."""
    errors: list[dict] = []
    for pattern, wrong, right, category, why in RULES:
        if re.search(pattern, text, re.IGNORECASE):
            errors.append(
                {"category": category, "wrong": wrong, "right": right, "explanation": why, "severity": 2}
            )
    if re.match(r"^[a-z]", text.strip()):
        errors.append(
            {"category": "mechanics", "wrong": "lowercase sentence start", "right": "capitalize the first word", "explanation": "English sentences start with a capital letter.", "severity": 1}
        )
    if _STANDALONE_I.search(text):
        errors.append(
            {"category": "mechanics", "wrong": "lowercase i", "right": "I", "explanation": 'The pronoun "I" is always capitalized.', "severity": 1}
        )
    return errors
