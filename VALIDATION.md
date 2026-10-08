# Validation record — 30 September 2026 — v0.6.0

## Evidence accuracy regression scope in 0.6.0

The attached Detailed Event Report and Word review were inspected locally to reproduce omitted governing sections, retained-device/no-return context and timing rules. An offline packet capture with mocked responses verified that the revised selection supplies complete governing sections for every check on this export. Reportability/timing split into separate packets instead of omitting Appendix C. Narrative, GFE, consultation and timing received the relevant record fields; the observed July 25 to August 14 interval is 20 calendar days. No complaint data was sent to a provider in this build environment, and no regenerated model assessment for this event is claimed.

Thirteen new regression checks use synthetic records, mocked model responses and bundled procedure text. They cover narrative/appendix coverage, GFE completion alternatives and retained status, timeline continuation/aware definitions/date calculation, consultation investigation routing, moved pages/renumbered headings, prose-reference exclusion, falsely missing-section assertions, legitimate missing facts, ambiguous multi-report date rejection, immutable quotations, splitting before a provider call, and mandatory verification without forcing favorable labels.

The source availability guard detects specific missing-section assertions; it is not a general factual entailment validator. The second model pass can also make mistakes. Clinical/regulatory accuracy still requires review against the applicable controlled sources. The bundled PDFs and extracted source digests are unchanged; local replacement revisions retain precedence. The Word renderer and its concise length targets remain unchanged.

Commands for this release: `python -m unittest discover -s tests -q` and `node --test tests/test_extension.mjs tests/test_background.mjs`. Final result: **130 Python tests and 34 JavaScript tests passed (164 total)**. The complete mocked run on the supplied export returned all 13 findings in nine packets; all governing sections were supplied and every packet received verification. The Word render was suppressed for that export-specific capture to avoid presenting mocked assessments as a new review. The standard suite still exercises Word generation.


**Result: 117 Python tests and 34 JavaScript tests passed (151 total).** Extension identity, UI element references and all original bundled procedure bytes were also verified.

Version 0.5.1 regression tests reproduce the returned-name mismatch, complete connection probes and a full 13-area review with a different reported deployment name, and verify every wire request remains `gpt-5.6-terra`. Saved context metadata and evidence preserve requested/reported names. Malformed or credential-containing model metadata is rejected without echoing it. No live alias mapping has been independently verified.

## Changed and checked locally

The app now fixes Production, OpenAI Responses, `gpt-5.6-terra` and Bearer authentication throughout configuration, native helper, Chrome token flow and optional manual utility. The endpoint and basic wire format match the supplied MDT-GPT screenshots. The model ID is the user's reported working selection.

Automated tests use synthetic records, mocked Responses HTTP results and mocked Chrome APIs. The six bundled procedure PDFs are read locally for extraction/digest checks and are never sent to a live provider during tests.

- Actual HTTP request construction uses only the Production `/providers/openai/v1/responses` URL, exact model, Bearer header, `input`, `max_output_tokens` and `store: false`. No Anthropic headers, request fields, model lookup or token-count endpoint remains active.
- Both documented reduced MDT envelopes and native Responses envelopes are parsed. Usage aliases are handled. Refusals, explicit incomplete/failed responses, malformed calls and unsupported output types are rejected. Reported deployment names are retained independently of the fixed outgoing model ID.
- Native tool continuation preserves full reasoning/function-call output before matching call results. Explicit unsupported tool parameters use a bounded JSON retrieval plan; unknown tools are rejected. Explicit unsupported `text.format` can use schema-in-prompt output, still checked locally. Invalid schemas, unexplained errors and access denial do not trigger compatibility retries.
- Full synthetic reviews generate all 13 findings through both native Responses and the text-only compatibility path. Tests verify complete Word output, original evidence insertion, correction of invalid fields, recovery from explicit output truncation, and no report after refusals or fabricated citations.
- Upgrade tests reset earlier environment/provider/model/header settings, clear unscoped credentials, preserve the Downloads path, complete interrupted credential migration, and retain current scoped Production credentials. Stale native/manual/extension requests cannot choose the earlier environment or model.
- Existing tests retain DER/PESR event matching, zero-padded identifiers, exact SAP report row selection, linked initial/follow-up MDR source views, retrieval coverage, context guards, six bundled procedure digests, replacement persistence, excluded documents and concise Word formatting.
- Network diagnostics classify exposed DNS, certificate, timeout and secure-connection errors without echoing credentials, source text or raw network error bodies. Redirects cannot forward credentials.

The source package includes the test suite and commands in README.md. Old model-catalog and provider token-count tests were replaced with tests for the new fixed model and complete Responses payload estimates.

## Preserved behavior

The floating button still selects Print → Detailed Event Report, using PESR when the detailed choice is unavailable. Correct-record validation, bounded source access, six default procedures, user procedure replacements, evidence validation and the concise Word layout remain. The Chrome extension key and ID are unchanged.

The local context estimate covers the complete request, including tools, schema and replayed output. The 128,000 application allowance is retained conservatively; this does not verify the internal deployment's actual context size. Returned usage only increases estimate calibration. Explicit input overflow can restart a batch with smaller fresh evidence.

## Limits of validation

No live request to Medtronic was made in this build environment. The user's successful Production/model test confirms their tested request, not every advanced gateway capability or the complete upgraded review. Gateway handling of tools, strict JSON, encrypted reasoning continuation, `store: false`, latency and actual context allowance still needs the target-environment run. Python tests simulate network responses; Chrome tests simulate browser APIs. Windows registration/DPAPI and live GCH/Zscaler are not available here.

The Word layout is unchanged; existing rendering/long-feedback tests continue to check content preservation. The new checks validate evidence coverage and bounded processing, not clinical or procedural correctness. Page count depends on model output, and the trainer must verify findings against the applicable documents.

## Acceptance run

Follow INSTALL_FOR_TRAINER.md to replace files in the same installation folder, reload Chrome's extension and refresh GCH. Confirm helper 0.6.0, Production and gpt-5.6-terra. Enter the Production token once. With Medtronic-required security settings, check a saved training record, confirm the correct export and Word file, and review its findings/citations with the trainer. Confirm uploaded procedure replacements remain active. If a connection or capability fails, share its redacted error and timestamp with the MDT-GPT/IT owner.
