# M14 Studio Runtime Integration Plan

M14 connects the Audio Story Studio presentation layer to the existing Python
runtime and SQLite authority without changing canonical v3.16.13 artifacts.

## Scope

- Serve `ui/dist` and a versioned JSON API from one Python process.
- Bind only to `127.0.0.1` or `localhost`.
- Project the latest workflow, stages, deterministic progress, transactions,
  generation calls, committed artifacts, current gates, and append-only events.
- Keep the UI API read-only until a workflow runner owns generation actions.
- Update `open_app.bat` to launch the integrated server against a selected
  workspace.

## Definition of Done

- Empty and populated SQLite workspaces project deterministically.
- Static paths cannot escape the UI directory.
- Non-loopback bindings and invalid ports fail closed.
- The UI refreshes from `/api/v1/studio` and reports connection failures.
- Repository quality gates pass and the canonical prompt hash is unchanged.
