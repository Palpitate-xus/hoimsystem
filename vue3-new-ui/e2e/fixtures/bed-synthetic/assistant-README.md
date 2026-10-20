These records contain only isolated synthetic engineering data.

`assistant-frozen.json` is an exact field extraction from
`/tmp/hoim-bed-pipeline-ui-final2-fixtures.json`. Its `origin_sha256` binds that
original export. To avoid repeating large proofs, the helper reconstructs the
unchanged `bed_findings`, result analysis and evidence from the committed
`pipeline-7.json` and `pipeline-14.json`. The extraction and a separate Node
`assert.deepStrictEqual` check compare both complete run details, both operational
inspections and the full source-series detail with the actual final2 export.
Identity, original quantities, clocks, governance and hashes are not regenerated.

`assistant-queued-serializer.json` and `assistant-receipt-states.json` are a
different evidence layer: the real backend `runtime.describe_run(False)` and
FastAPI `jsonable_encoder` serialized in-memory AIRun objects rehydrated from
those same original frozen requests and metadata. Only the synthetic status was
chosen as queued/running/succeeded. They are not evidence of a real HTTP queue
call, a persisted state transition, or a concurrent worker race. The tests
explicitly intercept the POST transport with these real serializer outputs, then
serve the unmodified, complete final2 native result for the same run ID and
context digest. Negative tests deliberately alter transport fields.

`assistant-partial-inspection.json` preserves metadata from the actual partial
series exported at `/tmp/hoim-bed-partial-findings-ui.json`. It uses the real
`ContextBundle`, `context_metadata` and `bed_evidence` serializers over that exact
frozen short context. The large original source and snapshot remain shared with
`pipeline-partial.json`; nullable quantities and unknown original declarations
are retained. No new clinical facts or complete historical observations are
invented for the preview.

`bed-assistant-harness.cjs` compiles the real AIAssistant, AIBedInput and
AIBedFindings in the worktree with their actual request, hash and mathematical
guards. It uses a temporary loopback server and the existing dependency tree.
All APIs are explicit synthetic interception; other origins and unknown API
paths fail closed. The cases are isolated mock browser tests, not production
entry tests or real hospital HTTP tests. No production dist, hospital service,
.env file, dependency installation or actual operational validation is used.
