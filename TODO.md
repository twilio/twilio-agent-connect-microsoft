# TODO

Tracked work items for `tac-azure` based on deep SDK review.

---

## Dependency Management

- [ ] **Split dependencies into extras** — core package should only require `agent-framework`, `tac`, and `pydantic`. Move `fastapi`, `uvicorn`, `websockets` into a `[server]` extra. Move `agent-framework-azure-ai`, `azure-identity` into an `[azure]` extra. Add a `[dev]` extra for ruff/mypy/pytest.
- [ ] **Remove `truststore` from package dependencies** — macOS-only SSL workaround that the SDK itself never calls. Belongs in example code or a setup guide, not in the manifest.
- [ ] **Remove `python-dotenv` from package dependencies** — the SDK never calls `load_dotenv()`. This is an app-level concern handled by each example already.
- [ ] **Resolve TAC private git dependency** — currently pinned to a commit hash on `twilio-internal` via SSH. Blocks anyone without org access. Needs a PyPI publish (even private index) or a documented workaround for external consumers.

---

## Naming and Identity

- [ ] **Reconsider package name `tac_azure`** — the SDK works with any Agent Framework provider (OpenAI, Ollama, Anthropic), not just Azure. Name implies Azure lock-in. Candidates: `tac_agent_framework`, `twilio_agent_connect`.
- [ ] **Reconsider repo name** — `azure-twilio-agent-connect-python` vs `microsoft-agent-framework-twilio-agent-connect-python` or shorter alternative.

---

## API Fixes

- [ ] **Type the `tac` parameter properly** — both `AgentFrameworkConnector` and `OmniChannelServer` accept `tac: Any`. Kills IDE autocomplete and type checking. Should be the actual `TAC` class or a Protocol describing the required interface.
- [ ] **Use `Literal["voice", "sms"]` for channels** — currently `list[str]`, so typos like `["Voice"]` silently produce no channels. Use `Literal` or an enum.
- [ ] **Make `on_message` hook support async** — currently sync-only (`Callable[..., str]`), called from async context. Prevents users from doing async operations (DB lookups, API calls) in the hook. Accept `Callable[..., str | Awaitable[str]]`.
- [ ] **Consider making `create_agent` support async** — lower priority than `on_message`, but same limitation. Blocks async setup per-agent (feature flags, config fetches).
- [ ] **Stop accessing private TAC internals** — `omnichannel_handler.py:343` reads `self.voice_channel._conversations[conversation_id]`. Request a public getter from TAC. Isolate behind a helper method with a clear TODO until then.
- [ ] **Fix voice agent cleanup logic** — `omnichannel_handler.py:407` `if not agent` warning fires when no agent exists, which is expected if WebSocket connected but no speech was received. The warning generates noise in production logs. Also, `del agent` / `del af_session` on local variables are no-ops.

---

## Tools

- [ ] **Remove or implement placeholder tools** — `flex_escalation.py` and `messaging.py` return `{"status": "...", "..._id": "placeholder"}`. Shipping stubs that don't work erodes trust. Either implement them or remove and document as "coming soon."
- [ ] **Fix tool parameter types** — `escalate_to_flex(params: dict[str, Any])` and `send_message(params: dict[str, Any])` give the LLM no schema. Use explicit keyword arguments or Pydantic models.
- [ ] **Standardize tool creation patterns** — three different patterns currently: factory returning `tac_tool.implementation`, factory returning a closure, and a raw async generator. Align on one consistent pattern.
- [ ] **Create Azure TAC memory adapter** — noted in ARCHITECTURE_REVIEW.md. Replace hand-rolled `format_memory_context` with a proper adapter. Do the same for Strands.

---

## Developer Experience

- [ ] **Add `.env.example` files** — one per example directory with all required env vars documented inline.
- [ ] **Remove `truststore` boilerplate from examples** — every example starts with `import truststore; truststore.inject_into_ssl()`. Either handle in the SDK with a platform guard, or move to a setup guide section.
- [ ] **Document `pip install .`** — README only documents `uv`. Enterprise Azure developers commonly use pip, poetry, or conda.
- [ ] **Add `py.typed` marker** — without `src/tac_azure/py.typed`, type checkers (mypy, pyright) won't treat the package as typed despite full annotations.
- [ ] **Add `__version__` to `__init__.py`** — enables `import tac_azure; print(tac_azure.__version__)` for debugging.

---

## Production Readiness

- [ ] **Add test suite** — no tests exist. At minimum: unit tests for `AgentFrameworkConnector` (mock TAC/Agent), `AgentSessionStore` protocol conformance, `format_memory_context`, and tool factories.
- [ ] **Add linting and type checking config** — ruff + mypy (or pyright). Add to CI.
- [ ] **Add CI/CD** — GitHub Actions for lint, type check, and test on every PR.
- [ ] **Add lifecycle hooks** — `on_call_start`, `on_call_end`, `on_sms_start`, `on_sms_end`, `on_error`. These are the most-requested extension points in similar SDKs.
- [ ] **Add `on_error` hook** — developers need to customize error handling (Sentry, retry, escalate). Currently SMS errors send a hardcoded generic message with no interception point.
- [ ] **Add graceful shutdown for background tasks** — `asyncio.create_task()` fire-and-forget saves are lost if the server shuts down. Track pending tasks and await them during shutdown.
- [ ] **Add metrics/tracing hooks** — no OpenTelemetry, no structured metrics, no APM integration point.
- [ ] **Consider rate limiting guidance** — WebSocket and SMS endpoints are unprotected. At minimum, document the concern; optionally add middleware support.
- [ ] **Consider SMS retry/dead-letter strategy** — webhook processing is fire-and-forget with `asyncio.create_task()`. If it fails, Twilio never knows and there's no retry.

---

## Documentation

- [ ] **Keep README focused on quick start** — it's currently good but mixes quick start, API reference, and architecture. Consider splitting API reference into separate docs or generated API docs.
- [ ] **Document deployment patterns** — ARCHITECTURE_REVIEW.md has excellent content on self-contained vs Foundry vs Hosted Agents. This should be user-facing documentation, not just an internal review doc.
- [ ] **Document horizontal scaling** — `AgentSessionStore` is the key abstraction for scaling, but there's no guide showing a Redis or CosmosDB implementation end-to-end.
