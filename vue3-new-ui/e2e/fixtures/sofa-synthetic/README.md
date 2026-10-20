These synthetic daily DTOs were exported from the actual SQLAlchemy in-memory
fixtures and the actual SOFA router detail/candidates implementations. They contain
no hospital data and were not assembled by a browser mock. `daily-create.json` is
the exact clinical request used for that actual assessment. The frozen revoked
wrapper preserves the original active public projection and its original hash;
current revocation governance is separate.

Browser tests mock HTTP transport and cannot establish backend authorization or
clinical validation. The structural contract examples in `sofa-contract-fixtures.cjs`
come from actual Pydantic validation; they are not ORM assessment fixtures or a
scoring oracle. Numerical analyses will use actual typed pure model output.
