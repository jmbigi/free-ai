# Tarea: Procesar transacciones bancarias

Implementa en Python una función llamada `process_transactions(transactions)` que reciba una lista de diccionarios y devuelva un diccionario con el resultado.

Cada transacción es un diccionario con las claves:
- `"type"`: string, puede ser `"deposit"` o `"withdraw"` (otros valores se ignoran)
- `"amount"`: entero

Reglas:
1. Saldo inicial: 0
2. `"deposit"`: siempre válido. Se suma al balance y se agrega a `valid_transactions`.
3. `"withdraw"`: solo válido si `amount <= balance_actual`. Si es válido, se resta al balance y se agrega a `valid_transactions`. Si el balance es insuficiente, se ignora completamente.
4. Cualquier otro tipo se ignora.
5. El orden de las transacciones en `valid_transactions` debe ser el mismo que aparecen en la entrada.

Retorna un diccionario:
```python
{
    "balance": <int>,
    "valid_transactions": <lista de diccionarios originales>
}
```
