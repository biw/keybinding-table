# Evidence records

`observations.json` is intentionally empty until a manually dispatched
workflow produces reviewed results. Do not manufacture records from the
existing README table.

Workflow artifacts contain the run-specific observation JSON, screenshots, and
Markdown summary. After review, merge approved observation records into this
directory and use their source IDs in the table. Validate any change with:

```sh
node scripts/validate-evidence.mjs
```

An `observed` result is only a fact for its stated browser build, OS build,
U.S. keyboard layout, clean profile, and textarea focus state. `os-level`
records are Windows-logo-key behavior; the browser receives no ownership claim.
