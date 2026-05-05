"""Single source of truth for the twilio-agent-connect-microsoft package version.

Kept in a leaf module so it can be imported from connectors without pulling in
``tac_microsoft/__init__.py`` (which re-exports from connectors, causing a cycle).
"""

from importlib.metadata import version

__version__ = version("twilio-agent-connect-microsoft")
