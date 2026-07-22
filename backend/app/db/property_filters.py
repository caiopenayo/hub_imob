from __future__ import annotations

from sqlalchemy.sql.elements import ColumnElement

from .models import Property


def visible_property_filters() -> list[ColumnElement[bool]]:
    return [
        Property.status == "ACTIVE",
        Property.property_subtype.is_distinct_from("Comercial"),
    ]
