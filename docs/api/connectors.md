# Connectors

<!-- Documented per-module rather than via `::: tac_microsoft` because the
     package's `__init__.py` resolves optional connectors through `__getattr__`
     at runtime (for lazy-loading extras), which griffe cannot resolve
     statically. -->

## Agent Framework

::: tac_microsoft.agent_framework_connector
    options:
      show_submodules: false

## Voice Live

::: tac_microsoft.voice_live_connector
    options:
      show_submodules: false

### Voice Live configuration and errors

::: tac_microsoft.voice_live_types
    options:
      show_submodules: false
