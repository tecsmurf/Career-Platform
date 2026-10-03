"""
Deterministic resume tailoring.

Tailoring here means *emphasis*, never invention:

* within each experience/project entry, bullet lines are re-ordered so the
  ones relevant to this posting come first (entries themselves keep their
  chronological order);
* the skills section is re-ordered so the skills this posting asks for lead;
* an optional one-line targeted summary is built only from the user's own
  headline and skills that appear in BOTH the resume and the posting.

No line is added that is not already the user's own words (except that
summary line, whose every term comes from the user's facts). Skills the
posting wants but the resume lacks are reported back as gaps for the user to
address truthfully — they are never inserted.
"""

from __future__ import annotations

import re

from app.services.apply.candidate import CandidateFacts, split_resume
from app.services.apply.schemas import JDAnalysis, TailoredResume
from app.services.apply.skills import find_skills

_BULLET = re.compile(r"^\s*(?:[-*•·▪◦●‣–]|\d{1,2}[.)])\s+")


def _relevance(line: str, required: set[str], preferred: set[str], resp_terms: set[str]) -> float:
    score = 0.0
    for hit in find_skills(line):
        if hit.name in required:
            score += 2.0
        elif hit.name in preferred:
            score += 1.0
    words = {w for w in re.findall(r"[a-z]{4,}", line.lower())}
    score += 0.25 * len(words & resp_terms)
    if re.search(r"\d", line):
        score += 0.25  # quantified achievements read stronger; content unchanged
    return score


def _reorder_bullets(lines: list[str], score_fn) -> tuple[list[str], int]:  # type: ignore[no-untyped-def]
    """Re-order each run of consecutive bullet lines by relevance (stable)."""
    out: list[str] = []
    moved = 0
    run: list[str] = []

    def flush() -> None:
        nonlocal moved
        if run:
            ranked = sorted(run, key=lambda ln: -score_fn(ln))  # sorted() is stable
            moved += sum(1 for a, b in zip(run, ranked, strict=True) if a != b)
            out.extend(ranked)
            run.clear()

    for line in lines:
        if _BULLET.match(line):
            run.append(line)
        else:
            flush()
            out.append(line)
    flush()
    return out, moved


def _reorder_skills_line(line: str, priority: list[str]) -> str:
    """Re-order a comma/pipe separated skills line; never adds or drops items."""
    sep = "," if line.count(",") >= line.count("|") else "|"
    prefix = ""
    body = line
    if ":" in line.split(sep)[0]:
        prefix, body = line.split(":", 1)
        prefix += ":"
    items = [i.strip() for i in body.split(sep) if i.strip()]
    if len(items) < 3:
        return line

    def rank(item: str) -> int:
        hits = [h.name for h in find_skills(item)]
        for idx, name in enumerate(priority):
            if name in hits:
                return idx
        return len(priority)

    ranked = sorted(items, key=rank)
    joiner = ", " if sep == "," else " | "
    return f"{prefix} {joiner.join(ranked)}".strip() if prefix else joiner.join(ranked)


def tailor_resume(facts: CandidateFacts, jd: JDAnalysis) -> TailoredResume:
    required = {s.name for s in jd.required_skills}
    preferred = {s.name for s in jd.preferred_skills}
    resp_terms = {w for r in jd.responsibilities for w in re.findall(r"[a-z]{4,}", r.lower())}
    priority = [s.name for s in jd.required_skills] + [s.name for s in jd.preferred_skills]

    def score_fn(line: str) -> float:
        return _relevance(line, required, preferred, resp_terms)

    changes: list[str] = []
    out_lines: list[str] = []
    sections = split_resume(facts.resume_text)
    have = facts.skill_names
    matched = [s for s in priority if s in have]

    summary_line = None
    if facts.headline and matched:
        summary_line = f"{facts.headline.strip()} — {', '.join(matched[:5])}"

    for section in sections:
        lines = list(section.lines)
        if section.kind in {"experience", "projects"}:
            lines, moved = _reorder_bullets(lines, score_fn)
            if moved:
                changes.append(
                    f"{section.heading or section.kind.title()}: moved the bullets most relevant to "
                    f"this role to the top of each entry ({moved} line(s) re-ordered, none changed)"
                )
        elif section.kind == "skills":
            new_lines = [_reorder_skills_line(ln, priority) if ln.strip() else ln for ln in lines]
            if new_lines != lines:
                changes.append("Skills: listed the skills this posting asks for first (same skills, new order)")
            lines = new_lines

        if section.heading:
            out_lines.append(section.heading)
        if section.kind == "header" and summary_line:
            out_lines.extend(lines_strip_trailing(lines))
            out_lines.append("")
            out_lines.append(summary_line)
            changes.append(
                "Added a one-line targeted summary built from your headline and the skills you "
                "share with this posting"
            )
            continue
        out_lines.extend(lines)

    text = "\n".join(out_lines).strip() + "\n"
    if not changes:
        changes.append("No changes needed — your resume already leads with the most relevant content")

    missing = [s for s in priority if s not in have]
    return TailoredResume(
        text=text[:40_000],
        changes=changes,
        emphasized_keywords=matched[:60],
        missing_keywords=missing[:60],
    )


def lines_strip_trailing(lines: list[str]) -> list[str]:
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    return out
