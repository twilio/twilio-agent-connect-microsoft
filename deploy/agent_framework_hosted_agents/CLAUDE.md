# CLAUDE.md — TAC Hosted Agents (Foundry) deployment

Deploys TAC + Agent Framework to **Hosted Agents in Foundry Agent Service**,
fronted by APIM. **For deployment steps, see [README.md](./README.md)** — the
entry point is `make deploy` (interactive, or pre-fill `.env`).

This file is maintainer/agent-facing: the non-obvious facts to know before
changing anything here, so they don't have to be rediscovered.

## Layout

- `deploy.sh` — the real entry point (`make deploy` runs it). Interactive
  bootstrap → provision (with retry) → wire agent env → push agent → offer
  Twilio config.
- `configure_twilio.sh` — points the Twilio number Voice URL + CO config
  webhook at this deployment (`make configure-twilio`).
- `Makefile` — `deploy` / `agent` / `urls` / `configure-twilio` / `down`.
- `infra/main.bicep` — APIM + Key Vault + APIs/policies + (optionally) the
  Foundry module + the APIM→Foundry role grant.
- `infra/foundry.bicep` — fresh Foundry account + project + model + ACR
  (created when `createFoundry=true`, the default).
- `infra/policies/*.xml` — APIM policies (sms / voice-twiml / voice-ws).
- `agent.py` — the agent container entrypoint. `Dockerfile` builds it.

## Gotchas (learned the hard way)

- **`deploy.sh` owns env-var wiring, NOT the `azure.yaml` hooks.** The hooks
  don't fire reliably across the separate `azd provision` / `azd deploy` calls
  `deploy.sh` makes, so the postprovision hook is informational-only. Anything
  the agent needs at deploy time (`AZURE_TENANT_ID`, `TWILIO_VOICE_PUBLIC_DOMAIN`,
  `AZURE_AI_PROJECT_ID`, `FOUNDRY_PROJECT_ENDPOINT`,
  `AZURE_CONTAINER_REGISTRY_ENDPOINT`, `AZURE_OPENAI_*`) is set in `deploy.sh`'s
  "bridge" step between provision and the agent push. Add new agent env wiring
  there, not in the hook.
- **SDK changes need a wheel rebuild.** The Dockerfile installs the TAC SDK from
  a vendored wheel in `wheels/` (not PyPI yet). Editing `src/tac_microsoft/...`
  has NO effect until you `uv build` + refresh `wheels/` (see README "Update
  code"). Editing `agent.py` does NOT need a rebuild.
- **ACR pull identity is the PROJECT managed identity**, not the account MI.
  `foundry.bicep` grants `AcrPull` to `project.identity.principalId`; granting
  the account MI fails the image pull (`ImageError`).
- **Derived resource names are length-sensitive.** Names come from `apimName`
  (= `tac-<slug>-<hash>`). Key Vault is `kv${uniqueString(...)}` (fixed length,
  no trailing-hyphen) — don't go back to `take('kv-${apimName}-...', 24)`, it
  truncates onto a hyphen for longer slugs and Azure rejects it. ACR strips
  hyphens; account is `<apim>-ai`.
- **`DEPLOY_SLUG` is consumed on first deploy.** `deploy.sh` materializes the
  literal resource names into `.env` from the slug, then removes the slug. After
  that the names in `.env` are the source of truth; editing the slug does
  nothing. Re-runs are idempotent and hit the same stack.
- **Both Twilio webhooks must be POST.** APIM only defines `POST`; a GET 404s
  (presents as "no response"). `configure_twilio.sh` sets both correctly.
- **`createFoundry=false`** is the bring-your-own-project path; then the
  `Foundry User` role grant is the user's job (the template only grants it when
  it creates the account).
- **Tenant policy.** Resources are tagged (`created_by`) and the Key Vault has a
  firewall + `AzureServices` bypass to satisfy common deny policies. If a tenant
  denies something new, the error names the policy.

## Secrets / git

- The real `.env` is gitignored — never commit it. `.env.template` must stay
  placeholder-only (no real Twilio/Azure values).
- Stage by explicit path; scan for env-like filenames before committing.

## Related

- Repo overview + import patterns: [root CLAUDE.md](../../CLAUDE.md).
- Container Apps sibling deployment: `../agent_framework_container_apps`.
