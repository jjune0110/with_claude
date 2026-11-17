from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: int
    name: str
    role: str  # '원장' | '강사'

    @property
    def is_director(self) -> bool:
        return self.role == "원장"
