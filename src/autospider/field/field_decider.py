from __future__ import annotations

import sys

from autospider.contexts.collection.infrastructure.adapters import llm_field_decider as _impl

sys.modules[__name__] = _impl
