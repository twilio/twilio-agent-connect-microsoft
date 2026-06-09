#!/usr/bin/env bash
#
# One-command, interactive deploy for TAC Agent Framework on Hosted Agents.
#
# Run `make deploy` (or ./deploy.sh). If .env doesn't exist it's created from
# the template; any missing REQUIRED values are prompted for one-by-one and
# written back to .env. Resource names are derived from a single "slug" you
# choose (e.g. your alias) plus a stable hash of (slug + subscription), so
# every solution engineer gets an INDEPENDENT, globally-unique, collision-free
# deployment that works the first time — and re-running updates the SAME stack
# rather than creating a new one.
#
# Then it: creates/selects the azd env, loads .env, provisions everything fresh
# (Foundry account + project + model + ACR + APIM + Key Vault, with a retry on
# the transient Key Vault RBAC race), and pushes the agent.
#
# Requires: azd + az installed and logged in.

set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=".env"
TEMPLATE=".env.template"

# ---------------------------------------------------------------------------
# .env helpers
# ---------------------------------------------------------------------------
# Read a key's current value from .env (empty if unset/placeholder).
read_val() {
  local v
  v=$(grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
  # Treat template placeholders (<...>) as empty.
  case "$v" in
    "<"*) echo "" ;;
    *) echo "$v" ;;
  esac
}

# Write/replace a key=value in .env.
write_val() {
  local key="$1" val="$2"
  if grep -qE "^$key=" "$ENV_FILE" 2>/dev/null; then
    # Replace in place (portable: write temp, move).
    grep -vE "^$key=" "$ENV_FILE" > "$ENV_FILE.tmp"
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
}

# Remove a key line from .env entirely (used to consume DEPLOY_SLUG after the
# resource names have been materialized from it).
remove_val() {
  local key="$1"
  if grep -qE "^$key=" "$ENV_FILE" 2>/dev/null; then
    grep -vE "^$key=" "$ENV_FILE" > "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"
  fi
}

# Prompt for a value if missing. Args: KEY "Prompt text" [secret] [default]
prompt_if_missing() {
  local key="$1" label="$2" secret="${3:-}" default="${4:-}"
  local cur
  cur=$(read_val "$key")
  if [ -n "$cur" ]; then
    return
  fi
  local input=""
  if [ "$secret" = "secret" ]; then
    printf '%s: ' "$label" >&2
    read -r -s input
    echo "" >&2
  else
    input=$(prompt_editable "$label: " "$default")
  fi
  if [ -z "$input" ]; then
    echo "ERROR: $key is required." >&2
    exit 1
  fi
  write_val "$key" "$input"
}

# Prompt with the default pre-filled as editable input (readline -i), so the
# user sees the real value and can edit it in place rather than retype it.
# Falls back to a "[default]" prompt where readline -i isn't available.
prompt_editable() {
  local prompt="$1" default="$2" out=""
  if read -e -i "x" -r _probe </dev/null 2>/dev/null; then
    # readline editing with an initial value is supported.
    read -e -i "$default" -r -p "$prompt" out >&2
  else
    if [ -n "$default" ]; then
      printf '%s[%s] ' "$prompt" "$default" >&2
    else
      printf '%s' "$prompt" >&2
    fi
    read -r out
    [ -z "$out" ] && out="$default"
  fi
  printf '%s' "$out"
}

# Stable short hash from slug + subscription (same every run → idempotent names).
stable_hash() {
  printf '%s' "$1-$2" | shasum 2>/dev/null | cut -c1-6
}

# ---------------------------------------------------------------------------
# 0. Ensure .env exists
# ---------------------------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  if [ ! -f "$TEMPLATE" ]; then
    echo "ERROR: neither $ENV_FILE nor $TEMPLATE found." >&2
    exit 1
  fi
  cp "$TEMPLATE" "$ENV_FILE"
  echo "==> Created $ENV_FILE from $TEMPLATE. Let's fill in the required values."
  echo ""
fi

# ---------------------------------------------------------------------------
# 1. Subscription (needed before we can derive/validate anything)
# ---------------------------------------------------------------------------
prompt_if_missing AZURE_SUBSCRIPTION_ID "Azure subscription ID" "" "$(az account show --query id -o tsv 2>/dev/null || echo '')"
SUB=$(read_val AZURE_SUBSCRIPTION_ID)

# ---------------------------------------------------------------------------
# 2. Resource names — materialized once from a one-time DEPLOY_SLUG.
# ---------------------------------------------------------------------------
# The names (AZURE_ENV_NAME / AZURE_RESOURCE_GROUP / APIM_NAME /
# HOSTED_AGENTS_PROJECT_NAME) are the authoritative source of truth in .env.
# DEPLOY_SLUG is only a bootstrap convenience: the FIRST time these names are
# absent, we generate globally-unique, collision-free values from the slug +
# a stable hash, write them into .env as raw values, and then CONSUME the slug
# (remove it). After that, .env shows only literal names — what you see is what
# deploys — and editing/removing the slug does nothing. To regenerate, delete
# the name lines (or the whole .env).
if [ -z "$(read_val APIM_NAME)" ]; then
  SLUG=$(read_val DEPLOY_SLUG)
  if [ -z "$SLUG" ]; then
    # Default: first initial + last name (e.g. John Smith -> jsmith), derived
    # from the Azure sign-in display name; fall back to the email alias.
    DISPLAY=$(az ad signed-in-user show --query displayName -o tsv 2>/dev/null || echo "")
    if [ -n "$DISPLAY" ]; then
      FIRST=$(printf '%s' "$DISPLAY" | awk '{print tolower(substr($1,1,1))}')
      LAST=$(printf '%s' "$DISPLAY" | awk '{print tolower($NF)}')
      DEFAULT_SLUG=$(printf '%s%s' "$FIRST" "$LAST" | tr -cd 'a-z0-9')
    else
      DEFAULT_SLUG=$(az account show --query user.name -o tsv 2>/dev/null | cut -d@ -f1 | tr -cd 'a-z0-9' || echo "")
    fi
    SLUG=$(prompt_editable 'Deployment slug (first initial + last name, e.g. John Smith -> jsmith): ' "$DEFAULT_SLUG")
  fi
  SLUG=$(printf '%s' "$SLUG" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')
  if [ -z "$SLUG" ]; then echo "ERROR: a deployment slug is required to generate resource names." >&2; exit 1; fi
  HASH=$(stable_hash "$SLUG" "$SUB")

  # Materialize raw names (only fill ones the user hasn't pinned). Bicep
  # derives the Foundry account / ACR / Key Vault names from APIM_NAME, so
  # APIM_NAME + env/RG/project are all we set here.
  [ -z "$(read_val AZURE_ENV_NAME)" ]             && write_val AZURE_ENV_NAME "tac-$SLUG"
  [ -z "$(read_val AZURE_RESOURCE_GROUP)" ]       && write_val AZURE_RESOURCE_GROUP "rg-tac-$SLUG"
  write_val APIM_NAME "tac-$SLUG-$HASH"
  [ -z "$(read_val HOSTED_AGENTS_PROJECT_NAME)" ] && write_val HOSTED_AGENTS_PROJECT_NAME "tac-$SLUG-project"

  # Consume the slug — names are now the source of truth.
  remove_val DEPLOY_SLUG
fi

# ---------------------------------------------------------------------------
# 3. Remaining required values (Twilio + publisher email)
# ---------------------------------------------------------------------------
prompt_if_missing APIM_PUBLISHER_EMAIL "Your email" "" "$(az account show --query user.name -o tsv 2>/dev/null || echo '')"
prompt_if_missing TWILIO_ACCOUNT_SID "Twilio Account SID (AC...)"
prompt_if_missing TWILIO_AUTH_TOKEN "Twilio Auth Token" secret
prompt_if_missing TWILIO_API_KEY "Twilio API Key (SK...)"
prompt_if_missing TWILIO_API_SECRET "Twilio API Secret" secret
prompt_if_missing TWILIO_PHONE_NUMBER "Twilio phone number (+1...)"
prompt_if_missing TWILIO_CONVERSATION_CONFIGURATION_ID "Twilio Conversation Configuration ID (conv_configuration_...)"

AZURE_ENV_NAME=$(read_val AZURE_ENV_NAME)
AZURE_LOCATION=$(read_val AZURE_LOCATION); : "${AZURE_LOCATION:=northcentralus}"

echo ""
echo "==> Deployment configured:"
echo "    azd env:         $AZURE_ENV_NAME"
echo "    resource group:  $(read_val AZURE_RESOURCE_GROUP)"
echo "    APIM:            $(read_val APIM_NAME)"
echo "    project:         $(read_val HOSTED_AGENTS_PROJECT_NAME)"
echo ""

# Confirm before kicking off the long-running deploy. Skipped when not running
# interactively (so CI/automation proceeds without a prompt).
if [ -t 0 ]; then
  printf 'Start deployment? This provisions Azure resources and pushes the agent, and typically takes several minutes. [Y/n]: '
  read -r START_ANSWER
  case "$START_ANSWER" in
    [nN]|[nN][oO])
      echo "Aborted. Re-run 'make deploy' when ready."
      exit 0
      ;;
  esac
fi
echo ""
echo "==> Starting deployment. No more input needed from here..."
echo ""

# ---------------------------------------------------------------------------
# 4. Create/select azd env + load .env
# ---------------------------------------------------------------------------
if azd env list --output json 2>/dev/null | grep -q "\"Name\": *\"$AZURE_ENV_NAME\""; then
  echo "==> Using existing azd environment '$AZURE_ENV_NAME'."
  azd env select "$AZURE_ENV_NAME"
else
  echo "==> Creating azd environment '$AZURE_ENV_NAME'..."
  azd env new "$AZURE_ENV_NAME" --location "$AZURE_LOCATION" --subscription "$SUB"
fi

echo "==> Loading $ENV_FILE into the azd environment..."
azd env set --file "$ENV_FILE" -e "$AZURE_ENV_NAME"

# azd's `host: azure.ai.agent` deploy step (postdeploy) requires AZURE_TENANT_ID
# in the environment and fails without it. Set it here from the signed-in
# account so it's guaranteed present before provision/deploy.
if [ -z "$(read_val AZURE_TENANT_ID)" ]; then
  TENANT=$(az account show --query tenantId -o tsv 2>/dev/null || echo "")
  if [ -n "$TENANT" ]; then
    azd env set AZURE_TENANT_ID "$TENANT" -e "$AZURE_ENV_NAME"
    write_val AZURE_TENANT_ID "$TENANT"
  fi
fi

ENV_ARG=(-e "$AZURE_ENV_NAME")
KV_RACE_PATTERN='getSecret/action|Reference resolution failed|Caller is not authorized'
provision() { azd provision --no-prompt --no-state "${ENV_ARG[@]}" 2>&1; }

# ---------------------------------------------------------------------------
# 5. Provision (with one retry on the KV RBAC race) + deploy the agent
# ---------------------------------------------------------------------------
echo "==> Provisioning infrastructure..."
set +e; OUTPUT=$(provision); STATUS=$?; set -e
echo "$OUTPUT"
if [ "$STATUS" -ne 0 ] && echo "$OUTPUT" | grep -qiE "$KV_RACE_PATTERN"; then
  echo ""
  echo "==> Hit the transient Key Vault RBAC-propagation race. Waiting 60s and retrying once..."
  sleep 60
  set +e; OUTPUT=$(provision); STATUS=$?; set -e
  echo "$OUTPUT"
fi
if [ "$STATUS" -ne 0 ]; then
  echo "" >&2
  echo "ERROR: provisioning failed (not the known transient KV race, or the retry" >&2
  echo "       did not resolve it). See output above." >&2
  exit "$STATUS"
fi

# Bridge provision outputs -> agent env vars BEFORE the agent push.
# These values only exist as Bicep outputs after provision, but the agent
# (agent.yaml) reads them at deploy time. We set them here in deploy.sh rather
# than rely on the azure.yaml postprovision hook, which has proven unreliable
# for the standalone `azd provision`/`azd deploy` calls this script makes.
#
# Helper: copy a Bicep output into an agent env var if that var isn't already
# set (so a user-pinned value or a prior run wins).
#
# Detect "is X set?" via `azd env get-value`'s EXIT STATUS, not by inspecting
# its output: a missing key prints a multi-line "ERROR/Suggestion" message
# (split across stdout/stderr) that is unreliable to pattern-match. A set key
# exits 0 and prints just the value; a missing key exits non-zero.
get_if_set() { # prints value to stdout iff the key is set (exit 0); else exit 1
  azd env get-value "$1" "${ENV_ARG[@]}" 2>/dev/null
}
bridge() { # bridge <output-key> <env-var>
  local out_key="$1" var="$2" val
  get_if_set "$var" >/dev/null 2>&1 && return 0          # already set -> leave it
  val=$(get_if_set "$out_key") || return 0               # output missing -> skip
  [ -n "$val" ] || return 0
  azd env set "$var" "$val" "${ENV_ARG[@]}"
}

echo "==> Wiring agent environment from provision outputs..."
# Voice: agent emits wss://<domain>/ws and 500s on /twiml if this is unset.
bridge voicePublicDomain TWILIO_VOICE_PUBLIC_DOMAIN
# Fresh-Foundry wiring the agent push needs (no-ops when bring-your-own).
bridge foundryProjectResourceId AZURE_AI_PROJECT_ID
bridge foundryProjectEndpoint FOUNDRY_PROJECT_ENDPOINT
bridge containerRegistryEndpoint AZURE_CONTAINER_REGISTRY_ENDPOINT
bridge openAiEndpoint AZURE_OPENAI_ENDPOINT
bridge modelDeploymentName AZURE_OPENAI_DEPLOYMENT_NAME

# OpenAI key isn't a Bicep output (secrets shouldn't be); fetch it from the
# created account if the agent doesn't already have one.
if ! get_if_set AZURE_OPENAI_API_KEY >/dev/null 2>&1; then
  ACCT=$(azd env get-value foundryAccountName "${ENV_ARG[@]}" 2>/dev/null || echo "")
  RG=$(read_val AZURE_RESOURCE_GROUP)
  if [ -n "$ACCT" ] && [ -n "$RG" ]; then
    OAI_KEY=$(az cognitiveservices account keys list --name "$ACCT" --resource-group "$RG" --query key1 -o tsv 2>/dev/null || echo "")
    [ -n "$OAI_KEY" ] && azd env set AZURE_OPENAI_API_KEY "$OAI_KEY" "${ENV_ARG[@]}"
  fi
fi

echo ""
echo "==> Deploying the agent..."
azd deploy --no-prompt "${ENV_ARG[@]}"

# Re-print the Twilio config URLs as the final output so they're the last
# thing on screen (the postprovision hook prints them earlier, but the agent
# push scrolls them off).
VOICE_URL=$(azd env get-value twilioVoiceTwimlUrl "${ENV_ARG[@]}" 2>/dev/null || echo "")
SMS_URL=$(azd env get-value twilioSmsWebhookUrl "${ENV_ARG[@]}" 2>/dev/null || echo "")
echo ""
echo "============================================================"
echo " Deploy complete. Configure Twilio (both URLs use HTTP POST):"
echo ""
echo "   Phone Number -> Voice URL (POST):     $VOICE_URL"
echo "   Conversation Orchestrator (POST):     $SMS_URL"
echo ""
echo "   NOTE: set the HTTP method to POST for BOTH."
echo "============================================================"

# Offer to set those two URLs in Twilio automatically. Opt-in (default No) —
# it mutates shared Twilio state: pointing this number / conversation config
# here points it away from any other deployment using the same ones. Skipped
# when not running interactively.
if [ -t 0 ]; then
  printf '\nSet Conversation Orchestrator webhook URL and Phone number TwiML webhook URL to this deployment now? [y/N]: '
  read -r ANSWER
  case "$ANSWER" in
    [yY]|[yY][eE][sS])
      ./configure_twilio.sh "${ENV_ARG[@]}"
      ;;
    *)
      echo "Skipped. You can do it later with: make configure-twilio"
      ;;
  esac
fi
