# `azure-twilio-agent-connect-python` vs `strands-twilio-agent-connect-python` - Key Differences

Ordered from biggest departure to smallest.

1. **Multi-provider LLM support** — Azure OpenAI, Foundry, OpenAI, Anthropic, Bedrock, Ollama, etc. via MS Agent Framework. Strands is Bedrock-only. Also enables Foundry portal → Twilio (define agents in UI, serve via SDK).

2. **No AgentProxy ABC** — uses MS Agent Framework's `Agent` directly (provider-agnostic wrapper around any LLM — handles tool calling, streaming, history).
   - Factory gets full `ConversationSession` instead of two strings (agent has context on current channel)
   - Streaming: `chunk.text` instead of `event["event"]["contentBlockDelta"]["delta"]["text"]`

3. **`SessionStore` interface** — pluggable session persistence. `AgentSession` is Agent Framework's abstraction for agent history (e.g. thread ID for Foundry Agent Service, full conversation history for Chat Completions).
   - SMS: handler auto-loads/saves `AgentSession` around every `agent.run()`
   - Voice: background saves after each utterance (non-blocking)
   - Default: in-memory. Swap for Redis/CosmosDB for horizontal scaling
   - Strands: stores history to local file system (`FileSessionManager`) — doesn't scale horizontally

4. **No handler/server duplication** — Strands copies streaming, agent lifecycle, and SMS logic across both files (handler: 288 lines, server: 559 lines). tac-azure server is a thin wrapper that delegates to handler.

5. **Memory auto-injection** — auto-retrieved memory prepended to prompts by default. Opt out (`auto_retrieve_memory=False`) or customize (`on_message` hook). Strands only exposes memory as a tool.

6. **Webhook signature validation** — built-in, on by default. Strands has none.

7. **Unified message dispatch** — single `on_message_ready` callback registered internally, dispatches by channel. Strands wires voice/SMS separately and requires manual callback registration.

8. **Channel selection** — `channels=["voice"]` or `["sms"]` to init only what you need. Strands always inits both.

9. **Tool registration** — no `@tool` decorator; Agent Framework auto-discovers from function name + docstring + types.

10. **Hooks** — `on_message` (customize SMS augmentation) and `on_startup` (async init). Strands has neither.

11. **Not yet in tac-azure** — no test suite, no ruff/mypy config, no RFC docs (Strands has all three).

## Suggested Improvements for Strands

1. **Fix handler/server duplication** — server should delegate to handler via composition instead of re-implementing streaming, agent lifecycle, and SMS logic
2. **Add webhook signature validation** — currently no validation on any route
3. **Channel selection** — allow initializing only voice or only SMS
4. **on_startup hook** — allow async initialization at server startup (e.g. knowledge base metadata fetch)
5. **Consider memory auto-injection** — currently memory is only available as a tool the agent must call; auto-prepending retrieved memory to prompts reduces latency and simplifies agent instructions
6. **Bump TAC pin** — currently pinned to older commit; newer TAC has unified `on_message_ready`, `auto_retrieve_memory`, `idempotency_token`
