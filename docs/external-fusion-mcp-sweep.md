# External Fusion MCP Sweep

This note tracks public Fusion 360 MCP patterns worth watching and the concrete Toolsmith responses already implemented. Keep it current when reviewing other servers; do not add project-specific geometry or demo-only workflows here.

## Public Servers Reviewed

- `frankhommers/autodesk-fusion-mcp`
  - Source: https://github.com/frankhommers/autodesk-fusion-mcp
  - Noteworthy pattern: standalone Fusion add-in using Streamable HTTP with no external proxy.
  - Toolsmith response: keep legacy SSE compatibility, add Streamable HTTP support metadata, bearer auth, health/discovery reporting, initialize instructions, and offline schema export.

- `faust-machines/fusion360-mcp-server`
  - Source: https://github.com/faust-machines/fusion360-mcp-server
  - Noteworthy pattern: packaged public server for coding-agent workflows, with PyPI availability and broad client positioning.
  - Toolsmith response: strengthen CLI packaging, live smoke tests, `doctor`, `dump-schemas`, README install/verify flow, and GitHub-ready docs.

- `ndoo/fusion360-mcp-bridge`
  - Source: https://github.com/ndoo/fusion360-mcp-bridge
  - Noteworthy pattern: very small bridge with raw script execution plus screenshot capture.
  - Toolsmith response: retain raw scripting as a fallback only, require `script_intent` and `mcp_tool_gap`, add viewport capture/demo sequence tools, and add tool-first guidance.

- `JustusBraitinger/FusionMCP`
  - Source: https://github.com/JustusBraitinger/FusionMCP
  - Noteworthy pattern: conversational CAD framing and parameter-focused automation.
  - Toolsmith response: add stronger parameter workflows, parameter CSV import/export, structured prompts, and profile-based tool exposure.

- `Joe-Spencer/fusion-mcp-server`, `Joelalbon/Fusion-MCP-Server`, and similar bridge-style servers
  - Sources:
    - https://github.com/Joe-Spencer/fusion-mcp-server
    - https://github.com/Joelalbon/Fusion-MCP-Server
  - Noteworthy pattern: remote command/control and direct Fusion API access.
  - Toolsmith response: make direct API access available only through guarded fallback paths, while prioritizing inspection, preflight, typed modeling tools, change journaling, and validation.

## Adopted Ideas

- Streamable HTTP awareness
  - `/health`, discovery, and `fusion://agent/server-capabilities` advertise Streamable HTTP and legacy SSE compatibility.

- Machine-readable client metadata
  - Initialize responses include Toolsmith instructions.
  - Tools include MCP risk annotations.
  - Resources include audience and priority annotations.
  - `fusion://agent/server-capabilities` summarizes transports, discovery keys, safety gates, annotations, prompts, profiles, and counts.

- Offline discoverability
  - `fusion-mcp dump-schemas` exports initialize metadata, tools, resources, templates, prompts, profiles, and server capabilities without launching Fusion.

- Agent workflow steering
  - `doctor`, `recommend_mcp_workflow`, `fusion://agent/tool-first-workflow`, and first-class MCP prompts route agents toward structured tools before raw scripts.

- Safer fallback scripting
  - `run_fusion_script` requires a stated intent and tool gap.
  - Raw export APIs are blocked unless explicitly overridden.

- Better visual/demo support
  - `capture_view`, `capture_demo_sequence`, `set_camera`, and `set_visibility` support screenshot-based verification and demos.

## Deliberate Differences

- Toolsmith does not optimize for the smallest possible bridge.
  - It favors inspection, planning, preflight, structured feature tools, and auditability over a raw-execute-first workflow.

- Toolsmith keeps dangerous tools separated.
  - Raw scripts, timeline deletion/suppression, document activation/revert, and undo are profiled as dangerous.

- Toolsmith treats printability checks as heuristic.
  - `inspect_printability` is read-only and warning-only; slicer preview remains the source of truth.

- Toolsmith avoids project-specific tools.
  - Demo-specific geometry should live in prompts, scripts, or examples, not in the general MCP server.

## Remaining Watch Items

- Public package metadata and release polish.
- More complete mock/simulation mode for no-Fusion client integration tests.
- Deeper typed CAD feature families where they remain general: sheet-metal workflows, richer joints/origin helpers, stronger sketch constraint editing, and slicer-grade printability.
- Additional protocol evolution in MCP transports, authorization, and client-side approval UX.
