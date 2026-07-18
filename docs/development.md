# Development And Releases

Use this page for maintainer and contributor workflows. Normal install and client setup lives in the README and [installation guide](installation.md).

## Unit Tests

```powershell
python -m unittest discover -s tests
```

## Live Fixture Tests

Run the structural live fixture when FusionMCP is loaded and you want deeper end-to-end coverage:

```powershell
fusion-mcp test-fixture
```

Run the guarded multicolor 3MF fixture after reloading the add-in when validating slicer/export workflows:

```powershell
fusion-mcp test-3mf-fixture
```

To keep a machine-readable validation artifact:

```powershell
fusion-mcp test-fixture --report-path dist\fusion-live-fixture-report.json
fusion-mcp validate-fixture-report dist\fusion-live-fixture-report.json
```

Compare archived reports from multiple Fusion versions or machines:

```powershell
fusion-mcp fixture-report-matrix reports\fusion-*.json --output dist\fusion-fixture-matrix.json
fusion-mcp fixture-report-matrix reports\fusion-*.json --format markdown --output dist\fusion-fixture-matrix.md
```

Or use the PowerShell scripts directly:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_fusion_mcp_inspection_fixture.ps1
powershell -ExecutionPolicy Bypass -File scripts/test_fusion_mcp_3mf_fixture.ps1
```

## Schema And Package Checks

```powershell
fusion-mcp dump-schemas --output dist\mcp-schemas.json
fusion-mcp package-addin
```

The packaged add-in is written to:

```text
dist\FusionMCP-addin.zip
```

## Mock Server

Run a deterministic no-Fusion mock server for client integration tests:

```powershell
fusion-mcp mock-server --port 9101
```

Stable representative mock payloads are documented in [mock-payload-examples.md](mock-payload-examples.md).

## Demo Material

Useful starter prompts are in [../examples/prompts.md](../examples/prompts.md).

Use [demo-script.md](demo-script.md) to record the short demo GIF/video for the README.

## CI And Releases

GitHub Actions runs the unit suite, checks the no-Fusion mock/schema surfaces, and builds the add-in ZIP on pushes and pull requests.

To publish a GitHub release with the packaged add-in attached:

```powershell
git tag v1.1.0
git push origin v1.1.0
```
