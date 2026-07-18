"""JSON renderer (doc §9.7): the machine-readable Report, field-for-field
what the pydantic model already is.
"""

from __future__ import annotations

from wattage.models import Report


def render_json(report: Report, indent: int | None = 2) -> str:
    return report.model_dump_json(indent=indent)
