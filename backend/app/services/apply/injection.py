"""
Prompt-injection screening for external content (job postings, web pages).

Job postings and company pages are written by third parties. FK Apply treats
them strictly as DATA:

1. They are scanned here with high-precision patterns aimed at text that
   addresses an AI system ("ignore previous instructions", "if you are an AI
   screening this…", chat-template tokens, invisible characters).
2. When anything is found, the posting is flagged for the user AND its raw
   text is withheld from every LLM call — only deterministic extraction runs
   on it. (Detection can never be complete; withholding is what makes a hit
   harmless.)
3. Even for clean content, LLM prompts wrap external text in a randomly
   nonced data block and the model's output is schema-validated and checked
   by the fabrication guard before anything is stored. The model has no
   tools: its output is text that FK Apply validates, never an action.

The patterns are deliberately narrower than the generic detector in
``src/validation/security.py`` (which also flags phrases such as "act as a",
common in real job descriptions).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤﻿\U000e0000-\U000e007f]")

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+)?"
            r"(previous|prior|above|earlier|preceding|system)\s+"
            r"(instructions?|prompts?|rules|directions|guidelines)",
            re.I,
        ),
    ),
    (
        "addresses_ai",
        re.compile(
            r"\b(if\s+you\s+are|as)\s+an?\s+(ai|a\.i\.|llm|language\s+model|chatbot|assistant|"
            r"automated\s+(screener|system|reviewer))\b",
            re.I,
        ),
    ),
    (
        "addresses_ai",
        re.compile(
            r"\b(ai|llm|gpt|language\s+model|assistant)s?\s+(reading|processing|screening|"
            r"reviewing|parsing)\s+(this|the\s+following)",
            re.I,
        ),
    ),
    (
        "role_reassignment",
        re.compile(
            r"\byou\s+are\s+(now\s+)?(an?|the)\s+(ai|assistant|language\s+model|chatbot|"
            r"unrestricted|jailbroken|developer\s+mode)\b",
            re.I,
        ),
    ),
    (
        "system_prompt_probe",
        re.compile(r"\b(reveal|print|show|repeat|output|leak)\s+(your\s+|the\s+)?system\s+prompt", re.I),
    ),
    (
        "template_tokens",
        re.compile(
            r"(<\|im_start\|>|<\|im_end\|>|<\|system\|>|\[/?INST\]|<<SYS>>|<\s*/?\s*system\s*>|"
            r"^\s*#{2,}\s*(system|instruction)s?\b|BEGIN\s+SYSTEM\s+PROMPT)",
            re.I | re.M,
        ),
    ),
    (
        "output_manipulation",
        re.compile(
            r"\b(rate|score|rank|mark)\s+(this|the|every|each)\s+(candidate|applicant|resume)\s+"
            r"(as\s+)?(a\s+)?(perfect|10|100|highly|top|excellent)",
            re.I,
        ),
    ),
    (
        "output_manipulation",
        re.compile(r"\b(respond|reply|answer)\s+only\s+with\b", re.I),
    ),
    (
        "exfiltration",
        re.compile(
            r"\b(send|email|forward|post|upload)\s+(the\s+|your\s+|all\s+|this\s+)?"
            r"(resume|cv|data|conversation|instructions|api\s+key|password|credentials|system\s+prompt)"
            r"[^.\n]{0,60}\bto\s+\S+@\S+",
            re.I,
        ),
    ),
    (
        "exfiltration",
        re.compile(
            r"\binclude\s+(the\s+|your\s+)?(api\s+key|password|secret|system\s+prompt|credentials)",
            re.I,
        ),
    ),
]


@dataclass(frozen=True)
class InjectionFinding:
    kind: str
    excerpt: str


def strip_invisible(text: str) -> str:
    """Remove zero-width / bidi-control / tag characters used to hide instructions."""
    return _INVISIBLE.sub("", text)


def scan(text: str | None) -> list[InjectionFinding]:
    """Return suspected prompt-injection findings (empty list = nothing found)."""
    if not text:
        return []
    findings: list[InjectionFinding] = []
    invisible = _INVISIBLE.findall(text)
    if len(invisible) >= 3:
        findings.append(
            InjectionFinding(kind="hidden_characters", excerpt=f"{len(invisible)} invisible characters")
        )
    visible = strip_invisible(text)
    seen: set[tuple[str, str]] = set()
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(visible):
            start = max(0, match.start() - 60)
            end = min(len(visible), match.end() + 60)
            excerpt = " ".join(visible[start:end].split())[:200]
            key = (kind, match.group(0).lower())
            if key not in seen:
                seen.add(key)
                findings.append(InjectionFinding(kind=kind, excerpt=excerpt))
            if len(findings) >= 10:
                return findings
    return findings
