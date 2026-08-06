"""Word-boundary phrase matching shared by the interpreter and the gap finder.

Matching has to be forgiving about inflection — people type "indexing" where the
vocabulary says "index", and "reviewer" where it says "reviewers" — but never so
loose that a phrase matches inside an unrelated word ("count" must not match
"country"). Allowing only a closed set of inflections gives us the first without
the second.
"""
from __future__ import annotations

import re

#: Suffixes that may separate a typed word from its vocabulary form, in either
#: direction. A closed set on purpose: open-ended stemming produces false hits.
_INFLECTIONS = ("s", "es", "ed", "d", "ing", "er", "ers", "ion", "ions")

_NON_WORD_RE = re.compile(r"[^a-z0-9]+")

#: Expanded BEFORE punctuation is stripped, because stripping turns "what's"
#: into "what s" — which would never match the expanded "what is" a user typed.
#: The knowledge files use contracted forms; people type both.
_CONTRACTIONS = {
    "what's": "what is", "it's": "it is", "that's": "that is",
    "there's": "there is", "how's": "how is", "where's": "where is",
    "who's": "who is", "isn't": "is not", "aren't": "are not",
    "doesn't": "does not", "don't": "do not", "didn't": "did not",
    "wasn't": "was not", "weren't": "were not", "hasn't": "has not",
    "haven't": "have not", "can't": "cannot", "won't": "will not",
    "we're": "we are", "they're": "they are", "we've": "we have",
}
_CONTRACTION_RE = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in _CONTRACTIONS) + r")\b"
)


def normalize(text: str | None) -> str:
    """Lowercase, expand contractions, collapse every non-alphanumeric run to a
    single space, and pad with spaces so a padded substring test is a
    word-boundary test.
    "how many alerts got dead-lettered?" -> " how many alerts got dead lettered "
    """
    lowered = (text or "").lower().replace("’", "'")
    expanded = _CONTRACTION_RE.sub(lambda m: _CONTRACTIONS[m.group(1)], lowered)
    cleaned = _NON_WORD_RE.sub(" ", expanded).strip()
    return f" {cleaned} " if cleaned else " "


def tokens(text: str | None) -> list[str]:
    return normalize(text).split()


def phrase_in(haystack: str | None, phrase: str | None) -> bool:
    """Is `phrase` present in `haystack` as consecutive whole words?

    The final word may differ by one inflection in either direction, so the
    vocabulary's "dead-lettered" still matches a user's "dead letter" and
    "connector failed" matches "connector fail". Leading words must match
    exactly: loosening those turns distinct monitors into each other.
    """
    target = normalize(phrase).split()
    if not target:
        return False

    words = normalize(haystack).split()
    span = len(target)
    for i in range(len(words) - span + 1):
        window = words[i:i + span]
        if window[:-1] == target[:-1] and _inflected_match(target[-1], window[-1]):
            return True
    return False


def _inflected_match(phrase: str, token: str) -> bool:
    if phrase == token:
        return True
    for suffix in _INFLECTIONS:
        if token == phrase + suffix or phrase == token + suffix:
            return True
    return False
