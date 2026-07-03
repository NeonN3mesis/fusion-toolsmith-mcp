import json
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))


class ManifestAndDeploymentTests(unittest.TestCase):
    def test_manifest_starts_server_on_fusion_startup(self):
        with open(os.path.join(ROOT, "FusionMCP.manifest"), "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["type"], "addin")
        self.assertEqual(manifest["autodeskProduct"], "Fusion")
        self.assertTrue(manifest["runOnStartup"])

    def test_installer_contains_required_payload_names(self):
        script_path = os.path.join(ROOT, "scripts", "install_fusion_mcp_addin.ps1")
        with open(script_path, "r", encoding="utf-8") as f:
            script = f.read()
        for name in [
            "__init__.py",
            "FusionMCP.py",
            "FusionMCP.manifest",
            "server",
            "tools",
            "mcp_primitives",
            "__pycache__",
            "LegacyAddInName",
            "runOnStartup",
        ]:
            self.assertIn(name, script)

    def test_package_marker_is_not_a_second_entrypoint(self):
        with open(os.path.join(ROOT, "__init__.py"), "r", encoding="utf-8") as f:
            package_init = f.read()
        self.assertIn("FusionMCP add-in package", package_init)
        self.assertNotIn("from .FusionMCP import run, stop", package_init)

    def test_live_smoke_script_checks_mcp_handshake(self):
        script_path = os.path.join(ROOT, "scripts", "test_fusion_mcp_live.ps1")
        with open(script_path, "r", encoding="utf-8") as f:
            script = f.read()
        for text in [
            ".fusion_mcp.json",
            "/health",
            "ExpectedPort",
            "initialize",
            "tools/list",
            "inspect_design",
        ]:
            self.assertIn(text, script)


if __name__ == "__main__":
    unittest.main()
