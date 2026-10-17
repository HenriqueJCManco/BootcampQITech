from models import Account, BankTransaction, Customer, LedgerEntry, TrustedContact


class CustomerDTO:
    @staticmethod
    def to_dict(customer: Customer) -> dict:
        return {
            "customer_key": str(customer.customer_key),
            "name": customer.name,
            "email": customer.email,
            "document_number": customer.document_number,
            "created_at": customer.created_at.isoformat(),
        }


class AccountDTO:
    @staticmethod
    def to_dict(account: Account) -> dict:
        return {
            "account_key": str(account.account_key),
            "customer_key": str(account.customer.customer_key),
            "balance_cents": account.balance_cents,
            "transfer_limit_cents": account.transfer_limit_cents,
            "blocked_mcc_list": sorted(blocked.mcc.strip() for blocked in account.blocked_mccs),
            "created_at": account.created_at.isoformat(),
        }


class TrustedContactDTO:
    @staticmethod
    def to_dict(contact: TrustedContact) -> dict:
        return {
            "contact_key": str(contact.contact_key),
            "name": contact.name,
            "channel": contact.channel,
            "address": contact.address,
            "created_at": contact.created_at.isoformat(),
        }


class LedgerEntryDTO:
    @staticmethod
    def to_dict(entry: LedgerEntry) -> dict:
        return {
            "entry_key": str(entry.entry_key),
            "transaction_key": str(entry.transaction.transaction_key),
            "transaction_type": entry.transaction.type,
            "direction": entry.direction,
            "kind": entry.kind,
            "amount_cents": entry.amount_cents,
            "mcc": entry.mcc.strip() if entry.mcc else None,
            "balance_after_cents": entry.balance_after_cents,
            "entry_datetime": entry.entry_datetime.isoformat(),
        }


class TransactionDTO:
    @staticmethod
    def response(transaction: BankTransaction, entries: list[LedgerEntry]) -> dict:
        balances = {entry.account_id: entry.balance_after_cents for entry in entries}
        result = {
            "transaction_key": str(transaction.transaction_key),
            "amount_cents": transaction.amount_cents,
            "fee_cents": transaction.fee_cents,
        }
        if transaction.type == "TRANSFER":
            result["from_balance_cents"] = balances[transaction.from_account_id]
            result["to_balance_cents"] = balances[transaction.to_account_id]
        else:
            result["balance_cents"] = balances[
                transaction.from_account_id or transaction.to_account_id
            ]
        return result
