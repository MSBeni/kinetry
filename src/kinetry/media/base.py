"""Spending cap, cache and result types shared by every media provider."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path


class MediaError(RuntimeError):
    pass


class BudgetExceeded(MediaError):
    pass


@dataclass
class MediaResult:
    path: Path
    mime: str
    cost: float  # estimated USD for this call (0 when it came from the cache)
    cached: bool
    meta: dict = field(default_factory=dict)


class Budget:
    """A per-run spending cap in USD. `charge()` is called *before* a provider call and refuses it when the
    estimate would go over the cap, or when the price isn't known and the cap isn't unlimited."""

    def __init__(self, cap: float | None):
        self.cap, self.spent, self.log = cap, 0.0, []
        self._lock = threading.Lock()

    def charge(self, what: str, usd: float | None) -> None:
        with self._lock:
            if usd is None:
                if self.cap is not None:
                    raise BudgetExceeded(
                        f"{what}: no price known for this model, so it can't be checked against the cap"
                    )
                usd = 0.0
            if self.cap is not None and self.spent + usd > self.cap + 1e-9:
                raise BudgetExceeded(
                    f"{what} would cost about ${usd:.2f}; ${self.spent:.2f} of the ${self.cap:.2f} cap is already used"
                )
            self.spent = round(self.spent + usd, 4)
            self.log.append({"what": what, "usd": usd})

    def refund(self, usd: float) -> None:  # a call that failed before producing anything
        with self._lock:
            self.spent = round(max(0.0, self.spent - usd), 4)


class MediaCache:
    """Content-addressed store: key = hash of (provider, model, request, input bytes). A hit is free."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @staticmethod
    def key(provider: str, model: str, request: dict, inputs: list[bytes] | None = None) -> str:
        h = hashlib.sha256()
        h.update(json.dumps([provider, model, request], sort_keys=True, default=str).encode())
        for b in inputs or []:
            h.update(hashlib.sha256(b).digest())
        return h.hexdigest()[:32]

    def get(self, key: str) -> tuple[Path, dict] | None:
        meta = self.root / f"{key}.json"
        if not meta.exists():
            return None
        m = json.loads(meta.read_text())
        p = self.root / m["file"]
        return (p, m) if p.exists() else None

    def put(self, key: str, data: bytes, ext: str, meta: dict) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.root / f"{key}.{ext}"
        p.write_bytes(data)
        (self.root / f"{key}.json").write_text(json.dumps({**meta, "file": p.name}, indent=2))
        return p
