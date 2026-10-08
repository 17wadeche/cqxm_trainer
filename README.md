# GCH Check my work — version 0.6.0

A floating button at the top right of GCH. Click **Check my work**, enter an MDT-GPT token if prompted, and open the concise Word training review when it is ready. Report selection, download, source retrieval and review run in the background.

- Trainees: QUICK_START.md.
- Trainer / IT installer: INSTALL_FOR_TRAINER.md.
- Test scope and remaining live verification: VALIDATION.md.

## Evidence accuracy improvements in 0.6.0

The model now receives governing procedure processes/appendices and decisive record pages before broad search. Narrative reads Event Description text info; GFE gets the retained-device/no-return fields plus the instruction's completion alternatives; timing gets the complete reporting table, awareness definitions and recorded report dates; consultation includes the investigation. Headings and fields locate evidence rather than fixed PDF pages. Procedure title matching also tolerates changed section numbers/appendix letters.

Combined checks split before an API call when their governing evidence would crowd the packet. Complete original source chunks remain the citation basis; model text removes excess PDF indentation while preserving line breaks and column separators. This keeps the concise report and the existing context ceiling.

Every draft receives a second evidence/applicability verification. It distinguishes information GFE, product return and requested customer response, checks the actual trigger for follow-up or late-report evaluation, and preserves supported observations when a supporting source is missing. Availability validation rejects concrete claims that a fully supplied section/appendix was missing. This does not prove clinical or regulatory correctness and does not force positive assessments.

For unambiguous complete regulatory-report pages, the helper supplies observed aware-to-submission calendar intervals and comparisons to the displayed due date. These calculations do not choose the governing clock rule or declare timeliness. Ambiguous date sets are left to explicit retrieval/date-tool use.

The added verification uses another model turn per evidence packet, so reviews may take longer and use more tokens. Production, `gpt-5.6-terra`, authentication, Chrome identity, saved tokens and procedure replacements remain as in 0.5.1.

## Production and GPT-5.6-terra

Version 0.5.1 fixes setup rejecting a successful response when MDT-GPT returns a deployment name different from the request alias. Every request still sends `gpt-5.6-terra`. The returned names are recorded per request in `context_usage.json` and alongside the requested ID in review evidence when they differ. The application does not assert that string differences prove a substituted model; the gateway owner controls alias routing. No returned name is copied into a later request.

The app retains the user-selected working deployment:

| Setting | Fixed value |
| --- | --- |
| Environment | Production |
| Provider | OpenAI Responses through MDT-GPT |
| Endpoint | `https://api.gpt.medtronic.com/providers/openai/v1/responses` |
| Model | `gpt-5.6-terra` |
| Authentication | `Authorization: Bearer <Production API token>` |

This is a Responses adapter, not just a model-name change. It sends `input` and `max_output_tokens` and reads `output[].content[].text`. It accepts the reduced output envelope and prompt/completion usage fields in the supplied MDT-GPT documentation, as well as native Responses status and input/output usage fields. Explicit incomplete, failed, refused and unexpected responses are rejected. Every outgoing request keeps the exact configured model ID; there is no model discovery, public-provider call or alternate environment fallback.

Saved settings migrate automatically. Old model/auth/environment preferences reset to the values above. A token from an earlier provider/environment or unscoped settings is cleared, and the GCH panel asks once for a Production token. Current version-scoped Production credentials remain saved. Uploaded procedure revisions, downloaded reports and source history remain intact. The extension ID stays `nlpgdigncphphoodneedoalppaeedapa`.

Connection setup checks a synthetic text response followed by a JSON response. Tokens remain in the native helper, optionally protected by Windows DPAPI. They are not saved in the extension, plaintext preferences or review evidence. TLS verification and corporate network settings remain enabled. Requests cannot follow redirects with credentials. Network failures identify DNS, certificate, timeout or secure-connection interruption when Python exposes that category; they do not claim which Zscaler policy failed.

## Retrieval and gateway compatibility

Native Responses function calls use the existing read-only document and date tools. Full output items, including reasoning items, are passed back before matching `function_call_output` items. Native tool requests ask for encrypted reasoning content for stateless continuation. Requests set `store: false`; they do not use server-side response IDs to retrieve conversation state. MDT-GPT's own retention policy still applies.

The supplied MDT-GPT screenshots document only basic Responses parameters. Advanced capabilities have not been verified on the live gateway here. If the gateway explicitly rejects native `tools`, `tool_choice` or `include`, the adapter falls back once to a JSON retrieval plan in the documented text input. The same limited local tools execute it; unknown tools, malformed plans and more than eight calls are rejected. If it explicitly rejects `text.format`, final output uses schema instructions and the existing strict local validation. These fallbacks never change model, host, credentials, TLS verification or the `store: false` setting. Invalid schemas, unexplained failures, access denials and refusals are not compatibility triggers.

Output schema, checklist coverage, record identity and source citations are validated before any report is accepted. A model-generated assertion is not a substitute for source evidence. Draft and verification findings each get one structured correction opportunity. Explicit output truncation can retry the original turn at a larger output allowance; partial text and calls are discarded. Each review has a bounded engine-call budget, with at most two additional capability-fallback requests per adapter turn.

## Report selection and context

GCH Print selects **Detailed Event Report**, using the blank SAP row selector next to the exact label. Product Event Summary Report is the fallback when the detailed option is unavailable. Duplicate matches stop automation. Downloads are checked against the selected event ID.

The helper extracts a heading-based outline with original PDF pages and source hashes. Review batches receive relevant sections and procedure excerpts; additional sections remain available through bounded search and continuation tools. Coverage metadata distinguishes supplied sections from partial or unrequested sections. Embedded initial/follow-up MDR forms remain separate linked source views. Cross-record consistency requires evidence from both the event record and the MDR.

The existing **128,000-token application budget** remains a conservative configuration, not a verified statement of GPT-5.6-terra's deployment limit. Target input is approximately 60,000 estimated tokens, with a 96,000 ceiling, output reservation and 8,192 tokens of headroom. The complete Responses payload is estimated locally and calibrated upward by reported usage. The old provider's token-count endpoint is no longer called. Explicit input-context errors restart a batch with a fresh smaller packet, at most twice. A lower actual deployment limit may require reducing these values after confirmation by the MDT-GPT owner.

The short Word format remains the default: all 13 review areas and up to five study priorities, with brief procedure references and material uncertainty. Page count is not forced. Full findings, source excerpts and coverage are saved locally in `review.json`, `evidence.json`, `retrieval_coverage.json` and `context_usage.json`.

The optional detailed format can be rendered from a completed review without another model call:

```bash
python render_report.py --review path/to/review.json --evidence path/to/evidence.json --output detailed.docx --detailed
```

## Included procedures

The six supplied defaults load automatically: 027-P043 K, 027-WI185 R, 027-WI186 N, 027-WI188 M, 054-P044 L and 054-WI198 P. Original PDFs and checked, page-located extraction files are bundled. These are baseline copies, not a live controlled-document subscription. **Documents & settings** allows approved replacements, which survive upgrades. D00788856 and D00788854 remain excluded from new reviews. Historical source snapshots are preserved.

## Package and tests

`extension/` provides the floating GCH panel and automation. `native_host.py` is the background helper started by Chrome. `app.py`, `web/` and `start.sh` retain a manual review utility; the extension uses native messaging, not its old pairing flow. `procedures/` contains the six baseline documents. `examples/` contains clearly marked synthetic demonstrations.

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
node --test tests/test_extension.mjs tests/test_background.mjs
```

Python 3.10+ is required. Node is only needed for developer tests. Native messaging pins the extension origin and allows specific setup/review commands, not arbitrary commands or paths to open. The source package contains no API secrets.

## References

The Production endpoint, Bearer header and reduced Responses envelope come from the user's MDT-GPT screenshots dated September 30, 2026. The exact model ID is the user's reported working ID; public OpenAI model names or limits do not establish its internal deployment properties.

- https://developers.openai.com/api/docs/guides/function-calling
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://developers.openai.com/api/docs/guides/reasoning
- https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging
- https://developer.chrome.com/docs/extensions/reference/manifest/key
- https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
