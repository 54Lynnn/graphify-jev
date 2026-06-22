"""Single source of truth for the graphify output-directory name.

The output directory is ``graphify-out`` by default and overridable with the
``GRAPHIFY_OUT`` env var (worktrees or shared-output setups, #686). It accepts a
relative name (``"graphify-out-feature"``) or an absolute path
(``"/shared/graphify-out"``).

This used to be duplicated as an identical ``_GRAPHIFY_OUT`` constant in
``__main__``, ``cache``, and ``watch``, while ``security`` and ``callflow_html``
hardcoded the literal ``"graphify-out"`` and silently ignored the override
(#1423). Centralising it here keeps the name in one place. The value is read
once at import time, matching the previous per-module constants — set
``GRAPHIFY_OUT`` before the process starts (the normal worktree/shared-output
flow) and every reader honours it.
"""

from __future__ import annotations

import os

GRAPHIFY_OUT = os.environ.get("GRAPHIFY_OUT", "graphify-out")

# Bare directory name even when GRAPHIFY_OUT is an absolute path. Used by the
# path guards that walk parents looking for the output dir by name.
GRAPHIFY_OUT_NAME = os.path.basename(os.path.normpath(GRAPHIFY_OUT))
