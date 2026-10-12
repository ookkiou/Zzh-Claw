from .amounts import amount


class Ledger:
    def __init__(self, balances):
        self.balances = dict(balances)
        self.receipts = {}

    def transfer(self, key, source, target, value):
        value = amount(value)
        signature = (source, target, value)
        if key in self.receipts:
            old_signature, receipt = self.receipts[key]
            if old_signature != signature:
                raise ValueError("idempotency conflict")
            return dict(receipt)
        if (
            source == target
            or source not in self.balances
            or target not in self.balances
        ):
            raise ValueError("invalid account")
        if self.balances[source] < value:
            raise ValueError("insufficient funds")
        self.balances[source] -= value
        self.balances[target] += value
        receipt = {"key": key, "source": source, "target": target, "amount": value}
        self.receipts[key] = (signature, receipt)
        return dict(receipt)
