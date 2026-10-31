from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import clueberry.report as report_module
import pytest
from clueberry.analysis import (
    AnalysisResult,
    Claim,
    ClaimAssessment,
    EvidenceReference,
    RejectedClaim,
    Verdict,
)
from clueberry.github.models import GitHubFetchResult, IssueDetails
from clueberry.investigation.models import Evidence
from clueberry.report import (
    cited_lines,
    fence,
    md,
    permalink,
    render_markdown,
    summary_line,
    write_report,
)
from test_analysis import BODY, REPO, SHA, TITLE, _inspection

WHEN = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _fetched(title: str = TITLE) -> GitHubFetchResult:
    return GitHubFetchResult(
        kind="issue",
        owner="psf",
        repo="requests",
        issue=IssueDetails(
            number=7611,
            title=title,
            state="open",
            body=BODY,
            html_url="https://github.com/psf/requests/issues/7611",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ),
    )


def _ref(start: int | None = 27, end: int | None = 27, eid: str = "E1") -> EvidenceReference:
    path = "src/requests/status_codes.py"
    category = "history" if start is None else "source"
    return EvidenceReference(
        evidence_id=eid,
        repository=REPO,
        commit_sha=SHA,
        path=path,
        start_line=start,
        end_line=end,
        category=category,
    )


def _analysis(*assessments: ClaimAssessment, **kwargs: object) -> AnalysisResult:
    return AnalysisResult(
        repository=REPO,
        commit_sha=SHA,
        model="ollama/qwen3:4b",
        assessments=list(assessments),
        **kwargs,
    )


def _assessment(
    verdict: Verdict,
    *refs: EvidenceReference,
    text: str = "Status code 102 is mapped to early-hints",
    model_verdict: Verdict | None = None,
    notes: list[str] | None = None,
) -> ClaimAssessment:
    return ClaimAssessment(
        claim=Claim(id="C1", text=text, quote="status code 102 is mapped to early-hints"),
        verdict=verdict,
        model_verdict=model_verdict or verdict,
        explanation="Line 27 maps 102 to early-hints.",
        references=list(refs),
        validation_notes=notes or [],
    )


def _render(analysis: AnalysisResult, fetched: GitHubFetchResult | None = None) -> str:
    return render_markdown(
        fetched=fetched or _fetched(),
        inspection=_inspection(),
        analysis=analysis,
        generated_at=WHEN,
    )


def test_report_contains_header_summary_claims_and_traceable_evidence() -> None:
    text = _render(
        _analysis(
            _assessment(Verdict.VERIFIED, _ref()),
            rejected_claims=[
                RejectedClaim(text="Invented", quote="not in text", reason="quote does not appear")
            ],
        )
    )

    assert text.startswith("# Clueberry report: Discrepancy in status\\_codes.py")
    assert "**AI-assisted analysis.**" in text
    assert "| Issue | [psf/requests#7611](https://github.com/psf/requests/issues/7611) |" in text
    assert f"| Commit inspected | `{SHA}` |" in text
    assert "| Generated | 2026-11-01 12:00 UTC by Clueberry" in text
    assert "1 claim assessed: 1 VERIFIED. 1 proposed claim was rejected as ungrounded." in text
    assert "| VERIFIED | 1 |" in text and "| CONTRADICTED | 0 |" in text
    assert "### C1: VERIFIED" in text
    assert (
        f"[src/requests/status\\_codes.py:27](https://github.com/psf/requests/blob/{SHA}"
        "/src/requests/status_codes.py#L27-L27)"
    ) in text
    assert '   27 |     102: ("processing", "early-hints"),' in text
    assert "## Rejected claims" in text and "- Invented (quote does not appear)" in text
    assert "- Files: 10 in tree, 8 eligible, 8 inspected" in text
    assert "## Limitations" in text


def test_report_explains_downgrades_and_validation_notes() -> None:
    text = _render(
        _analysis(
            _assessment(
                Verdict.INCONCLUSIVE,
                model_verdict=Verdict.VERIFIED,
                notes=["Rejected citation: 'E99' is not an evidence item that was provided"],
            )
        )
    )
    assert (
        "*The model answered VERIFIED; Clueberry's validation changed it to INCONCLUSIVE.*" in text
    )
    assert "- Rejected citation: 'E99' is not an evidence item that was provided" in text
    assert "**Evidence:**" not in text


def test_report_with_no_claims() -> None:
    text = _render(_analysis(notes=["No grounded technical claims were found."]))
    assert "No grounded technical claims were assessed." in text
    assert "> No grounded technical claims were found." in text
    assert "## Claims" not in text


def test_untrusted_text_cannot_inject_markdown_or_html() -> None:
    hostile = (
        "![pixel](https://evil.example/p.png) <img src=x onerror=alert(1)> "
        "[click](javascript:alert(1)) <script>x</script> | table | # heading"
    )
    text = _render(
        _analysis(_assessment(Verdict.VERIFIED, _ref(), text=hostile)),
        fetched=_fetched(title=hostile),
    )
    assert "![pixel](" not in text
    assert "[click](javascript" not in text
    assert not re.search(r"(?<!\\)<(img|script)", text)
    assert "\\!\\[pixel\\]\\(https://evil.example/p.png\\)" in text


def test_code_fence_is_longer_than_any_backtick_run() -> None:
    assert fence("plain") == "```\nplain\n```"
    assert fence("a ```` b").startswith("`````\n")
    assert fence("x").endswith("\n```")


def test_md_collapses_newlines() -> None:
    assert md("line one\n\n# not a heading") == "line one \\# not a heading"


def test_permalink_encodes_paths_and_omits_lines_for_history() -> None:
    ref = _ref().model_copy(update={"path": "docs/my file.md"})
    assert permalink(ref).endswith("/docs/my%20file.md#L27-L27")
    assert "#L" not in permalink(_ref(None, None, eid="E3"))


def test_cited_lines_slice_exact_range_and_history() -> None:
    assert cited_lines(_inspection(), _ref(27, 28)) == [
        (27, '    102: ("processing", "early-hints"),'),
        (28, '    103: ("checkpoint",),'),
    ]
    history = cited_lines(_inspection(), _ref(None, None, eid="E3"))
    assert history[0][0] is None and "Add status codes" in history[0][1]
    assert cited_lines(_inspection(), _ref(eid="E99")) == []


def test_summary_line_grammar() -> None:
    two = _analysis(
        _assessment(Verdict.VERIFIED, _ref()), _assessment(Verdict.CONTRADICTED, _ref())
    )
    assert summary_line(two) == "2 claims assessed: 1 VERIFIED, 1 CONTRADICTED."


def test_write_report_is_atomic_and_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "report.md"
    write_report(target, "first")
    write_report(target, "second")
    assert target.read_text() == "second"
    assert [p.name for p in tmp_path.iterdir()] == ["report.md"]


def test_written_report_has_normal_permissions(tmp_path: Path) -> None:
    import os
    import stat

    umask = os.umask(0o022)
    try:
        target = tmp_path / "report.md"
        write_report(target, "content")
        assert stat.S_IMODE(target.stat().st_mode) == 0o644
    finally:
        os.umask(umask)


def test_failed_write_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "report.md"
    target.write_text("previous report")

    def broken_replace(src: str, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(report_module.os, "replace", broken_replace)
    with pytest.raises(OSError):
        write_report(target, "new content")
    assert target.read_text() == "previous report"
    assert [p.name for p in tmp_path.iterdir()] == ["report.md"]


def test_evidence_text_with_backticks_stays_inside_its_fence() -> None:
    inspection = _inspection(
        [
            Evidence(
                repository=REPO,
                commit_sha=SHA,
                path="README.md",
                start_line=1,
                end_line=2,
                text="```\n# Injected heading",
                category="documentation",
                reason="r",
            )
        ]
    )
    ref = EvidenceReference(
        evidence_id="E1",
        repository=REPO,
        commit_sha=SHA,
        path="README.md",
        start_line=1,
        end_line=2,
        category="documentation",
    )
    text = render_markdown(
        fetched=_fetched(),
        inspection=inspection,
        analysis=_analysis(_assessment(Verdict.VERIFIED, ref)),
        generated_at=WHEN,
    )
    assert "````\n    1 | ```\n    2 | # Injected heading\n````" in text
