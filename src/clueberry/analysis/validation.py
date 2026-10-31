from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from clueberry.investigation.models import Evidence, InspectionResult

from .models import (
    AnalysisResult,
    Claim,
    ClaimAssessment,
    EvidenceReference,
    RejectedClaim,
    Verdict,
)
from .provider import ModelResponseError

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_HEX_RE = re.compile(r"^[0-9a-f]+$")

T = TypeVar("T", bound=BaseModel)


# --- what the model is allowed to say ----------------------------------------


class ExtractedClaim(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    quote: str


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claims: list[ExtractedClaim]


class Citation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    evidence_id: str
    path: str
    start_line: int | None = None
    end_line: int | None = None
    commit_sha: str | None = None


class AssessmentOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    verdict: Verdict
    explanation: str
    citations: list[Citation] = []

    @field_validator("verdict", mode="before")
    @classmethod
    def _normalize_verdict(cls, value: object) -> object:
        if isinstance(value, str):
            return re.sub(r"[\s-]+", "_", value.strip()).upper()
        return value


def parse_model_json(raw: str, model: type[T]) -> T:
    """Parse a model answer into `model`, tolerating think blocks and code fences."""
    text = _THINK_RE.sub("", raw)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ModelResponseError("model output contained no JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ModelResponseError(f"model output was not valid JSON ({exc.msg})") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "output"
        raise ModelResponseError(
            f"model JSON did not match the expected schema ({location}: {first['msg']})"
        ) from exc


# --- claims ---------------------------------------------------------------------


_QUOTE_MARKS = str.maketrans("", "", "'\"`‘’“”")


def _normalize(text: str) -> str:
    # Models often drop markdown backticks or swap quote styles when copying a
    # quote; the words themselves must still match exactly.
    return " ".join(text.translate(_QUOTE_MARKS).split()).casefold()


def ground_claims(
    extracted: Sequence[ExtractedClaim],
    source_text: str,
    *,
    max_claims: int,
    min_quote_chars: int,
) -> tuple[list[Claim], list[RejectedClaim]]:
    """Keep only claims whose quote really appears in the issue/PR text.

    This stops the model from inventing claims (including ones planted by a
    prompt-injection attempt in another part of the input).
    """
    source = _normalize(source_text)
    claims: list[Claim] = []
    rejected: list[RejectedClaim] = []
    seen: set[str] = set()

    for item in extracted:
        text, quote = item.text.strip()[:500], item.quote.strip()[:500]
        reason = None
        if not text:
            reason = "empty claim"
        elif len(_normalize(quote)) < min_quote_chars:
            reason = "quote too short to ground the claim"
        elif _normalize(quote) not in source:
            reason = "quote does not appear in the issue/PR text"
        elif _normalize(text) in seen:
            reason = "duplicate claim"
        elif len(claims) >= max_claims:
            reason = "over the claim limit"

        if reason:
            rejected.append(RejectedClaim(text=text, quote=quote, reason=reason))
            continue
        seen.add(_normalize(text))
        claims.append(Claim(id=f"C{len(claims) + 1}", text=text, quote=quote))
    return claims, rejected


# --- citations ------------------------------------------------------------------

_TERM_RE = re.compile(r"[A-Za-z0-9_]{3,}")
_STOPWORDS = frozenset(
    "the and for that this with from when not are was were has have but into its "
    "does should would could will can than then there their which what about also "
    "only instead".split()
)


def _terms(text: str) -> set[str]:
    return {t.lower() for t in _TERM_RE.findall(text)} - _STOPWORDS


def claim_terms(claim: Claim) -> frozenset[str]:
    return frozenset(_terms(f"{claim.text} {claim.quote}"))


def _cited_text(evidence: Evidence, start: int | None, end: int | None) -> str:
    if evidence.start_line is None or start is None or end is None:
        return evidence.text
    lines = evidence.text.split("\n")
    return "\n".join(lines[start - evidence.start_line : end - evidence.start_line + 1])


def validate_citation(
    citation: Citation,
    evidence_by_id: Mapping[str, Evidence],
    commit_sha: str,
    terms: frozenset[str] = frozenset(),
) -> EvidenceReference | str:
    """Return a checked reference, or a string describing why the citation is invalid.

    If `terms` (from the claim) are given, the cited lines must contain at least
    one of them as a whole word: a cheap guard against real-but-irrelevant
    citations. It can't prove relevance, only rule out the clearly unrelated.
    """
    eid = citation.evidence_id.strip()
    evidence = evidence_by_id.get(eid)
    if evidence is None:
        return f"{eid!r} is not an evidence item that was provided"
    if citation.path != evidence.path:
        return f"{eid}: cited path {citation.path!r} does not match {evidence.path!r}"
    if evidence.commit_sha != commit_sha:
        return f"{eid}: evidence commit {evidence.commit_sha} is not the inspected commit"
    if citation.commit_sha is not None:
        cited = citation.commit_sha.strip().lower()
        if len(cited) < 7 or not _HEX_RE.match(cited) or not commit_sha.startswith(cited):
            return f"{eid}: cited commit {citation.commit_sha!r} does not match {commit_sha}"

    if evidence.start_line is None or evidence.end_line is None:
        if citation.start_line is not None or citation.end_line is not None:
            return f"{eid}: history evidence has no line numbers to cite"
        start = end = None
    else:
        start = citation.start_line if citation.start_line is not None else citation.end_line
        end = citation.end_line if citation.end_line is not None else citation.start_line
        if start is None or end is None:
            start, end = evidence.start_line, evidence.end_line
        if not evidence.start_line <= start <= end <= evidence.end_line:
            return (
                f"{eid}: lines {start}-{end} are outside {evidence.path}:"
                f"{evidence.start_line}-{evidence.end_line}"
            )

    if terms and not terms & _terms(_cited_text(evidence, start, end)):
        return f"{eid}: cited lines share no terms with the claim"

    return EvidenceReference(
        evidence_id=eid,
        repository=evidence.repository,
        commit_sha=evidence.commit_sha,
        path=evidence.path,
        start_line=start,
        end_line=end,
        category=evidence.category,
    )


def build_assessment(
    claim: Claim,
    output: AssessmentOutput,
    evidence_by_id: Mapping[str, Evidence],
    *,
    commit_sha: str,
    max_citations: int,
    max_explanation_chars: int,
) -> ClaimAssessment:
    """Validate every citation and downgrade verdicts that end up unsupported."""
    references: list[EvidenceReference] = []
    notes: list[str] = []
    seen: set[tuple[str, int | None, int | None]] = set()
    terms = claim_terms(claim)

    for citation in output.citations[:max_citations]:
        checked = validate_citation(citation, evidence_by_id, commit_sha, terms)
        if isinstance(checked, str):
            notes.append(f"Rejected citation: {checked}")
            continue
        key = (checked.evidence_id, checked.start_line, checked.end_line)
        if key not in seen:
            seen.add(key)
            references.append(checked)
    if len(output.citations) > max_citations:
        notes.append(f"Only the first {max_citations} citations were considered.")

    verdict = output.verdict
    if verdict is not Verdict.INCONCLUSIVE and not references:
        notes.append(
            f"Downgraded {verdict.value} to INCONCLUSIVE: no valid evidence citation supports it."
        )
        verdict = Verdict.INCONCLUSIVE

    explanation = output.explanation.strip()[:max_explanation_chars] or "(no explanation given)"
    return ClaimAssessment(
        claim=claim,
        verdict=verdict,
        model_verdict=output.verdict,
        explanation=explanation,
        references=references,
        validation_notes=notes,
    )


def inconclusive(claim: Claim, note: str) -> ClaimAssessment:
    return ClaimAssessment(
        claim=claim,
        verdict=Verdict.INCONCLUSIVE,
        explanation=note,
        validation_notes=[note],
    )


def verify_references(result: AnalysisResult, inspection: InspectionResult) -> list[str]:
    """Independently re-check a finished result against the inspection's evidence.

    Every reference must point at a collected evidence item (by id, path and
    commit) with a line range inside it, and every non-INCONCLUSIVE verdict must
    have at least one reference. Returns a list of problems (empty if valid).
    """
    by_id = {f"E{i}": item for i, item in enumerate(inspection.evidence, start=1)}
    problems: list[str] = []
    if result.commit_sha != inspection.commit_sha:
        problems.append(f"result commit {result.commit_sha} != {inspection.commit_sha}")

    for assessment in result.assessments:
        cid = assessment.claim.id
        if assessment.verdict is not Verdict.INCONCLUSIVE and not assessment.references:
            problems.append(f"{cid}: {assessment.verdict.value} has no evidence reference")
        for ref in assessment.references:
            item = by_id.get(ref.evidence_id)
            if item is None:
                problems.append(f"{cid}: unknown evidence {ref.evidence_id}")
                continue
            if (ref.path, ref.commit_sha, ref.repository) != (
                item.path,
                item.commit_sha,
                item.repository,
            ):
                problems.append(f"{cid}: {ref.evidence_id} path/commit/repository mismatch")
            elif item.start_line is None or item.end_line is None:
                if ref.start_line is not None or ref.end_line is not None:
                    problems.append(f"{cid}: {ref.evidence_id} cites lines in history evidence")
            elif (
                ref.start_line is None
                or ref.end_line is None
                or not item.start_line <= ref.start_line <= ref.end_line <= item.end_line
            ):
                problems.append(f"{cid}: {ref.evidence_id} line range outside evidence")
    return problems
