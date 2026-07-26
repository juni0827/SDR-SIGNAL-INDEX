from datetime import UTC, datetime
from typing import Any

from sqlalchemy.inspection import inspect


def model_dict(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in inspect(value).mapper.column_attrs:
        item = getattr(value, column.key)
        if isinstance(item, datetime):
            item = item.astimezone(UTC).isoformat()
        result[column.key] = item
    return result
