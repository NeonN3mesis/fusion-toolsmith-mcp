# Safety Model

Fusion Toolsmith MCP is designed for agent-assisted CAD work where accidental mutation is a real risk.

## Defaults

- The add-in is opt-in and keeps `runOnStartup` set to `false`.
- Fusion API calls execute on Fusion's main thread through `TaskManager`.
- Streamable HTTP requires bearer/query-token auth. Query-token auth remains for legacy SSE clients.
- `/health` is token-free but does not expose tokens or `sse_url`.
- Dangerous tools are separated from normal profiles in `tool_profiles.json`.

## Tool-First Workflow

Agents should inspect and plan before editing:

1. Call `doctor`.
2. Inspect the active design.
3. Use structured tools whenever possible.
4. Run `preflight_model_change` before risky model edits.
5. Run `preflight_export` before exports.
6. Validate after changes.
7. Use `run_fusion_script` only as a last resort with `script_intent` and `mcp_tool_gap`.

The same guidance is exposed through initialize instructions and `fusion://agent/tool-first-workflow`.

## Change Journal

FusionMCP writes local JSONL tool-call audit entries to:

```text
C:\Users\<you>\.fusion_mcp\journal.jsonl
```

Read it through MCP:

```text
fusion://runtime/change-journal
```

Or call:

```text
get_change_journal
clear_change_journal
```

The journal redacts tokens, authorization headers, raw scripts, and long string arguments. `run_fusion_script` entries include before/after design-state comparison metadata so the journal can report whether the script changed the model.

## Local Docs Resource

FusionMCP exposes a local Fusion API and best-practices index:

```text
fusion://docs/fusion-api
```

Search it with:

```text
search_local_fusion_docs
```

This is an offline companion to official Autodesk docs and is meant for quick planning before writing raw Fusion API scripts.
