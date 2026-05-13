from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass
class Observation:
    count: int = 0
    total: float = 0.0
    max_value: float = 0.0

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.max_value = max(self.max_value, value)


class Metrics:
    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()
        self._gauges: dict[str, float] = {}
        self._observations: dict[str, Observation] = {}

    def increment(self, name: str, value: int = 1) -> None:
        self._counters[name] += value

    def set_gauge(self, name: str, value: int | float) -> None:
        self._gauges[name] = float(value)

    def observe(self, name: str, value: int | float) -> None:
        self._observations.setdefault(name, Observation()).observe(float(value))

    def snapshot(self) -> dict[str, object]:
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "observations": {
                name: {
                    "count": observation.count,
                    "sum": observation.total,
                    "max": observation.max_value,
                    "avg": observation.total / observation.count if observation.count else 0.0,
                }
                for name, observation in self._observations.items()
            },
        }

    def render_text(self) -> str:
        lines = []
        for name, value in sorted(self._counters.items()):
            metric_name = _metric_name(name)
            lines.append(f"# TYPE {metric_name} counter")
            lines.append(f"{metric_name} {value}")
        for name, value in sorted(self._gauges.items()):
            metric_name = _metric_name(name)
            lines.append(f"# TYPE {metric_name} gauge")
            lines.append(f"{metric_name} {value}")
        for name, observation in sorted(self._observations.items()):
            metric_name = _metric_name(name)
            lines.append(f"# TYPE {metric_name} summary")
            lines.append(f"{metric_name}_count {observation.count}")
            lines.append(f"{metric_name}_sum {observation.total}")
            lines.append(f"{metric_name}_max {observation.max_value}")
        return "\n".join(lines) + ("\n" if lines else "")


def _metric_name(name: str) -> str:
    safe = "".join(character if character.isalnum() else "_" for character in name)
    return "openabm_" + safe.strip("_")
