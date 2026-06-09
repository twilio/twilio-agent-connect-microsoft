.PHONY: help deploy agent urls configure-twilio down

# Post-deploy targets (agent/urls/down) act on the azd env that `make deploy`
# created/selected. We read its name from .env if set, else fall back to azd's
# current default environment (which deploy.sh selected).
ENV_NAME := $(shell grep -E '^AZURE_ENV_NAME=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"'')
ENV_ARG  := $(if $(ENV_NAME),-e $(ENV_NAME),)

help:
	@echo "TAC Hosted Agents deployment commands:"
	@echo "  make deploy   - Fill in .env, then run this. Creates the azd env, loads .env,"
	@echo "                  provisions everything fresh, and pushes the agent. One command."
	@echo "  make agent            - Rebuild/redeploy just the agent (azd deploy)"
	@echo "  make urls             - Print the Twilio Voice/SMS URLs to configure"
	@echo "  make configure-twilio - Point your Twilio number + conversation config at this deploy"
	@echo "  make down             - Tear down ALL resources this deployment created (prompts to confirm)"

# One command: bootstraps the azd env from .env, provisions (with the Key Vault
# RBAC-race retry), and deploys the agent. Requires only a filled-in .env.
deploy:
	./deploy.sh

agent:
	azd deploy --no-prompt $(ENV_ARG)

urls:
	@azd env get-values $(ENV_ARG) | grep -iE "twilioVoiceTwimlUrl|twilioSmsWebhookUrl|twilioVoiceWssUrl|voicePublicDomain" || true

configure-twilio:
	./configure_twilio.sh $(ENV_ARG)

# Tear down everything this deployment created: the agent, plus the resource
# group's APIM, Key Vault, Foundry account + project + model, and Container
# Registry. `--purge` also clears the soft-deleted APIM/Foundry/Key Vault so
# their globally-unique names are immediately reusable. Confirms first, since
# this is destructive and irreversible.
down:
	@echo "This will DELETE all Azure resources for env '$(ENV_NAME)':"
	@echo "  agent, APIM, Key Vault, Foundry account + project + model, Container Registry"
	@echo "  (and purge the soft-deleted APIM / Foundry / Key Vault)."
	@printf 'Tear everything down? [y/N]: '; \
	read ans; \
	case "$$ans" in \
	  [yY]|[yY][eE][sS]) azd down --force --purge $(ENV_ARG) ;; \
	  *) echo "Aborted." ;; \
	esac
