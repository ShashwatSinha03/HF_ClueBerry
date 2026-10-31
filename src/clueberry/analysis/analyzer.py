from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from clueberry.investigation.models import Evidence, InspectionResult

from .models import AnalysisLimits, AnalysisResult, Claim, ClaimAssessment
from .prompts import (
    ASSESSMENT_SCHEMA,
    EXTRACTION_SCHEMA,
    build_assessment_prompt,
    build_extraction_prompt,
)
from .provider import AnalysisError, ModelProvider, ModelResponseError, ModelTimeoutError
from .validation import (
    AssessmentOutput,
    ExtractionOutput,
    build_assessment,
    ground_claims,
    inconclusive,
    parse_model_json,
    verify_references,
)

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_STOPWORDS = frozenset(
    "the and for that this with from when not are was were has have but into its "
    "does should would could will can than then there their which what about".split()
)


def select_evidence(
    claim: Claim, evidence: Sequence[Evidence], limit: int
) -> list[tuple[str, Evidence]]:
    """Pick the evidence most lexically related to a claim, keeping original ids and order.

    Ids (E1, E2, ...) always refer to positions in the full inspection evidence
    list, so a citation means the same thing however the subset was chosen.
    """
    indexed = [(f"E{i}", item) for i, item in enumerate(evidence, start=1)]
    if len(indexed) <= limit:
        return indexed

    words = {w.lower() for w in _WORD_RE.findall(f"{claim.text} {claim.quote}")} - _STOPWORDS

    def score(item: Evidence) -> int:
        haystack = f"{item.path}\n{item.text}".lower()
        return sum(1 for word in words if word in haystack)

    ranked = sorted(range(len(indexed)), key=lambda i: (-score(indexed[i][1]), i))
    keep = sorted(ranked[:limit])
    return [indexed[i] for i in keep]


def analyze_claims(
    *,
    title: str,
    body: str,
    inspection: InspectionResult,
    provider: ModelProvider,
    extraction_provider: ModelProvider | None = None,
    kind: str = "issue",
    limits: AnalysisLimits | None = None,
    progress: Callable[[str], None] | None = None,
) -> AnalysisResult:
    """Extract claims from issue/PR text and assess each one against collected evidence.

    The model proposes claims, verdicts and citations; deterministic code decides
    what is accepted. `extraction_provider` (default: `provider`) lets claim
    extraction use different settings, e.g. thinking off. `progress` receives a
    short status message before each model call. Raises ModelUnavailableError
    if the model can't be used at all, and ModelResponseError/ModelTimeoutError
    if claim extraction fails. Per-claim timeouts or malformed answers yield
    INCONCLUSIVE for that claim.
    """
    limits = limits or AnalysisLimits()
    body = body or ""
    report = progress or (lambda message: None)

    report("Extracting claims")
    system, prompt = build_extraction_prompt(
        title, body, kind=kind, max_claims=limits.max_claims, max_input_chars=limits.max_input_chars
    )
    extraction = parse_model_json(
        (extraction_provider or provider).generate_json(system, prompt, EXTRACTION_SCHEMA),
        ExtractionOutput,
    )
    claims, rejected = ground_claims(
        extraction.claims,
        f"{title}\n\n{body[: limits.max_input_chars]}",
        max_claims=limits.max_claims,
        min_quote_chars=limits.min_quote_chars,
    )

    notes: list[str] = []
    if not claims:
        notes.append("No grounded technical claims were found in the issue/PR text.")
    if not inspection.evidence:
        notes.append("No evidence was collected from the repository.")

    assessments: list[ClaimAssessment] = []
    for number, claim in enumerate(claims, start=1):
        report(f"Assessing claim {number}/{len(claims)}")
        if not inspection.evidence:
            assessments.append(inconclusive(claim, "No evidence was collected to assess this."))
            continue

        selected = select_evidence(claim, inspection.evidence, limits.max_evidence_per_claim)
        system, prompt = build_assessment_prompt(
            claim,
            selected,
            commit_sha=inspection.commit_sha,
            max_evidence_chars=limits.max_evidence_chars,
        )
        try:
            output = parse_model_json(
                provider.generate_json(system, prompt, ASSESSMENT_SCHEMA), AssessmentOutput
            )
        except ModelTimeoutError as exc:
            assessments.append(inconclusive(claim, f"Model timed out on this claim: {exc}"))
            continue
        except ModelResponseError as exc:
            assessments.append(inconclusive(claim, f"Model output was unusable: {exc}"))
            continue

        assessments.append(
            build_assessment(
                claim,
                output,
                dict(selected),
                commit_sha=inspection.commit_sha,
                max_citations=limits.max_citations,
                max_explanation_chars=limits.max_explanation_chars,
            )
        )

    result = AnalysisResult(
        repository=inspection.repository,
        commit_sha=inspection.commit_sha,
        model=provider.name,
        assessments=assessments,
        rejected_claims=rejected,
        notes=notes,
    )
    problems = verify_references(result, inspection)
    if problems:  # an internal invariant; should be unreachable
        raise AnalysisError("Evidence reference check failed: " + "; ".join(problems))
    return result
