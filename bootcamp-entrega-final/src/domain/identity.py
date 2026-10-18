import hashlib


def only_digits(document: str) -> str:
    return "".join(character for character in document if character.isdigit())


def document_hash(document: str) -> str:
    return hashlib.sha256(only_digits(document).encode("utf-8")).hexdigest()


def mask_document(document: str) -> str:
    digits = only_digits(document)
    if len(digits) <= 4:
        return "*" * len(digits)
    return f"{digits[:3]}{'*' * (len(digits) - 5)}{digits[-2:]}"


def destination_key(participant: str, branch: str, account: str, document: str) -> str:
    raw = "|".join([participant.strip(), branch.strip(), account.strip(), only_digits(document)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
