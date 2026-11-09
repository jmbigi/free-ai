def process_transactions(transactions):
    balance = 0
    valid_transactions = []
    for tx in transactions:
        ttype = tx.get("type")
        amount = tx.get("amount", 0)
        if ttype == "deposit":
            balance += amount
            valid_transactions.append(tx)
        elif ttype == "withdraw":
            if amount <= balance:
                balance -= amount
                valid_transactions.append(tx)
    return {"balance": balance, "valid_transactions": valid_transactions}