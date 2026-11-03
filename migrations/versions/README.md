`0001_create_accounts.py` is the initial revision. It creates `banking.accounts`
for `SAVINGS_ACCOUNT`, with named constraints, server defaults and a customer index.
Downgrade drops only the Accounts table and index; the shared banking schema is
preserved. Do not edit revisions after they have been applied.

`0002_create_transactions.py` follows it and adds banking.transactions and
banking.account_movements with numeric types, checks, FKs and indexes. Its
downgrade removes only these two tables and their indexes, retaining Accounts.
