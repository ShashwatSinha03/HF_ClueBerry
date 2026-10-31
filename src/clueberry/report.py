"""Markdown investigation reports.

Everything that comes from GitHub, the repository or the model is untrusted:
inline text is backslash-escaped so it can't create links, images or HTML,
and code is placed in fences longer than any backtick run it contains.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from clueberry import __version__
from clueberry.analysis.models import AnalysisResult, EvidenceReference, Verdict
from clueberry.github.models import GitHubFetchResult
from clueberry.investigation.models import Evidence, InspectionResult

VERDICT_ORDER = (
    Verdict.VERIFIED,
    Verdict.PARTIALLY_VERIFIED,
    Verdict.CONTRADICTED,
    Verdict.INCONCLUSIVE,
)

_MD_SPECIAL_RE = re.compile(r"([\\`*_\[\]()<>!|#~])")
_BACKTICK_RUN_RE = re.compile(r"`+")


def md(text: str) -> str:
    """Escape untrusted text for inline Markdown (single line, no live syntax)."""
    return _MD_SPECIAL_RE.sub(r"\\\1", " ".join(text.split()))


def fence(code: str) -> str:
    longest = max((len(run) for run in _BACKTICK_RUN_RE.findall(code)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}\n{code}\n{ticks}"


def verdict_counts(result: AnalysisResult) -> Counter[Verdict]:
    return Counter(a.verdict for a in result.assessments)


def summary_line(result: AnalysisResult) -> str:
    total = len(result.assessments)
    if total == 0:
        text = "No grounded technical claims were assessed."
    else:
        counts = verdict_counts(result)
        parts = [f"{counts[v]} {v.value}" for v in VERDICT_ORDER if counts[v]]
        text = f"{total} claim{'s' if total != 1 else ''} assessed: {', '.join(parts)}."
    if result.rejected_claims:
        n = len(result.rejected_claims)
        text += f" {n} proposed claim{'s were' if n != 1 else ' was'} rejected as ungrounded."
    return text


def evidence_for(inspection: InspectionResult, ref: EvidenceReference) -> Evidence | None:
    index = int(ref.evidence_id[1:]) - 1 if ref.evidence_id[1:].isdigit() else -1
    if 0 <= index < len(inspection.evidence):
        return inspection.evidence[index]
    return None


def cited_lines(
    inspection: InspectionResult, ref: EvidenceReference
) -> list[tuple[int | None, str]]:
    """The exact cited lines (line number, text), or the full history text."""
    evidence = evidence_for(inspection, ref)
    if evidence is None:
        return []
    lines = evidence.text.split("\n")
    if evidence.start_line is None or ref.start_line is None or ref.end_line is None:
        return [(None, line) for line in lines]
    first = ref.start_line - evidence.start_line
    return [
        (ref.start_line + offset, line)
        for offset, line in enumerate(lines[first : first + ref.end_line - ref.start_line + 1])
    ]


def permalink(ref: EvidenceReference) -> str:
    url = f"https://github.com/{ref.repository}/blob/{ref.commit_sha}/{quote(ref.path, safe='/')}"
    if ref.start_line is not None:
        url += f"#L{ref.start_line}-L{ref.end_line}"
    return url


def issue_url(fetched: GitHubFetchResult) -> str:
    segment = "pull" if fetched.kind == "pull_request" else "issues"
    return f"https://github.com/{fetched.owner}/{fetched.repo}/{segment}/{fetched.issue.number}"


def render_markdown(
    *,
    fetched: GitHubFetchResult,
    inspection: InspectionResult,
    analysis: AnalysisResult,
    generated_at: datetime,
) -> str:
    kind = "Pull request" if fetched.kind == "pull_request" else "Issue"
    repo = f"{fetched.owner}/{fetched.repo}"
    out: list[str] = [
        f"# Clueberry report: {md(fetched.issue.title)}",
        "",
        "> **AI-assisted analysis.** A local model proposed the claims and verdicts. "
        "Clueberry checked that every cited file, line range and commit exists in the "
        "evidence it collected, but it cannot prove that a citation fully supports a "
        "claim. Review the evidence before acting on a verdict.",
        "",
        "| | |",
        "|---|---|",
        f"| {kind} | [{repo}#{fetched.issue.number}]({issue_url(fetched)}) |",
        f"| Repository | {repo} |",
        f"| Commit inspected | `{analysis.commit_sha}` |",
        f"| Model | {md(analysis.model)} |",
        f"| Generated | {generated_at:%Y-%m-%d %H:%M %Z} by Clueberry {__version__} |",
        "",
        "## Summary",
        "",
        summary_line(analysis),
        "",
        "| Verdict | Claims |",
        "|---|---|",
    ]
    counts = verdict_counts(analysis)
    out += [f"| {v.value} | {counts[v]} |" for v in VERDICT_ORDER]
    if analysis.notes:
        out.append("")
        out += [f"> {md(note)}" for note in analysis.notes]

    if analysis.assessments:
        out += ["", "## Claims"]
    for assessment in analysis.assessments:
        claim = assessment.claim
        out += [
            "",
            f"### {claim.id}: {assessment.verdict.value}",
            "",
            f"**Claim:** {md(claim.text)}",
            "",
            f"**Quoted from the {kind.lower()}:**",
            "",
            f"> {md(claim.quote)}",
            "",
            f"**Assessment:** {md(assessment.explanation)}",
        ]
        if assessment.model_verdict and assessment.model_verdict is not assessment.verdict:
            out += [
                "",
                f"*The model answered {assessment.model_verdict.value}; Clueberry's "
                f"validation changed it to {assessment.verdict.value}.*",
            ]
        if assessment.references:
            out += ["", "**Evidence:**"]
        for ref in assessment.references:
            label = md(ref.location)
            out += ["", f"- {ref.evidence_id} ({ref.category}): [{label}]({permalink(ref)})", ""]
            lines = cited_lines(inspection, ref)
            code = "\n".join(
                line if number is None else f"{number:>5} | {line}" for number, line in lines
            )
            out.append(fence(code))
        if assessment.validation_notes:
            out += ["", "**Validation notes:**", ""]
            out += [f"- {md(note)}" for note in assessment.validation_notes]

    if analysis.rejected_claims:
        out += ["", "## Rejected claims", ""]
        out += [
            f"- {md(rejected.text) or '(empty)'} ({md(rejected.reason)})"
            for rejected in analysis.rejected_claims
        ]

    skipped = ", ".join(f"{reason} {n}" for reason, n in inspection.skipped.items()) or "none"
    out += [
        "",
        "## Evidence collection",
        "",
        f"- Files: {inspection.files_in_tree} in tree, {inspection.files_eligible} eligible, "
        f"{inspection.files_inspected} inspected",
        f"- Skipped: {md(skipped)}",
        f"- Evidence items collected: {len(inspection.evidence)}",
        f"- Search terms: {md(', '.join(inspection.search_terms)) or 'none'}",
        f"- Limits reached: {'yes, results were truncated' if inspection.truncated else 'no'}",
        "",
        "## Limitations",
        "",
        "- Only the repository snapshot at the commit above was inspected; for pull "
        "requests this is the head commit, not the base-to-head diff.",
        "- Validation proves each citation exists and shares a term with the claim, "
        "not that it supports the claim. Verdicts depend on the model and on the evidence "
        "Clueberry happened to collect.",
        "- No repository code was executed.",
        "",
    ]
    return "\n".join(out)


def write_report(path: Path, content: str) -> None:
    """Write atomically: a partial report is never left behind, even if interrupted."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        # mkstemp creates the file 0600; give the report normal permissions.
        umask = os.umask(0)
        os.umask(umask)
        os.fchmod(fd, 0o666 & ~umask)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
