CPF_LENGTH = 11
CNPJ_LENGTH = 14

CHECK_DIGIT_POSITIONS = [9, 10]


def is_valid_cpf(document_number: str) -> bool:
    digits = []
    for character in document_number:
        if character.isdigit():
            digits.append(int(character))

    if len(digits) != CPF_LENGTH:
        return False

    all_digits_are_equal = True
    for digit in digits:
        if digit != digits[0]:
            all_digits_are_equal = False
            break

    if all_digits_are_equal:
        return False

    for position in CHECK_DIGIT_POSITIONS:
        total = 0
        first_weight = position + 1

        for index in range(position):
            total = total + digits[index] * (first_weight - index)

        remainder = total % 11

        if remainder < 2:
            expected_digit = 0
        else:
            expected_digit = 11 - remainder

        if digits[position] != expected_digit:
            return False

    return True


def is_valid_cnpj(document_number: str) -> bool:
    digits = [int(character) for character in document_number if character.isdigit()]

    if len(digits) != CNPJ_LENGTH or len(set(digits)) == 1:
        return False

    weights = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    first_sum = sum(digit * weight for digit, weight in zip(digits[:12], weights))
    first_digit = 0 if first_sum % 11 < 2 else 11 - first_sum % 11

    weights = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    second_sum = sum(digit * weight for digit, weight in zip(digits[:13], weights))
    second_digit = 0 if second_sum % 11 < 2 else 11 - second_sum % 11

    return digits[-2:] == [first_digit, second_digit]


def is_valid_document_number(document_number: str) -> bool:
    digits = "".join(character for character in document_number if character.isdigit())
    if len(digits) == CPF_LENGTH:
        return is_valid_cpf(document_number)
    if len(digits) == CNPJ_LENGTH:
        return is_valid_cnpj(document_number)
    return False


def mask_document(document: str | None) -> str:
    if not document:
        return "***"
    digits = "".join(ch for ch in document if ch.isdigit())
    if len(digits) == 11:
        return f"***.***.{digits[6:9]}-**"
    if len(digits) == 14:
        return f"**.***.***/{digits[8:12]}-**"
    if len(document) > 4:
        return f"***{document[-4:]}"
    return "***"
