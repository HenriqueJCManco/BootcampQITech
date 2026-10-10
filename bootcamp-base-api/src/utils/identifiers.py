import re
from uuid import UUID

from errors import InvalidSchema


UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def parse_uuid(value: str, field: str) -> UUID:
    if UUID_PATTERN.fullmatch(value) is None:
        raise InvalidSchema(
            "Request validation failed.",
            [{"field": field, "rule": "format", "message": "Value must be a UUID."}],
        )
    return UUID(value)
