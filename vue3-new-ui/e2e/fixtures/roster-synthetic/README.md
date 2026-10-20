These are synthetic records exported from the actual in-memory SQLAlchemy source
service, the mounted application router, and JWT-authorized ASGI requests. No
hospital database, `.env`, or external credential service was used. IDs,
original and governance hashes, UTC clocks, flags, and payloads
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

`plans.json` is the final actual ORM plan lifecycle export from
`/tmp/hoim-roster-plan-ui-real-fixtures.json` (one passing test, 7.29 seconds,
source `c9c6271`, native core `5bfa663`). It retains the complete four-person
cohort, including a doctor without an old recurring schedule, every person and
session pair, current collection digest, and distinct publication, rejection,
revocation and stale-fact lifecycles. Missing coverage remains unknown.
`plan-options.json` is a separate real JWT/ASGI directory export from a matching
synthetic ORM case (one passing test, 6.90 seconds); its department and complete
doctor ID set were asserted equal to the original request. It is not presented
as a query against the earlier, already closed in-memory process.

`pipeline.json` and `pipeline-plan.json` are the actual mounted HTTP, durable
queue, native schema-10 ASGI, blob and authorized detail/trace export from Root's
final backend (`118c76a`), including the same live plan ID and its actual options.
The immutable task contains only a short binding; authorized detail expands the
complete frozen plan, public projection and original governance proof. This
case intentionally returns `input_unknown` rather than inventing a feasible plan.

`feasible-meet.json` and `feasible-slots.json` are separate complete actual
JWT/HTTP source creation and Super publication, plan preview/capture/publication,
durable worker, native ASGI, authorized detail and trace flows. The two export
tests passed in 9.98 seconds. Each has its own real plan ID and proof chain;
the dedicated synthetic department has one doctor, explicit qualifications,
availability, known work rules and complete coverage. Both searches exhausted
their definite and relaxed graphs and proved an optimum. Actual planned service
is 5 and 8 respectively, with penalty 2. The meet-target objective keeps its
objective `planned_slots` null because only penalty is ranked in that objective.
The files are unmodified exports from `/tmp/hoim-roster-feasible-meet-ui-real.json`
and `/tmp/hoim-roster-feasible-slots-ui-real.json`.

`core-meet.json` and `core-slots.json` contain actual final typed native model
inputs and computed results, without a hospital plan proof. They exercise only
the public analysis API guard; the UI always additionally requires a complete
authorized plan. `capabilities.json` is the actual isolated Docker
`GET /capabilities` receipt from the final container verification. Its runtime
model digest reflects the container's actual Python and timezone environment;
it is not substituted with the host runtime digest.

The loopback harness compiles actual Vue source components and uses the real
request client. API traffic must be explicitly intercepted; unexpected requests
fail closed. It does not rebuild `dist`. Metadata derived for transport mocks
only drops the four private fields exactly as the real list endpoint does.
