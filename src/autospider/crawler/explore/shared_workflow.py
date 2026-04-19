from __future__ import annotations

import sys

from autospider.contexts.collection.application.use_cases import explore_site as _impl

sys.modules[__name__] = _impl
