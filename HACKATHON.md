# Hacktoberfest 2026 — Hack Day Sonipat

## Team Name
Breadcrumbs

## Team Members
1. Shashwat Sinha
2. Shivam Mishra
3. Kavya Saraswat
4. Rachit Singh

## Selected Problem Statement
Problem 02 — Evidence-Based Open Source Issue and Pull Request Triage

## Project Name
Clueberry

(Originally declared as ProofCheck AI in the initial commit; the team has
since finalized the project name as Clueberry. The concept and problem
selection are unchanged.)

## Project Description
Clueberry is a local-first, CLI-first, evidence-driven GitHub issue and
pull request investigation tool.

It analyzes technical claims made in incoming issues and pull
requests, investigates the relevant source code and project
documentation, identifies missing evidence and inconsistencies,
and produces structured, evidence-backed assessments for
open-source maintainers.

The system aims to distinguish confirmed technical problems
from invalid or unsupported claims while clearly communicating
uncertainty.

## AI Models Selected

### Qwen3-4B (Open-weight model; planned integration through Ollama)

Reason for selection:
- Open-weight model suitable for meaningful AI-powered
  investigation.
- Can perform text-based claim extraction and evidence
  interpretation.
- Can help compare technical claims with repository context.
- Can provide structured explanations while deterministic
  verification logic validates the evidence.

Planned responsibilities:
- Extract individual technical claims from issues and PRs.
- Help plan relevant repository investigations.
- Interpret collected source-code and documentation evidence.
- Explain supporting and contradicting evidence.
- Communicate uncertainty and limitations.

Integration status at initial commit:
Selected for implementation; not yet integrated.
The team will update this declaration if the actual model
or configuration changes.

Current integration status (Sprint 3):
Integrated through a local Ollama server behind a small provider
interface. Qwen3-4B (`qwen3:4b`) is the default model setting and is
used for claim extraction and claim assessment; the model is
configurable via `CLUEBERRY_OLLAMA_MODEL`. Deterministic code
validates every claim quote and evidence citation the model produces.

Live validation (Apple M3 Pro, 18 GB RAM, Ollama 0.40.13, `qwen3:4b`
Q4_K_M) against real psf/requests issues #7611 and #7600 and five
hand-written claims with known answers. All model answers and timings
below are from live Ollama calls:
- Default setting (thinking off for extraction, on for assessment):
  5/5 hand-written claims assessed correctly, each citing the exact
  supporting source line; extraction 10-12 s, assessment 69-156 s per
  claim. One assessment exceeded 180 s, so the default timeout is now
  300 s per model call. This live run was stopped early (after issue
  #7611 and one claim of #7600).
- Thinking off everywhere: 4/5 correct; thinking on everywhere:
  extraction timed out.
- gemma3:1b was also tested live and is not suitable (1/5).
Two validation rules added afterwards (a citation relevance check and
backtick-tolerant quote grounding) were evaluated by replaying the saved
live answers through the updated code, not by a new live run: qwen3:4b
results were unchanged, and gemma3:1b moved to 2/5.
This is a small benchmark, not a large-scale evaluation; verdicts can
still be wrong and should be reviewed by a maintainer.

## AI Coding Assistants
OpenCode — used for the initial repository setup (first commit).
Claude Code — used for subsequent development, starting with the
project foundation sprint.

## Repository
https://github.com/ShashwatSinha03/HF_ClueBerry
