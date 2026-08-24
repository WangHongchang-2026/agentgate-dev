"""Read-only catalog for the POC Demo Target versions."""

from __future__ import annotations


class TargetCatalog:
    """Resolve exact Demo Target versions without relying on collection order."""

    _versions = (
        {"id": "loan-agent-v1-risky", "label": "风险版本", "is_latest": False},
        {"id": "loan-agent-v2-fixed", "label": "修复版本", "is_latest": True},
    )

    def versions(self) -> tuple[dict, ...]:
        return tuple(dict(item) for item in self._versions)

    def resolve(self, version: str | None) -> str:
        selected = version or next(
            item["id"] for item in self._versions if item["is_latest"]
        )
        if selected not in {item["id"] for item in self._versions}:
            raise ValueError(f"unknown target version: {selected}")
        return selected
