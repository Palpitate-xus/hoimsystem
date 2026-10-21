These production entry tests load the canonical `dist` through a private static
HTTP server with no backend or proxy. Every API response is intercepted synthetic
data. They verify the built Vue application, request client, private proofs and
native calculation checks, rather than a browser connection to a native service.

`production-entry.json` is the exact output of the guarded same-case export
`/tmp/hoim_supply_native_entry_export_v3.py`. SHA-256:
`38ca5822fdabfe0e5ffd6bf3291f1ff001930830e1b287f84096942b58c2376d`.
Actual memory SQLite/JWT/ASGI calls produced the five task states, live and revoked
Series, complete Source originals, pharmacy catalogs, management lists, and
metadata-only provider check. The deliberately mismatched provider was saved
after task execution, then checked through actual native ASGI `GET /capabilities`.
No hospital data or operational outcome validation is represented.

`production-complete.json` is a lossless representation of a separate same-case
complete 336-original pipeline export. Its own manifest records raw and canonical
SHA-256 and bytes. `supply-production-complete.cjs` checks every shared subtree and
the entire packet before returning independent JSON trees. Run that file with
`--check` to compare against the guarded `/tmp` export. The complete production
test uses that case's own business catalog, live Series, H14 receipt and full task;
it never combines identities or hashes from the partial case.

UI user bootstrap credentials are fixed synthetic setup. Tests do not approve
deployment, validate hospital forecasts, modify stock or save provider settings.
