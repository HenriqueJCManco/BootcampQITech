from errors.base_error import QIException


class PixInvalidSchema(QIException):
    code = "AFP000001"

    def __init__(self, errors: list[dict] | None = None) -> None:
        super().__init__(
            "Bad Request",
            self.code,
            400,
            "The request body, header or parameter is not in the expected format.",
            "O corpo, cabeçalho ou parâmetro da requisição está fora do formato.",
            errors,
        )


class PixForbidden(QIException):
    code = "AFP000002"

    def __init__(self) -> None:
        super().__init__(
            "Forbidden",
            self.code,
            403,
            "The INTERNAL-TOKEN header is missing or invalid.",
            "O cabeçalho INTERNAL-TOKEN está ausente ou é inválido.",
            [{"field": "INTERNAL-TOKEN", "rule": "required", "message": "A valid internal token is required."}],
        )


class PixAnalysisNotFound(QIException):
    code = "AFP000003"

    def __init__(self) -> None:
        super().__init__(
            "Analysis not found",
            self.code,
            404,
            "No analysis was found for this Pix id.",
            "Nenhuma análise foi encontrada para este id de Pix.",
            [{"field": "id", "rule": "exists", "message": "Analysis does not exist."}],
        )


class PixIdempotencyConflict(QIException):
    code = "AFP000004"

    def __init__(self) -> None:
        super().__init__(
            "Pix id conflict",
            self.code,
            409,
            "This Pix id was already analysed with a different body.",
            "Este id de Pix já foi analisado com um corpo diferente.",
            [{"field": "id", "rule": "request_hash", "message": "Use a new id for a different request."}],
        )


class PixInvalidDocument(QIException):
    code = "AFP000005"

    def __init__(self, field: str = "document") -> None:
        super().__init__(
            "Invalid document number",
            self.code,
            422,
            "The CPF or CNPJ check digits are invalid.",
            "Os dígitos verificadores do CPF ou CNPJ são inválidos.",
            [{"field": field, "rule": "check_digits", "message": "Document check digits are invalid."}],
        )


class PixInvalidTransactionDate(QIException):
    code = "AFP000006"

    def __init__(self, rule: str = "timezone") -> None:
        super().__init__(
            "Invalid transaction date",
            self.code,
            400,
            "The transaction_date must carry a timezone offset and cannot be in the future.",
            "A transaction_date precisa ter fuso horário e não pode estar no futuro.",
            [{"field": "transaction_date", "rule": rule, "message": "Value must have a timezone and not be in the future."}],
        )


class PixInvalidChannel(QIException):
    code = "AFP000007"

    def __init__(self) -> None:
        super().__init__(
            "Invalid channel",
            self.code,
            422,
            "The source channel is not one of the accepted values.",
            "O canal de origem não é um dos valores aceitos.",
            [
                {
                    "field": "source.channel",
                    "rule": "enum",
                    "message": "Value must be internet, celular, computador, tablet or relogio.",
                }
            ],
        )


class PixInvalidAmount(QIException):
    code = "AFP000008"

    def __init__(self) -> None:
        super().__init__(
            "Invalid amount",
            self.code,
            400,
            "The amount must be an integer greater than or equal to one cent.",
            "O valor deve ser um número inteiro de pelo menos um centavo.",
            [{"field": "amount", "rule": "minimum", "message": "Value must be an integer of at least 1."}],
        )


class PixLockTimeout(QIException):
    code = "AFP000009"

    def __init__(self) -> None:
        super().__init__(
            "Payer lock timeout",
            self.code,
            503,
            "The payer is busy. Retry the request with the same Pix id.",
            "O pagador está ocupado. Tente novamente com o mesmo id do Pix.",
        )


