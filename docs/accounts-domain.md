# Accounts domain — Phase 1

The Accounts module follows CRP's `domain/<module>/entities.py` and `enums.py`
layout, frozen dataclasses, `StrEnum`, constructor validation, and parametrized
pytest tests. CRP uses `ValueError` for domain validation; Accounts defines
`InvalidAccountData` and `InvalidAccountStateTransition` as specific subclasses.
CRP represents values with standard Python types and frozen dataclasses, and
repository interfaces with `Protocol` under `ports/`. No account repository or
new value-object abstraction is needed in this phase. CRP remains read-only and
is not a runtime dependency.

`Account.create()` generates a UUID and UTC creation/update timestamps and always
creates an ACTIVE account without a closing date. Callers supply the customer
UUID, account number, currency, and opening date. Product type defaults to the
only supported classification, `SAVINGS_ACCOUNT`. `CURRENT_ACCOUNT` and the old
`SAVING_ACCOUNT` spelling are unsupported. UUID strings and
raw enum strings must be converted by the calling boundary before construction.

Direct `Account(...)` construction validates supplied data and preserves its
status, identity, dates, and timestamps, including historical BLOCKED and CLOSED
accounts. CLOSED accounts require a closing date on or after the opening date;
ACTIVE and BLOCKED accounts cannot have a closing date. There is no closure
operation: future ledger integration must validate balances and pending work.

Instances are frozen, including product type, currency, and status. Transitions
return validated snapshots with a fresh UTC update timestamp; callers retain
the returned instance:

```python
account = account.block()  # ACTIVE -> BLOCKED
account = account.reactivate()  # BLOCKED -> ACTIVE
```

Other transitions, including repeated block/reactivate calls and reactivation
of CLOSED accounts, raise `InvalidAccountStateTransition`. Existing snapshots
are unchanged. `validate()` checks the same invariants used during construction.

Currency validation requires an already normalized string of exactly three
uppercase ASCII letters. Lowercase and padded codes are rejected. Neither CBS
nor CRP supplies an established currency registry, so **ISO 4217 membership is
not yet verified**; a format-valid value such as `ZZZ` is currently accepted.
Account numbers must be nonblank strings; no bank-specific numbering format is
assumed. Account-number uniqueness and customer existence require future ports
and application logic and are outside this entity's scope.

Phase 1 introduced the domain, unit tests, and documentation. Phase 2 renames the
product classification and adds separate [persistence](accounts-persistence.md).
Phase 4 adds separate [application use cases](accounts-application.md). APIs,
balances, and ledger behavior remain deferred.
