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

## AI Coding Assistants
OpenCode — used for the initial repository setup (first commit).
Claude Code — used for subsequent development, starting with the
project foundation sprint.

## Repository
https://github.com/ShashwatSinha03/HF_ClueBerry
