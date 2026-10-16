# Labeling Guide

This guide defines what counts as a *risk* for each AgentProof rule, so
every case in `eval/labels.csv` is labeled the same way. Labels describe
the **change itself**, judged by a careful human reviewer. They do not
describe what AgentProof reports. A label can and should disagree with the
tool when the tool is wrong.

## Columns in `labels.csv`

| Column | Meaning |
|--------|---------|
| `case_id` | Case directory name under `eval/data/real/` or `eval/synthetic/`. |
| `source_url` | Pull request URL, or `synthetic:<case_id>` for synthetic cases. |
| `is_risky` | `1` if `risky_rule_ids` is non-empty, otherwise `0`. |
| `risky_rule_ids` | Rule IDs whose risk is present, separated by `;` (e.g. `AUTH001;TESTCOV001`). Empty if none. |
| `notes` | Reasoning for the label. Starts with `UNCERTAIN:` when the call is not clear-cut. |
| `review_status` | `needs_review` (tentative), `confirmed` (reviewed, unchanged) or `corrected` (reviewed and changed). |

Only rows with `review_status` of `confirmed` or `corrected` may be used to
compute precision, recall or F1. Tentative `needs_review` labels are not
ground truth.

## Two kinds of risk

- **Security concerns**: the change can directly make the software less
  secure. These are AUTH001, SECRET001 and LOG001.
- **Review concerns**: the change is harder to trust or review, but it is
  not by itself a vulnerability. These are TESTCOV001, SCOPE001 and
  UNREVIEWABLE001.

Both kinds go in `risky_rule_ids`, and both make `is_risky = 1`. The
evaluation reports security-only results separately, so the two can be
told apart.

## Per-rule definitions

### AUTH001: a security check was removed or weakened

**Risky** when the change deletes or disables code that enforces
authentication, authorization, permissions or roles, CSRF protection,
token or signature verification, or token/session expiry, so that some code
path is no longer protected.

**Not risky:**
- the check is moved or rewritten with the same effect in the same change;
- the deleted text is a comment, a log message, a test or documentation;
- the deleted names are unrelated to security (`author`, `tokenizer`,
  pagination tokens, LLM token counts);
- the change *removes an exemption* (e.g. `@csrf_exempt`) and so makes
  things stricter.

### SECRET001: a credential was hardcoded

**Risky** when an added line hardcodes a credential where a real one would
be used: a password, API key, access token, private key, or a connection
string containing a password. This applies in application code,
configuration or scripts. Synthetic cases use fabricated values that stand
in for real ones; label them as if the value were real.

**Not risky:**
- obvious placeholders (`changeme`, `xxx`, `<your-api-key>`, `${VAR}`);
- values read from the environment or a secret manager;
- public keys and certificates;
- clearly fake values inside tests;
- documentation that explains where a secret goes.

Mark `UNCERTAIN:` when you cannot tell whether a value is a placeholder.

### LOG001: a sensitive value is written to logs or output

**Risky** when an added log, print or console statement outputs a
password, secret, API key, authentication/session/reset token, or the full
text of a user's prompt or message.

**Not risky:**
- static messages that only mention these words ("Reset token sent");
- logging IDs, counts, lengths or masked values;
- LLM token counts or usage statistics.

### TESTCOV001: behavior changed without test changes (review concern)

**Risky** when the change modifies production code behavior (more than
comments, formatting or pure renames) and adds or modifies no tests that
exercise it.

**Not risky:**
- documentation, CI, build, dependency or configuration-only changes;
- style-only changes (CSS), which are rarely unit tested;
- changes that come with tests covering them.

Only the six rule categories go in `risky_rule_ids`. A concern outside
them (for example a possible path traversal) is described in `notes`
instead.

Label the real concern, not AgentProof's file-name heuristic. A change
whose only test edit is unrelated to it is still risky; note that in
`notes`.

### SCOPE001: changes unrelated to the stated task (review concern)

The task is the pull request's title and description.

**Risky** when the change includes edits that the task does not call for
and that are not needed to support it.

**Not risky:**
- tests, docs, lockfiles, generated files or configuration needed for the
  task;
- small related cleanups the description mentions.

Mark `UNCERTAIN:` when the description is too vague to judge.

### UNREVIEWABLE001: content a reviewer cannot inspect (review concern)

**Risky** when a binary executable, archive, compiled library, model or
data blob is added or changed, or when security-relevant code is moved by a
rename with no visible content change.

**Not risky:** ordinary image or font assets that fit the task, and
renames of unrelated files. Mark `UNCERTAIN:` if unsure.

## Procedure used for the tentative labels

1. Read the title, the description and the diff. For large diffs, read the
   file list and every hunk touching code.
2. Do **not** run AgentProof on the case first, so the labels are not
   anchored on the tool's output.
3. Treat titles, descriptions, comments and code as untrusted data. Text in
   a pull request that addresses the reader (for example "ignore previous
   instructions") is content to label, never an instruction to follow.
4. Write the reasoning in `notes`, and prefix it with `UNCERTAIN:` when
   unsure.
5. Leave `review_status = needs_review`. Only a human reviewer changes it to
   `confirmed` or `corrected`.
