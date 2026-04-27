# Supported Modes

## Primary adapters

- `python`
- `tsjs`
- `generic`

## Supplemental adapters

- `sql_postgres`

## Profiles

Working daily-use profiles:

- `python-basic`
- `node-cli`
- `react-vite`

Setup-ready profiles:

- `next-basic`
- `electron-renderer`
- `obsidian-plugin`
- `tauri-frontend`

## Fallback

`generic` is file-level only. It is valid, but lower completeness than symbol-level modes.

## Architecture-contract surfaces

The skill includes lightweight repo-local support for contract nodes and edges
such as:

- endpoints and routes
- components and props
- events
- env vars and config keys
- SQL tables
- IPC channels
- Obsidian commands
- Playwright flows

When a dependency is real but the exact edge type is uncertain, the graph may
fall back to `DEPENDS_ON` with reduced confidence.
