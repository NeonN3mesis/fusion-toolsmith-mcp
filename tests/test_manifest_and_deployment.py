import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = os.path.dirname(os.path.dirname(__file__))


class ManifestAndDeploymentTests(unittest.TestCase):
    def test_manifest_does_not_start_server_on_fusion_startup(self):
        with open(os.path.join(ROOT, "FusionMCP.manifest"), "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["type"], "addin")
        self.assertEqual(manifest["autodeskProduct"], "Fusion")
        self.assertFalse(manifest["runOnStartup"])

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
            "tool_profiles.json",
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
            "doctor",
            "recommend_mcp_workflow",
            "extract_reference_dimensions",
            "get_body_faces",
            "create_offset_plane",
            "create_rounded_rectangle_body",
            "create_rounded_slot_cut",
            "create_rounded_pocket",
            "create_hole_pattern",
            "create_counterbore_hole_pattern",
            "mirror_features_or_bodies",
            "pattern_feature",
            "shell_body",
            "set_visibility",
            "bearer_sse_url",
            "Authorization",
            "TaskManager is not running",
        ]:
            self.assertIn(text, script)

    def test_live_inspection_fixture_script_checks_structural_tools(self):
        script_path = os.path.join(ROOT, "scripts", "test_fusion_mcp_inspection_fixture.ps1")
        with open(script_path, "r", encoding="utf-8") as f:
            script = f.read()
        for text in [
            ".fusion_mcp.json",
            "Fixture_BaseSketch",
            "Fixture_BaseExtrude",
            "Fixture_ProjectSketch",
            "Fixture_TargetComponent",
            "inspect_sketch",
            "inspect_feature",
            "get_sketch_parameters",
            "get_feature_parameters",
            "get_parameter_usage",
            "get_projected_geometry_sources",
            "map_coordinates",
            "get_feature_dependencies",
            "get_dependency_graph",
            "assess_change_impact",
            "plan_parameterization",
            "doctor",
            "recommend_mcp_workflow",
            "get_runtime_diagnostics",
            "run_fusion_script",
            "script_intent",
            "mcp_tool_gap",
            "bearer_sse_url",
            "Authorization",
            "TaskManager is not running",
            "KeepFixtureDocument",
            "doc.close(False)",
        ]:
            self.assertIn(text, script)

    def test_antigravity_config_sync_script_uses_live_discovery(self):
        script_path = os.path.join(ROOT, "scripts", "sync_antigravity_fusion_mcp_config.ps1")
        with open(script_path, "r", encoding="utf-8") as f:
            script = f.read()
        for text in [
            ".gemini\\config\\mcp_config.json",
            ".fusion_mcp.json",
            "autodesk-fusion-mcp",
            "sse_url",
            "serverUrl",
            ".bak-",
        ]:
            self.assertIn(text, script)

    def test_pyproject_exposes_management_cli(self):
        with open(os.path.join(ROOT, "pyproject.toml"), "r", encoding="utf-8") as f:
            pyproject = f.read()
        for text in [
            "fusion-toolsmith-mcp",
            "Fusion Toolsmith MCP",
            "README.md",
            "fusion-mcp = \"fusion_mcp_cli.cli:main\"",
            "fusion_mcp_cli",
        ]:
            self.assertIn(text, pyproject)

    def test_readme_documents_install_verify_and_profiles(self):
        with open(os.path.join(ROOT, "README.md"), "r", encoding="utf-8") as f:
            readme = f.read()
        for text in [
            "fusion-mcp install-addin",
            "fusion-mcp package-addin",
            "fusion-mcp test-live",
            "fusion-mcp print-client-config",
            "Tool Profiles",
            "dangerous",
            "bearer_sse_url",
            "fusion://runtime/change-journal",
            "get_change_journal",
            "fusion://docs/fusion-api",
            "search_local_fusion_docs",
            "examples/prompts.md",
            "docs/tooling-roadmap.md",
            "GitHub Actions",
            "LICENSE",
            "runOnStartup",
        ]:
            self.assertIn(text, readme)

    def test_cli_help_loads_without_fusion(self):
        completed = subprocess.run(
            [sys.executable, "-m", "fusion_mcp_cli", "--help"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("install-addin", completed.stdout)
        self.assertIn("package-addin", completed.stdout)
        self.assertIn("sync-config", completed.stdout)
        self.assertIn("doctor", completed.stdout)
        self.assertIn("list-profiles", completed.stdout)

    def test_cli_module_help_loads_without_fusion(self):
        completed = subprocess.run(
            [sys.executable, "-m", "fusion_mcp_cli.cli", "--help"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("install-addin", completed.stdout)
        self.assertIn("test-live", completed.stdout)

    def test_cli_package_addin_builds_clean_zip_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "FusionMCP-addin.zip")
            completed = subprocess.run(
                [sys.executable, "-m", "fusion_mcp_cli", "package-addin", "--output", output],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(os.path.isfile(output))
            with zipfile.ZipFile(output, "r") as archive:
                names = set(archive.namelist())
        for name in [
            "FusionMCP/FusionMCP.py",
            "FusionMCP/FusionMCP.manifest",
            "FusionMCP/server/mcp_server.py",
            "FusionMCP/tools/__init__.py",
            "FusionMCP/mcp_primitives/__init__.py",
            "FusionMCP/tool_profiles.json",
        ]:
            self.assertIn(name, names)
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))

    def test_cli_list_profiles_outputs_shared_profile_file(self):
        completed = subprocess.run(
            [sys.executable, "-m", "fusion_mcp_cli", "list-profiles"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertIn("profiles", payload)
        self.assertIn("inspection", payload["profiles"])
        self.assertIn("dangerous", payload["profiles"])
        self.assertIn("docs", payload["profiles"])

    def test_tooling_roadmap_tracks_general_cad_gaps(self):
        with open(os.path.join(ROOT, "docs", "tooling-roadmap.md"), "r", encoding="utf-8") as f:
            roadmap = f.read()
        for text in [
            "create_hole_pattern",
            "mirror_features_or_bodies",
            "pattern_feature",
            "create_rounded_pocket",
            "shell_body",
            "inspect_printability",
            "capture_demo_sequence",
        ]:
            self.assertIn(text, roadmap)


if __name__ == "__main__":
    unittest.main()
