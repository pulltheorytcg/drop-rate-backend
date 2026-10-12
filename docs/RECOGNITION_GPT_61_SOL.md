# Recognition model upgrade — 12 October 2026

The founder explicitly requested GPT-6.1 Sol for the existing Drop Rate scanner. Target API model ID: `gpt-6.1-sol`.

## Scope and configuration

Set `TCG_RECOGNITION_MODEL=gpt-6.1-sol` on the **existing** `drop-rate-api-live` Railway service (`6aa92310-153f-4fc9-9e22-dc338282605b`) in project `9329767b-b092-495c-bf18-75cf69c28536`, production environment `6f00816c-b630-4d0b-bcc1-26ac71fa712d`. Do not change other services or shared marketing model configuration.

This is an explicit environment override using Settings.from_env, not a cosmetic badge rename. The repository fallback stays `gpt-5.6-sol` for rollback/other environments; production must have the override. The configured name is returned by `/api/v1/recognition/status` and used by the raw/sealed image adapter and graded-label adapter. Both use the Responses API, image input and strict Structured Outputs with `store: false`. No tools, automatic model fallback or premium service tier are added.

OpenAI's official model and migration documentation checked on 12 October:
- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://developers.openai.com/api/docs/guides/latest-model

GPT-6.1 Sol does not support `none` or `minimal` reasoning. Existing requests omit explicit reasoning and therefore use the provider default; this upgrade initially preserves their existing token budgets and 45-second timeouts. Verify actual response completion rather than assuming compatibility. A failed candidate probe must block promotion, not remove schema/identity checks or quietly relabel the old model.

## Release gate

1. Review this PR and run the existing backend/JavaScript checks, including the new **mocked** provider regression cases.
2. Append `PYTHONPATH=backend python backend/scripts/recognition_model_smoketest.py --expected-model gpt-6.1-sol` to the existing API service's pre-deploy command for this one upgrade only. Set the explicit model override without creating another service or extracting its API key. Preserve the existing pre-deploy checks.
3. The script makes exactly two real image requests through the existing production adapters, using a generated blank grey image only. Verify the API returns the requested model, completed strict output for both schemas, and no invented card/certificate. Print only model/timing/token metadata; never keys, headers, observations or customer photos. It does not call the database or certificate providers and does not save stock.
4. Record the exact deployment ID, model-receipt logs, checks and rollback state in the PR release comment. A successful server health check alone is not an inference test.
5. Restore the original pre-deploy command after verification so later unrelated releases do not make new paid recognition calls. Keep the model override. A new deployment is not needed just to restore this future-deploy command.

The test is an API/schema/no-object smoke test, **not** an exact-print accuracy benchmark, a comparative old/new model evaluation, or a signed-in physical-camera test. Report that boundary. No assertion of better card accuracy is made by this release.

## Preserved safeguards

No catalogue changes, source-image retention, owner/account merges, stock imports, confidence-threshold adjustments, physical condition/grade verification bypasses, financial writes, pricing algorithm changes or Shopify/eBay/Whatnot publication. The collection-first Confirm & add workflow remains. No new service or n8n workflow. The existing READY label means configured and is not continuous provider-health evidence.

## Rollback

On a failed pre-deploy probe, do not promote the candidate. Restore `TCG_RECOGNITION_MODEL=gpt-5.6-sol` and the previous pre-deploy command, leaving existing stock and database history untouched. If a deployed candidate subsequently fails, set that explicit previous model and redeploy the same tested application source. Do not mix old/new scan evidence: the existing recognition cache/runtime version includes the configured model.

This document records the approved plan; the final release comment distinguishes what actually passed and what remains unverified.
