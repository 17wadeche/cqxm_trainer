# Trainer / IT installation — version 0.6.0

## Update the existing installation

1. Close Chrome completely so the old background helper exits.
2. Extract this package and replace the files inside the **same existing GCH_Check_My_Work_App installation folder**, including `extension` and `procedures`.
3. Reopen Chrome. At `chrome://extensions`, reload **GCH Check my work**, then refresh the GCH page.
4. In **Documents & settings**, confirm **Background helper version: 0.6.0**. Connection settings must show Production, `gpt-5.6-terra` and `Authorization: Bearer`.
5. Click **Check my work** to generate a new review. Enter the working **Production API token** only if prompted. Remember protects it for the Windows account.

The extension ID and native registration remain valid when the installation folder is unchanged. If you move the folder, run Install-Windows.cmd again and load the extension from its new location. Remove any separate older extension copy. Keep the manifest key and native_config.json identity together.

The migration resets previous provider/model/auth/environment settings and clears their remembered token. Current version-scoped Production tokens survive restarts. Existing uploaded procedure revisions, downloaded Word files and source history remain in `%LOCALAPPDATA%\GCHCheckMyWork`. Do not delete that data folder during an upgrade.

## First installation

1. Extract the complete package into a permanent folder.
2. Run **Install-Windows.cmd** under the Windows account that will use the tool. Python 3.10+ and the approved Python package source are required. The script installs dependencies and registers a per-user Chrome native messaging helper.
3. Load the `extension` folder using your approved Chrome deployment process. For a permitted pilot, use `chrome://extensions` → Developer mode → Load unpacked. For trainee rollout, use managed distribution.
4. Open GCH and refresh it. The **Check my work** button appears at the top right.
5. Confirm the Downloads location under **Documents & settings**, then enter a Production token in the GCH panel.

Chrome starts the helper automatically. No separate app window, web server or pairing code is needed. API credentials are not included in this download.

Version 0.6.0 improves evidence selection and adds a second applicability verification without changing the working connection. Successfully remembered 0.5.1 Production credentials are preserved. The prior gateway response-name fix remains.

## Fixed connection

- Endpoint: `https://api.gpt.medtronic.com/providers/openai/v1/responses`
- Environment: Production
- Model: `gpt-5.6-terra`
- Header: `Authorization: Bearer <Production token>`

A stale panel or saved preference cannot select the previous environment, authentication style or model. An explicit model rejection stops setup; there is no automatic model substitution. The model ID and endpoint follow the user's reported working deployment and supplied screenshots.

Connection setup performs text and JSON probes containing no complaint documents. Document retrieval uses native Responses function calls when supported. Explicit unsupported-tool/format errors can use locally validated JSON plans/output through the same endpoint and model. Every source/citation and checklist check still applies. Native functions, structured output, encrypted reasoning continuation and `store: false` support must be confirmed in the target MDT-GPT environment. If the gateway rejects `store`, the app stops instead of silently removing that setting.

## Procedures and output

The six bundled procedure revisions load automatically: 027-P043 K, 027-WI185 R, 027-WI186 N, 027-WI188 M, 054-P044 L and 054-WI198 P. Existing uploaded copies take precedence. D00788856 and D00788854 are excluded from new reviews.

To replace a procedure, open **Documents & settings**, select the document ID, enter its approved revision and upload PDF, Word or text. The replacement is used in later reviews and survives updates. It does not alter completed review evidence.

Detailed Event Report is the default export, selected by exact row label and its SAP selection link; PESR is the fallback. The concise Word output includes all 13 review areas and up to five study priorities. Complete evidence and coverage remain saved locally. Initial/follow-up MDR linkage, source identity and citation validation remain required.

## Accuracy check for this update

Re-run the same saved training event; earlier Word reports do not change. Confirm the narrative cites the actual Event Description and the event-detail requirements, the GFE row considers the no-return rationale separately from missing information, and timing uses the selected instruction's complete table/aware-date rule with the recorded dates. Consultation should use the supplied Investigation Summary. Remaining Not assessable findings should identify a precise missing source or condition, not an appendix that is included.

The verification may extend run time. The report remains concise. It does not automatically mark every row Done properly, and absent attachments, local coding tools or genuinely applicable excluded instructions can still limit a judgment.

## Target-environment check

Use a saved training record and Medtronic-required network/security settings. Confirm the correct report downloads, the review completes with GPT-5.6-terra in Production, and the Word file appears in Downloads. Have the trainer check interpretations against the approved procedures. Confirm original pages and MDR version linkage in saved evidence for a detailed report with embedded forms.

The supplied working Production test does not establish every advanced gateway capability or this build's end-to-end behavior. Live GCH, MDT-GPT, Windows DPAPI and Zscaler are not accessible in the build environment. SAP layout changes, native print dialogs, blob-only PDF viewers or POST-only exports may require a capture adapter.

## Troubleshooting

- **401 / rejected token:** enter the Production token. Tokens do not belong in screenshots or support tickets.
- **403 / access denied:** ask IT or the MDT-GPT owner to inspect access to the Production endpoint and model.
- **Unknown model:** confirm the exact `gpt-5.6-terra` ID is enabled for this Production token. No catalog fallback runs.
- **DNS, certificate, timeout or secure-connection interruption:** the app identifies the category when available. Ask IT to investigate `api.gpt.medtronic.com:443` with the failure time and your Zscaler state. The tool does not change Zscaler, proxy rules or TLS verification.
- **Output limit:** the app retries the original turn with more output space, up to 16,384 tokens. Partial responses are discarded. Reasoning tokens may consume the Responses output allowance.
- **Input context limit:** the current conservative application budget is retained; explicit overflow retries a fresh smaller packet. Confirm the actual deployment context limit with the MDT-GPT owner before increasing it.
- **Citation/checklist validation:** the app allows one correction. If it still fails, the error identifies the affected check and field. No unverified report is accepted.

Tokens stay in helper memory or Windows DPAPI storage when Remember is selected. **Forget this account's API token** removes the saved copy. Word files and evidence remain local; follow your internal retention process. `GCH_DATA_DIR` and `GCH_DOWNLOADS_DIR` can set managed storage locations. Model and environment are fixed in this build.
