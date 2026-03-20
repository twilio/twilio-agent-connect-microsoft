# Plan: TACServer Enhancements (in twilio-agent-connect-python)

These changes are prerequisites for the partner package strategy.
Applied to: `~/proj/twilio-agent-connect-python/`

## Summary

Add two small enhancements to `TACServer` so partner SDKs can delegate server lifecycle to it without losing functionality they currently own.

---

## Change 1: Add `on_startup` callback

File: `src/tac/server/server.py`

Partner SDKs need async initialization before serving (e.g., fetching knowledge base metadata). TACServer currently has no lifecycle hook.

**Add parameter to `__init__`**:
```python
def __init__(
    self,
    tac: TAC,
    voice_channel: VoiceChannel | None = None,
    sms_channel: SMSChannel | None = None,
    config: TACServerConfig | None = None,
    on_startup: Callable[[], Awaitable[None]] | None = None,  # NEW
) -> None:
    ...
    self.on_startup = on_startup
```

**Wire into `_create_app()` via FastAPI lifespan**:
```python
def _create_app(self) -> FastAPI:
    from contextlib import asynccontextmanager
    startup_cb = self.on_startup

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if startup_cb:
            await startup_cb()
        yield

    app = FastAPI(title="TAC Server", lifespan=lifespan)
    # ... rest of existing route registration unchanged
```

---

## Change 2: Add `app` property

File: `src/tac/server/server.py`

Partner SDKs need access to the FastAPI app for two reasons:
1. Container deployments: `CMD ["uvicorn", "server:app", ...]` requires an importable `app` object
2. Custom routes: developers add routes to `server.app` alongside TACServer's built-in routes

**Add to `__init__`**:
```python
self._app: FastAPI | None = None
```

**Add property**:
```python
@property
def app(self) -> FastAPI:
    """Return (and lazily create) the FastAPI application."""
    if self._app is None:
        self._app = self._create_app()
    return self._app
```

**Update `start()` to use property**:
```python
def start(self) -> None:
    """Create the FastAPI app and start uvicorn."""
    logger.info(f"Starting TAC Server on {self.config.host}:{self.config.port}")
    uvicorn.run(
        self.app,  # was: self._create_app()
        host=self.config.host,
        port=self.config.port,
        log_level="info",
        access_log=False,
    )
```

---

## Verification

1. `server.app` returns a FastAPI instance before `start()` is called
2. `server.start()` still works (uses cached app)
3. `on_startup` callback fires before first request
4. Existing TAC examples/tests are unaffected (no breaking changes)
