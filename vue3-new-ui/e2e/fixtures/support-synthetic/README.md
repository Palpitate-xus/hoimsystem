These are synthetic source DTOs exported through actual in-memory SQLAlchemy
fixtures and the generic source router's `detail` function. They contain no
hospital patient data and no model outputs or clinical performance claims.

MAP, respiratory support and arterial pairing use the source fixtures in
`fastapi_be/tests/test_inpatient_respiratory_sources.py`; the vasoactive interval
and its published/draft mapping use `test_inpatient_vasoactive.py` and
`test_ai_vasoactive_mappings.py`. Original full payloads, six-digit UTC clocks,
fixed native decimal strings, original dependency snapshots, and backend SHA-256
content/governance hashes are retained for browser contract regression.

`support-fixtures.cjs` separately generates synthetic write receipts and CAS
transitions for API-mocked UI tests. Those receipts are not real clinical data.
