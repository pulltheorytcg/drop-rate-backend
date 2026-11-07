# Approved image pilot: runtime diagnosis

The first actual read-only invocation did not establish a successful Buffer connection. A Docker pre-deploy command beginning with shell-style NAME=value assignments failed before runner output. Prefix the explicit operator command with `env`, or use a correctly quoted shell; Docker exec invocation is not a shell. This changes no credential or permission.

The next check started the existing runner but returned its generic RUN_UNVERIFIED message. The runner now tracks CONFIG, IMPORT, EXECUTE and SUMMARY phases and converts known errors into a closed set of categories. The classifier never returns raw stdout/stderr, provider errors, URLs, request bodies, signatures, environment values or arbitrary error messages. Unknown errors stay generic. A diagnostic category is a hint, not evidence of a successful preflight or public delivery.

The normal startup, approved manifest, HMAC validation, publication journal and no-retry rules remain unchanged. The runner still imports the exact reviewed manual workflow into its own temporary SQLite database and never resets the persistent n8n volume. Its only external business operations remain the existing exact-manifest check/publish/status commands.

Tests execute the real classifier under Node with known and malicious-looking failure strings, and assert a fixed response schema and no echoed input. Existing actual n8n check/submit/status fixture tests continue to exercise the runner in an externally network-disabled container. No production credentials enter CI.

Operational sequence remains: deploy verified source; run check; inspect actual safe output; publish only when preflight passes and the exact revision hash is enabled; then reconcile delivery and repeated requests without reposting. An unknown outcome requires journal inspection before retry. Remove the temporary operator command and disable publication after the pilot. The previous healthy n8n deployment is retained if a pre-deploy check fails.

The application and workflow tests are distinct from real-model execution and live social delivery. This repair does not enable recurring jobs, add a new service/provider, edit media, change any database schema/RLS, or recreate the unrelated previously blocked broad probe/source-export helpers.
