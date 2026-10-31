# Examples

Real Clueberry runs against public GitHub data. The files in each folder are
the **actual, unedited output** of the command shown. Nothing was rewritten
or filtered.

## `requests-7611/` — psf/requests issue #7611

Issue: [psf/requests#7611](https://github.com/psf/requests/issues/7611),
"Discrepancy in status_codes.py: 102 mapped to "early-hints" instead of 103".

Command:

```bash
COLUMNS=100 clueberry analyze https://github.com/psf/requests/issues/7611 \
  --output examples/requests-7611/report.md \
  > examples/requests-7611/terminal-output.txt
```

- [`terminal-output.txt`](requests-7611/terminal-output.txt): what the
  command printed. It has no colors because output was redirected.
- [`report.md`](requests-7611/report.md): the Markdown report it wrote.

Run details:

| | |
|---|---|
| Commit inspected | `3c7baaa05ab4aa49cc819ce3a819d260de19c157` (default branch `HEAD` at run time) |
| Model | `qwen3:4b` (Q4_K_M) via Ollama 0.40.13, default Clueberry settings |
| Hardware | Apple M3 Pro, 18 GB RAM |
| Wall time | 7 min 5 s, exit code 0 |
| Evidence | 130 files in tree, 121 inspected, 9 evidence items |

How the verdicts compare with the source code at that commit (checked by
hand):

| Claim | Clueberry verdict | Assessment |
|---|---|---|
| C1: 102 is mapped to "early-hints" instead of 103 | `VERIFIED`, cites `status_codes.py:27` | Correct; cites the exact line. |
| C2: `requests.codes.early_hints` doesn't exist | `VERIFIED`, cites `status_codes.py:106` | Verdict correct, but the reasoning is weak. The real cause is the alias loop at lines 110–114, which only registers the hyphenated name; those lines were not among the collected evidence. |
| C3: `requests.codes.get("early-hints")` returns 102 | `VERIFIED`, cites `status_codes.py:27` | Correct. |
| C4, C5: what RFC 9110 specifies for 102/103 | `INCONCLUSIVE` | Correct: the RFC text isn't in the repository, so it can't be checked from code. |

This shows Clueberry's main limitation honestly: every citation is a real
line at the inspected commit, but whether it fully supports the claim still
needs a human to read it (C2).

### Reproducing

Run the command above with Ollama and `qwen3:4b` installed. Issues are
inspected at the repository's current default-branch `HEAD`, so a later run
may inspect a newer commit and produce different evidence or verdicts. Model
output can also vary slightly between runs and machines. The report always
records the exact commit that was inspected.
