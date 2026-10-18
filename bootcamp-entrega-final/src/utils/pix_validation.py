from jsonschema import ValidationError

from errors import PixInvalidAmount, PixInvalidChannel, PixInvalidSchema, QIException
from utils.schema_handler import describe_schema_error


def pix_schema_error(error: ValidationError) -> QIException:
    path = [str(part) for part in error.absolute_path]

    if path == ["source", "channel"] and error.validator == "enum":
        return PixInvalidChannel()
    if path == ["amount"]:
        return PixInvalidAmount()
    return PixInvalidSchema([describe_schema_error(error)])
