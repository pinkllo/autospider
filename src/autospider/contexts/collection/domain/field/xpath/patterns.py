from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class XPathSegment:
    axis: str
    tag: str
    predicate: str = ""

    def render(self) -> str:
        return f"{self.axis}{self.tag}{self.predicate}"
