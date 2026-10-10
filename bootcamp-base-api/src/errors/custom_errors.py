from errors.base_error import QIException


class MissingIdempotencyKey(QIException):
    code = "BNK000011"

    def __init__(self) -> None:
        super().__init__(
            "Idempotency key required",
            self.code,
            400,
            "The Idempotency-Key header is required.",
            "Informe o cabeçalho Idempotency-Key.",
            [{"field": "Idempotency-Key", "rule": "required", "message": "Header is required."}],
        )


class IdempotencyConflict(QIException):
    code = "BNK000012"

    def __init__(self) -> None:
        super().__init__(
            "Idempotency key conflict",
            self.code,
            409,
            "This Idempotency-Key was already used for a different request.",
            "Essa chave de idempotência já foi usada em outra requisição.",
            [{"field": "Idempotency-Key", "rule": "request_hash", "message": "Use a new key for a different request."}],
        )


class DuplicateCustomer(QIException):
    code = "BNK001002"

    def __init__(self) -> None:
        super().__init__(
            "Customer already registered",
            self.code,
            409,
            "A customer with this document or email is already registered.",
            "Já existe um cliente com esse documento ou e-mail.",
        )


class InvalidCustomerDocument(QIException):
    code = "BNK001003"

    def __init__(self) -> None:
        super().__init__(
            "Invalid document number",
            self.code,
            422,
            "The document check digits are invalid.",
            "Os dígitos verificadores do documento são inválidos.",
            [{"field": "document_number", "rule": "check_digits", "message": "Document check digits are invalid."}],
        )


class NotFoundCustomer(QIException):
    code = "BNK001004"

    def __init__(self) -> None:
        super().__init__("Customer not found", self.code, 404, "The customer was not found.", "Cliente não encontrado.")


class NotFoundAccount(QIException):
    code = "BNK002001"

    def __init__(self) -> None:
        super().__init__("Account not found", self.code, 404, "The account was not found.", "Conta não encontrada.")


class CustomerAlreadyHasAccount(QIException):
    code = "BNK002002"

    def __init__(self) -> None:
        super().__init__(
            "Customer already has an account",
            self.code,
            409,
            "This customer already has an account.",
            "Este cliente já possui uma conta.",
        )


class InvalidTransferLimit(QIException):
    code = "BNK002003"

    def __init__(self) -> None:
        super().__init__(
            "Invalid transfer limit",
            self.code,
            400,
            "The transfer limit must be greater than or equal to one cent.",
            "O limite por transferência deve ser de pelo menos um centavo.",
            [{"field": "transfer_limit_cents", "rule": "minimum", "message": "Value must be at least 1."}],
        )


class InvalidMCCList(QIException):
    code = "BNK002004"

    def __init__(self) -> None:
        super().__init__(
            "Invalid MCC list",
            self.code,
            400,
            "Every MCC must contain exactly four digits.",
            "Cada MCC deve conter exatamente quatro dígitos.",
            [{"field": "mcc_list", "rule": "pattern", "message": "Each MCC must contain four digits."}],
        )


class TrustedContactLimitReached(QIException):
    code = "BNK003001"

    def __init__(self) -> None:
        super().__init__(
            "Trusted contact limit reached",
            self.code,
            409,
            "An account can have at most two trusted contacts.",
            "A conta pode ter no máximo dois contatos de confiança.",
        )


class DuplicateTrustedContact(QIException):
    code = "BNK003002"

    def __init__(self) -> None:
        super().__init__(
            "Trusted contact already registered",
            self.code,
            409,
            "This address is already registered for the account.",
            "Este endereço já está cadastrado nesta conta.",
        )


class InsufficientFunds(QIException):
    code = "BNK004001"

    def __init__(self, balance_cents: int, required_cents: int) -> None:
        super().__init__(
            "Insufficient funds",
            self.code,
            409,
            "The available balance is below the amount required for this operation.",
            "O saldo disponível é menor que o valor necessário para esta operação.",
            [
                {"field": "balance_cents", "rule": "minimum", "message": f"Current balance: {balance_cents}."},
                {"field": "amount_cents", "rule": "minimum", "message": f"Required amount: {required_cents}."},
            ],
        )


class SameAccountTransfer(QIException):
    code = "BNK004002"

    def __init__(self) -> None:
        super().__init__(
            "Invalid transfer",
            self.code,
            422,
            "The source and destination accounts must be different.",
            "A conta de origem e a de destino devem ser diferentes.",
        )


class TransferLimitExceeded(QIException):
    code = "BNK004003"

    def __init__(self) -> None:
        super().__init__(
            "Transfer limit exceeded",
            self.code,
            422,
            "The requested amount exceeds the account transfer limit.",
            "O valor solicitado excede o limite por transferência da conta.",
        )


class BlockedByVault(QIException):
    code = "BNK004004"

    def __init__(self) -> None:
        super().__init__(
            "Operation blocked by MCC protection",
            self.code,
            422,
            "The operation matches an MCC blocked for this account.",
            "A operação corresponde a um MCC bloqueado para esta conta.",
        )


class InvalidMerchantDocument(QIException):
    code = "BNK004005"

    def __init__(self) -> None:
        super().__init__(
            "Invalid merchant document",
            self.code,
            422,
            "The merchant document check digits are invalid.",
            "Os dígitos verificadores do CNPJ do estabelecimento são inválidos.",
        )


class InvalidAmount(QIException):
    code = "BNK004006"

    def __init__(self) -> None:
        super().__init__(
            "Invalid amount",
            self.code,
            400,
            "The amount must be an integer greater than or equal to one cent.",
            "O valor deve ser um número inteiro de pelo menos um centavo.",
            [{"field": "amount_cents", "rule": "minimum", "message": "Value must be at least 1."}],
        )


class LockWaitTimeout(QIException):
    code = "BNK004007"

    def __init__(self) -> None:
        super().__init__(
            "Account lock timeout",
            self.code,
            503,
            "The account is busy. Retry the request with the same Idempotency-Key.",
            "A conta está ocupada. Tente novamente com a mesma Idempotency-Key.",
        )
