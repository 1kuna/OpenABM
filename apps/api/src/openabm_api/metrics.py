from __future__ import annotations

from collections import Counter


class Metrics:
    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()

    def increment(self, name: str, value: int = 1) -> None:
        self._counters[name] += value

    def render_text(self) -> str:
        lines = []
        for name, value in sorted(self._counters.items()):
            metric_name = "openabm_" + name.replace(".", "_")
            lines.append(f"# TYPE {metric_name} counter")
            lines.append(f"{metric_name} {value}")
        return "\n".join(lines) + ("\n" if lines else "")

