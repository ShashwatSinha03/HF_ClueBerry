# Clueberry report: Discrepancy in status\_codes.py: 102 mapped to "early-hints" instead of 103

> **AI-assisted analysis.** A local model proposed the claims and verdicts. Clueberry checked that every cited file, line range and commit exists in the evidence it collected, but it cannot prove that a citation fully supports a claim. Review the evidence before acting on a verdict.

| | |
|---|---|
| Issue | [psf/requests#7611](https://github.com/psf/requests/issues/7611) |
| Repository | psf/requests |
| Commit inspected | `3c7baaa05ab4aa49cc819ce3a819d260de19c157` |
| Model | ollama/qwen3:4b |
| Generated | 2026-10-31 21:29 UTC by Clueberry 0.1.0 |

## Summary

5 claims assessed: 3 VERIFIED, 2 INCONCLUSIVE.

| Verdict | Claims |
|---|---|
| VERIFIED | 3 |
| PARTIALLY_VERIFIED | 0 |
| CONTRADICTED | 0 |
| INCONCLUSIVE | 2 |

## Claims

### C1: VERIFIED

**Claim:** The \`requests.codes\` module incorrectly maps the status code 102 to the string 'early-hints' instead of 103

**Quoted from the issue:**

> In \`src/requests/status\_codes.py\`, "early-hints" is currently associated with status code \`102\` rather than \`103\`

**Assessment:** Evidence E1 line 27 shows 102: \('processing', 'early-hints'\) confirming the claim that 'early-hints' is mapped to 102 \(not 103\).

**Evidence:**

- E1 (source): [src/requests/status\_codes.py:27](https://github.com/psf/requests/blob/3c7baaa05ab4aa49cc819ce3a819d260de19c157/src/requests/status_codes.py#L27-L27)

```
   27 |     102: ("processing", "early-hints"),
```

### C2: VERIFIED

**Claim:** The \`requests.codes.early\_hints\` attribute does not exist, causing an AttributeError when accessed

**Quoted from the issue:**

> requests.codes.early\_hints raises \`AttributeError: 'LookupDict' object has no attribute 'early\_hints'

**Assessment:** Evidence \[E2\] shows \`codes\` is a \`LookupDict\` \(a dictionary\), so \`early\_hints\` is not an attribute.

**Evidence:**

- E2 (source): [src/requests/status\_codes.py:106](https://github.com/psf/requests/blob/3c7baaa05ab4aa49cc819ce3a819d260de19c157/src/requests/status_codes.py#L106-L106)

```
  106 | codes: LookupDict[int] = LookupDict(name="status_codes")
```

### C3: VERIFIED

**Claim:** The \`requests.codes.get\("early-hints"\)\` method returns 102 instead of 103

**Quoted from the issue:**

> \`requests.codes.get\("early-hints"\)\` returns \`102\`

**Assessment:** Evidence \[E1\] line 27 shows 102 maps to 'early-hints'.

**Evidence:**

- E1 (source): [src/requests/status\_codes.py:27](https://github.com/psf/requests/blob/3c7baaa05ab4aa49cc819ce3a819d260de19c157/src/requests/status_codes.py#L27-L27)

```
   27 |     102: ("processing", "early-hints"),
```

### C4: INCONCLUSIVE

**Claim:** The RFC 9110 standard specifies that status code 102 should be mapped to 'processing' and 103 to 'early-hints'

**Quoted from the issue:**

> RFC 9110 §15.2.3 / RFC 2518

**Assessment:** Evidence only shows requests library's mappings, not RFC 9110 standard. Claim references RFC 9110 §15.2.3 but evidence lacks RFC 9110 content.

### C5: INCONCLUSIVE

**Claim:** The RFC 9110 standard specifies that status code 103 should be mapped to 'early-hints'

**Quoted from the issue:**

> RFC 9110 §15.2.4 / RFC 8297

**Assessment:** Evidence from requests library does not include RFC 9110 or RFC 8297; claim unverified.

## Evidence collection

- Files: 130 in tree, 121 eligible, 121 inspected
- Skipped: binary 5, oversized 2, symlink 2
- Evidence items collected: 9
- Search terms: status\_codes.py, status\_codes, src/requests/status\_codes.py, early-hints, requests.codes.early\_hints, requests.codes.processing, requests.codes.EARLY\_HINTS, Shaivarth:fix-rfc9110-status-codes, a2480570, requests.codes.get
- Limits reached: no

## Limitations

- Only the repository snapshot at the commit above was inspected; for pull requests this is the head commit, not the base-to-head diff.
- Validation proves each citation exists and shares a term with the claim, not that it supports the claim. Verdicts depend on the model and on the evidence Clueberry happened to collect.
- No repository code was executed.
