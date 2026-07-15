# Contributing

Fusion Toolsmith MCP is built around a safety-first Fusion 360 workflow. Contributions should preserve that shape.

## Development Setup

```powershell
python -m pip install -e .
python -m unittest discover -s tests
```

Install the add-in locally:

```powershell
fusion-mcp install-addin
```

Then start or restart `FusionMCP` from Fusion 360:

```text
Utilities > Add-Ins > Scripts and Add-Ins > Add-Ins > FusionMCP > Run
```

## Contribution Guidelines

- Prefer structured tools over expanding raw script execution.
- Keep mutating tools explicit about intent, target, and validation.
- Add tests for protocol, registry, packaging, and safety-contract changes.
- Do not make the add-in start automatically with Fusion.
- Keep local-only behavior and auth defaults conservative.

## Validation

Run unit tests:

```powershell
python -m unittest discover -s tests
```

Build the add-in ZIP:

```powershell
fusion-mcp package-addin
```

When Fusion 360 is available, run:

```powershell
fusion-mcp test-live
```
