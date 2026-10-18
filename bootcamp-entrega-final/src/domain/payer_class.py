import re
import unicodedata

from domain.config import EngineConfig
from domain.identity import only_digits
from utils.document_number import is_valid_cpf


PF = "PF"
MEI = "MEI"
PJ = "PJ"

TRAILING_DIGITS = re.compile(r"(\d+)$")


def normalize_name(name: str) -> str:
    without_accents = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(without_accents.upper().split())


def has_company_suffix(normalized_name: str, suffixes: list[str]) -> bool:
    for suffix in suffixes:
        pattern = r"(^|[\s.])" + re.escape(suffix.upper()) + r"($|[\s.])"
        if re.search(pattern, normalized_name):
            return True
    return False


def classify_payer(document: str, name: str | None, config: EngineConfig) -> tuple[str, dict]:
    digits = only_digits(document)
    if len(digits) == 11:
        return PF, {}

    if name is None:
        return PJ, {"reason": "name_missing"}

    params = config.params["mei"]
    normalized = normalize_name(name)

    if has_company_suffix(normalized, params["sufixos_veto"]):
        return PJ, {"matched": "company_suffix"}

    compact = re.sub(r"[\s./-]", "", normalized)
    trailing = TRAILING_DIGITS.search(compact)
    if trailing is None:
        return PJ, {}

    tail = trailing.group(1)
    if params.get("cpf_no_fim_do_nome") and len(tail) >= 11 and is_valid_cpf(tail[-11:]):
        return MEI, {"matched": "cpf_suffix"}
    if params.get("raiz_cnpj_no_fim_do_nome") and len(tail) >= 8 and tail[-8:] == digits[:8]:
        return MEI, {"matched": "cnpj_root_suffix"}
    return PJ, {}
