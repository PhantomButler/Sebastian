from __future__ import annotations

import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_tools() -> None:
    """Scan capabilities/tools/ and import every non-underscore .py module.
    Each module's @tool decorators self-register into core.tool._tools."""
    tools_dir = Path(__file__).parent
    for path in sorted(tools_dir.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        module_name = f"sebastian.capabilities.tools.{path.stem}"
        try:
            importlib.import_module(module_name)
            logger.info("Loaded tool module: %s", path.stem)
        except Exception:
            logger.exception("Failed to load tool module: %s", path.stem)
