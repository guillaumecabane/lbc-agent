# Hermes Agent integration (optional)

`enqueue_listing.py` turns one physical item into a manifest (`$LBC_HOME/items/<slug>/manifest.json`)
and a three-task Kanban graph on a Hermes Agent board: intake (one of several parallel intake
profiles) → publisher (serialized browser writer) → verifier (independent read-back). It requires
the `hermes` CLI with the kanban feature and is configured entirely through `LBC_*` environment
variables (see the module docstring and `.env.example`).

```bash
python3 integrations/hermes/enqueue_listing.py --slug example-item --title "Example item" \
  --source "operator message + photo paths" [--photo items/example-item/01.jpg] \
  [--blocked "Confirm mains safety test"] [--expert]
```

Tasks run with `$LBC_HOME` as their workspace and refer to `scripts/...` relative paths, so keep
`LBC_HOME` at the repository root (the default) when using this integration.
