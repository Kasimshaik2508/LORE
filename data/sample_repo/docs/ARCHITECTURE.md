# Payflow architecture

Payflow is a small payments platform made of five services.

- **payments_api** is the public REST API. It creates charges and refunds.
- **ledger_service** records every debit and credit. It is the source of truth for balances.
- **webhooks_service** receives payment-provider callbacks.
- **reporting_service** builds daily finance reports from a read replica.
- **authentication_service** (`auth_service/`) verifies API tokens for every request.

All payment state lives in **payments-db** (PostgreSQL). User accounts live in **users-db**.

Decision: Every service must authenticate requests through authentication_service rather than validating tokens locally.
Why: Revocation has to take effect everywhere at once.
Affects: authentication_service, payments_api, webhooks_service
