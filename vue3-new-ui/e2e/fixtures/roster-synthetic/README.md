These are synthetic records exported from the actual in-memory SQLAlchemy source
service, the mounted application router, and JWT-authorized ASGI requests. No
hospital database, `.env`, external credential service, optimizer, or model call
was used. IDs, original and governance hashes, UTC clocks, flags, and payloads
were produced by the real service; tests never construct substitute proofs.

`sources.json` is the unmodified export from
`/tmp/hoim-roster-ui-real-source-fixtures.json` (source exporter: one passing real
ORM/JWT/ASGI test, 6.69 seconds). The four `drafts` and `published` records keep
the same IDs and original hashes through publication. They include an unknown
job key, an external duty, a break with `counted_as_work: false`, unknown
availability, a known zero minute limit, missing rolling limits, and a fixed
window with a known zero minimum. `admin_list` is a real metadata-only response.
Its `stale_redacted` key was captured before the stricter note redaction contract;
it is retained only as a rejected legacy receipt, never as an accepted current
redaction fixture.

`terminal.json` is the unmodified final export from
`/tmp/hoim-roster-ui-real-terminal-fixtures.json` (one passing actual test,
7.04 seconds; source implementation `43a0362`). It includes independent real
publish, reject, revoke and stale-parent lifecycles. Every transition keeps its
own original ID and hash. Ordinary redacted details have `payload`,
`parent_binding`, `review_basis_note`, and `revoke_reason` all null; full original
and governance proofs remain available only in the authorized Super audit.
The review and revoke request bodies are also actual requests, so UI tests bind
the returned CAS state and governance digest to the exact submitted evidence.

The loopback harness compiles actual Vue source components and uses the real
request client. API traffic must be explicitly intercepted; unexpected requests
fail closed. It does not rebuild `dist`. Metadata derived for transport mocks
only drops the four private fields exactly as the real list endpoint does.
