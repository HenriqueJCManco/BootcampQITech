import inspect
import sys


def error_verification() -> None:
    exported_classes = inspect.getmembers(sys.modules["errors"], inspect.isclass)
    codes: dict[str, str] = {}

    for class_name, class_type in exported_classes:
        if not issubclass(class_type, QIException) or class_type is QIException:
            continue

        code = getattr(class_type, "code", None)
        if code is None:
            continue
        if code in codes:
            raise RuntimeError(
                f"The code {code} is used by both {class_name} and {codes[code]}."
            )
        codes[code] = class_name


class QIException(Exception):
    def __init__(
        self,
        title: str,
        code: str,
        http_status: int,
        description: str,
        translation: str,
        errors: list[dict] | None = None,
    ) -> None:
        super().__init__(description)
        self.title = title
        self.description = description
        self.translation = translation
        self.code = code
        self.http_status = http_status
        self.errors = errors or []


class MethodNotAllowed(QIException):
    code = "BNK000405"

    def __init__(self) -> None:
        super().__init__(
            "Method not allowed",
            self.code,
            405,
            "The requested method is not supported.",
            "O método solicitado não é permitido.",
        )


class InternalError(QIException):
    code = "BNK000500"

    def __init__(self) -> None:
        super().__init__(
            "Internal Error",
            self.code,
            500,
            "An internal error has occurred and is being investigated.",
            "Ocorreu um erro interno e ele está sendo investigado.",
        )


class NotFoundResource(QIException):
    code = "BNK000404"

    def __init__(self) -> None:
        super().__init__(
            "Resource not found",
            self.code,
            404,
            "The requested resource was not found.",
            "O recurso solicitado não foi encontrado.",
        )


class InvalidSchema(QIException):
    code = "BNK000001"

    def __init__(self, description: str, errors: list[dict] | None = None) -> None:
        super().__init__(
            "Bad Request",
            self.code,
            400,
            description,
            "O corpo ou parâmetro da requisição é inválido.",
            errors,
        )


class ForbiddenNotInternal(QIException):
    code = "BNK000002"

    def __init__(self) -> None:
        super().__init__(
            "Forbidden",
            self.code,
            403,
            "Request must be internal.",
            "Requisição não autorizada.",
        )
