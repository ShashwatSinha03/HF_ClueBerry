from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from clueberry.investigation.models import EvidenceCategory


class Verdict(StrEnum):
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    CONTRADICTED = "CONTRADICTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class Claim(BaseModel):
    """A technical claim, grounded by a verbatim quote from the issue/PR text."""

    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    quote: str


class RejectedClaim(BaseModel):
    """A claim proposed by the model but dropped by deterministic checks."""

    model_config = ConfigDict(frozen=True)

    text: str
    quote: str
    reason: str


class EvidenceReference(BaseModel):
    """A citation that has been checked against a collected Evidence item.

    `repository`, `commit_sha`, `path` and `category` are copied from that
    evidence item; the line range was checked to lie inside it.
    """

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    repository: str
    commit_sha: str
    path: str
    start_line: int | None = None
    end_line: int | None = None
    category: EvidenceCategory

    @property
    def location(self) -> str:
        if self.start_line is None:
            return self.path
        if self.start_line == self.end_line:
            return f"{self.path}:{self.start_line}"
        return f"{self.path}:{self.start_line}-{self.end_line}"


class ClaimAssessment(BaseModel):
    claim: Claim
    verdict: Verdict
    model_verdict: Verdict | None = Field(
        default=None, description="What the model answered, before deterministic guardrails."
    )
    explanation: str
    references: list[EvidenceReference] = []
    validation_notes: list[str] = []


class AnalysisLimits(BaseModel):
    """Bounds on what is sent to, and accepted from, the model."""

    model_config = ConfigDict(frozen=True)

    max_claims: int = Field(default=8, gt=0)
    max_input_chars: int = Field(default=8_000, gt=0)
    max_evidence_per_claim: int = Field(default=12, gt=0)
    max_evidence_chars: int = Field(default=1_500, gt=0)
    max_citations: int = Field(default=10, gt=0)
    max_explanation_chars: int = Field(default=1_000, gt=0)
    min_quote_chars: int = Field(default=8, gt=0)


class AnalysisResult(BaseModel):
    repository: str
    commit_sha: str
    model: str
    assessments: list[ClaimAssessment]
    rejected_claims: list[RejectedClaim] = []
    notes: list[str] = []
