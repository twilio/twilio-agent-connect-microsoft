#!/usr/bin/env bash
#
# Point Twilio at a deployed Hosted Agents stack:
#   1. Phone number Voice URL  -> https://<apim>/twilio/twiml   (HTTP POST)
#   2. Conversation Orchestrator statusCallback -> https://<apim>/twilio/webhook (POST)
#
# Reads the APIM URLs from the azd environment outputs and the Twilio
# credentials / number / configuration id from the azd environment (loaded
# from .env by deploy.sh). Safe to re-run — it overwrites both targets to
# point at THIS deployment.
#
# NOTE: this mutates shared Twilio state. Pointing this number / configuration
# at this deployment points it AWAY from any other deployment that was using
# the same number / configuration.
#
# Usage:
#   ./configure_twilio.sh [-e <azd-env>]
#
# Requires: az/azd logged in, curl, python3.

set -euo pipefail
cd "$(dirname "$0")"

ENV_ARG=()
if [ "${1:-}" = "-e" ] && [ -n "${2:-}" ]; then
  ENV_ARG=(-e "$2")
fi

getv() { azd env get-value "$1" "${ENV_ARG[@]}" 2>/dev/null || echo ""; }

VOICE_URL=$(getv twilioVoiceTwimlUrl)
SMS_URL=$(getv twilioSmsWebhookUrl)
ACCOUNT_SID=$(getv TWILIO_ACCOUNT_SID)
AUTH_TOKEN=$(getv TWILIO_AUTH_TOKEN)
API_KEY=$(getv TWILIO_API_KEY)
API_SECRET=$(getv TWILIO_API_SECRET)
PHONE=$(getv TWILIO_PHONE_NUMBER)
CONFIG_ID=$(getv TWILIO_CONVERSATION_CONFIGURATION_ID)

# Basic-auth pair: prefer API key/secret, fall back to Account SID/Auth Token.
if [ -n "$API_KEY" ] && [ -n "$API_SECRET" ]; then
  AUTH="$API_KEY:$API_SECRET"
else
  AUTH="$ACCOUNT_SID:$AUTH_TOKEN"
fi

fail() { echo "ERROR: $1" >&2; exit 1; }
[ -n "$ACCOUNT_SID" ] || fail "TWILIO_ACCOUNT_SID not set in the azd environment."
[ -n "$AUTH" ] || fail "No Twilio credentials (API key/secret or auth token) in the azd environment."

# ---------------------------------------------------------------------------
# 1. Phone number Voice URL (classic REST API)
# ---------------------------------------------------------------------------
if [ -n "$PHONE" ] && [ -n "$VOICE_URL" ]; then
  echo "==> Setting Voice URL for $PHONE -> $VOICE_URL (POST)"
  # Find the IncomingPhoneNumber SID for this E.164 number.
  PN_SID=$(curl -s -u "$AUTH" \
    --get "https://api.twilio.com/2010-04-01/Accounts/$ACCOUNT_SID/IncomingPhoneNumbers.json" \
    --data-urlencode "PhoneNumber=$PHONE" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); l=d.get('incoming_phone_numbers',[]); print(l[0]['sid'] if l else '')" 2>/dev/null || echo "")
  if [ -z "$PN_SID" ]; then
    echo "    WARNING: no IncomingPhoneNumber found for $PHONE on this account — skipping voice." >&2
  else
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST -u "$AUTH" \
      "https://api.twilio.com/2010-04-01/Accounts/$ACCOUNT_SID/IncomingPhoneNumbers/$PN_SID.json" \
      --data-urlencode "VoiceUrl=$VOICE_URL" \
      --data-urlencode "VoiceMethod=POST")
    if [ "$HTTP" = "200" ]; then echo "    OK (number $PN_SID updated)"; VOICE_OK=1; else echo "    WARNING: voice update returned HTTP $HTTP" >&2; fi
  fi
else
  echo "==> Skipping voice (TWILIO_PHONE_NUMBER or twilioVoiceTwimlUrl missing)."
fi

# ---------------------------------------------------------------------------
# 2. Conversation Orchestrator statusCallback (Maestro Domain API)
# ---------------------------------------------------------------------------
if [ -n "$CONFIG_ID" ] && [ -n "$SMS_URL" ]; then
  echo "==> Setting Conversation Orchestrator webhook on $CONFIG_ID -> $SMS_URL (POST)"
  BASE="https://conversations.twilio.com/v2/ControlPlane/Configurations/$CONFIG_ID"
  # Fetch current config, swap statusCallbacks, strip read-only fields, PUT back.
  CUR=$(curl -s -u "$AUTH" -H "X-Pre-Auth-Context: $ACCOUNT_SID" "$BASE")
  BODY=$(printf '%s' "$CUR" | python3 -c "
import sys, json
url = sys.argv[1]
d = json.load(sys.stdin)
d['statusCallbacks'] = [{'method': 'POST', 'url': url}]
for k in ['id','createdAt','updatedAt','version','accountId','serviceId']:
    d.pop(k, None)
print(json.dumps(d))
" "$SMS_URL" 2>/dev/null || echo "")
  if [ -z "$BODY" ]; then
    echo "    WARNING: could not read/parse configuration $CONFIG_ID — skipping SMS webhook." >&2
  else
    HTTP=$(printf '%s' "$BODY" | curl -s -o /dev/null -w "%{http_code}" -X PUT -u "$AUTH" \
      -H "X-Pre-Auth-Context: $ACCOUNT_SID" -H "Content-Type: application/json" \
      --data @- "$BASE")
    case "$HTTP" in
      200|202) echo "    OK (configuration updated, HTTP $HTTP)"; SMS_OK=1 ;;
      *) echo "    WARNING: configuration update returned HTTP $HTTP" >&2 ;;
    esac
  fi
else
  echo "==> Skipping SMS webhook (TWILIO_CONVERSATION_CONFIGURATION_ID or twilioSmsWebhookUrl missing)."
fi

echo "==> Twilio configuration complete."

# Tailor the "ready" line to what actually got wired up.
ACTIONS=""
if [ -n "${VOICE_OK:-}" ] && [ -n "${SMS_OK:-}" ]; then
  ACTIONS="text or call"
elif [ -n "${SMS_OK:-}" ]; then
  ACTIONS="text"
elif [ -n "${VOICE_OK:-}" ]; then
  ACTIONS="call"
fi
if [ -n "$ACTIONS" ] && [ -n "$PHONE" ]; then
  echo ""
  echo "============================================================"
  echo " Your agent is ready. Send a $ACTIONS to:"
  echo ""
  echo "     $PHONE"
  echo "============================================================"
fi
