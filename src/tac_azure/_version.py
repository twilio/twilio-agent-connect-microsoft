"""Single source of truth for the tac-azure package version.

Kept in a leaf module so it can be imported from connectors without pulling in
``tac_azure/__init__.py`` (which re-exports from connectors, causing a cycle).
"""

from importlib.metadata import version

__version__ = version("tac-azure")
