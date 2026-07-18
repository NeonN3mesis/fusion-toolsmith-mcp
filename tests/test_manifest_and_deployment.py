import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
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
            "KeepLegacyAddIn",
            "AddInsDisabled",
            "disabled-legacy",
        ]:
            self.assertIn(name, script)

    def test_package_marker_is_not_a_second_entrypoint(self):
        with open(os.path.join(ROOT, "__init__.py"), "r", encoding="utf-8") as f:
            package_init = f.read()
        self.assertIn("FusionMCP add-in package", package_init)
        self.assertNotIn("from .FusionMCP import run, stop", package_init)

    def test_addin_start_refreshes_runtime_modules(self):
        with open(os.path.join(ROOT, "FusionMCP.py"), "r", encoding="utf-8") as f:
            addin_entrypoint = f.read()
        for text in [
            "os.path.dirname(os.path.abspath(__file__))",
            "sys.path.insert(0, addin_root)",
            "importlib.invalidate_caches()",
            "_clear_runtime_modules()",
            "force_reload=True",
            "server.mcp_server",
            "tools",
            "mcp_primitives",
            "_try_stop_runtime_modules",
            "stopped without loaded runtime modules",
        ]:
            self.assertIn(text, addin_entrypoint)

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
            "inspect_printability",
            "inspect_selection_sets",
            "inspect_3mf_archive",
            "plan_multibody_3mf_export",
            "plan_multicolor_3mf_export",
            "inspect_mesh_bodies",
            "plan_mesh_conversion",
            "inspect_design_configurations",
            "plan_design_variant",
            "apply_design_variant_parameters",
            "inspect_render_workspace",
            "plan_render_output",
            "render_viewport_output",
            "inspect_document_management_state",
            "plan_document_management_action",
            "export_document_copy",
            "get_physical_properties",
            "inspect_analysis_capabilities",
            "interference_check",
            "clearance_check",
            "verify_insert_alignment",
            "exact_interference_check",
            "exact_clearance_check",
            "inspect_sheet_metal_rules",
            "preflight_flat_pattern",
            "plan_sheet_metal_workflow",
            "export_flat_pattern",
            "inspect_surface_bodies",
            "plan_surface_repair",
            "inspect_drawing_documents",
            "preflight_drawing_creation",
            "plan_drawing_views",
            "inspect_electronics_workspace",
            "plan_pcb_enclosure_fit",
            "inspect_simulation_workspace",
            "list_simulation_studies",
            "plan_simulation_study",
            "add_drawing_view",
            "add_drawing_dimension",
            "add_drawing_callout",
            "add_parts_list",
            "add_revision_table",
            "inspect_manufacturing_workspace",
            "list_manufacturing_setups",
            "inspect_operation",
            "plan_manufacturing_operation",
            "create_manufacturing_setup",
            "create_manufacturing_operation",
            "generate_toolpaths",
            "post_process",
            "get_body_faces",
            "get_body_edges",
            "get_assembly_tree",
            "get_assembly_references",
            "get_assembly_joints",
            "plan_joint_limits",
            "list_appearances",
            "inspect_body_style",
            "get_timeline",
            "measure_entity",
            "validate_model",
            "assess_change_impact",
            "preflight_model_change",
            "edit_extrude_feature",
            "edit_fillet_radius",
            "edit_chamfer_distance",
            "edit_shell_thickness",
            "edit_pattern_parameter",
            "edit_hole_parameter",
            "offset_face_or_press_pull",
            "create_offset_plane",
            "create_construction_point",
            "create_construction_axis",
            "create_rigid_joint",
            "create_section_analysis",
            "create_revolute_joint",
            "create_slider_joint",
            "create_cylindrical_joint",
            "create_pin_slot_joint",
            "create_planar_joint",
            "create_ball_joint",
            "set_joint_limits",
            "create_flange",
            "create_bend",
            "unfold_sheet_metal",
            "refold_sheet_metal",
            "patch_surface",
            "stitch_surfaces",
            "thicken_surface",
            "trim_surface",
            "extend_surface",
            "create_ruled_surface",
            "add_sketch_constraint",
            "delete_sketch_constraint",
            "create_sketch_offset",
            "copy_profile_loop",
            "offset_profile_loop",
            "create_parametric_feature",
            "extrude_existing_profile",
            "revolve_feature",
            "loft_feature",
            "sweep_feature",
            "create_rounded_rectangle_body",
            "create_rounded_slot_cut",
            "create_rounded_pocket",
            "create_hole_pattern",
            "create_counterbore_hole_pattern",
            "mirror_features_or_bodies",
            "pattern_feature",
            "apply_appearance",
            "convert_mesh_to_solid",
            "repair_mesh_body",
            "reduce_mesh_body",
            "remesh_body",
            "reorganize_body_to_component",
            "import_parameters_csv",
            "export_parameters_csv",
            "capture_view",
            "set_camera",
            "shell_body",
            "set_visibility",
            "capture_demo_sequence",
            "prompt_user",
            "list_documents",
            "create_design_document",
            "close_active_document",
            "set_timeline_marker",
            "clone_timeline_feature",
            "streamable_http_url",
            "/mcp",
            "Mcp-Session-Id",
            "Streamable HTTP initialize",
            "bearer_sse_url",
            "Authorization",
            "TaskManager is not running",
            "stop and run the FusionMCP add-in again",
            "reloads Python modules",
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
            "Fixture_RevolveSketch",
            "Fixture_LoftSectionA",
            "Fixture_LoftSectionB",
            "Fixture_SweepProfile",
            "Fixture_SweepPath",
            "Fixture_TargetComponent",
            "inspect_sketch",
            "inspect_feature",
            "get_sketch_parameters",
            "get_feature_parameters",
            "edit_extrude_feature",
            "copy_profile_loop",
            "offset_profile_loop",
            "extrude_existing_profile",
            "edit_fillet_radius",
            "edit_chamfer_distance",
            "edit_shell_thickness",
            "edit_pattern_parameter",
            "edit_hole_parameter",
            "get_parameter_usage",
            "get_projected_geometry_sources",
            "map_coordinates",
            "get_feature_dependencies",
            "get_dependency_graph",
            "assess_change_impact",
            "plan_parameterization",
            "get_physical_properties",
            "inspect_analysis_capabilities",
            "interference_check",
            "clearance_check",
            "verify_insert_alignment",
            "exact_interference_check",
            "exact_clearance_check",
            "inspect_sheet_metal_rules",
            "preflight_flat_pattern",
            "plan_sheet_metal_workflow",
            "export_flat_pattern",
            "inspect_surface_bodies",
            "plan_surface_repair",
            "inspect_drawing_documents",
            "preflight_drawing_creation",
            "plan_drawing_views",
            "inspect_simulation_workspace",
            "list_simulation_studies",
            "plan_simulation_study",
            "add_drawing_view",
            "add_drawing_dimension",
            "add_drawing_callout",
            "add_parts_list",
            "add_revision_table",
            "inspect_manufacturing_workspace",
            "list_manufacturing_setups",
            "inspect_operation",
            "plan_manufacturing_operation",
            "create_manufacturing_setup",
            "create_manufacturing_operation",
            "generate_toolpaths",
            "post_process",
            "Exact interference APIs are not available",
            "Exact minimum-distance APIs are not available",
            "Sheet-metal operation preflight failed",
            "not an open Fusion drawing document",
            "Manufacturing preflight failed",
            "Live fixture validates guarded surface mutator unsupported handling",
            "get_assembly_references",
            "plan_joint_limits",
            "Invoke-MotionJointProbe",
            "Live fixture validates joint-limit planning",
            "Fixture_RevoluteJoint",
            "Fixture_SliderJoint",
            "Fixture_CylindricalJoint",
            "Fixture_PinSlotJoint",
            "Fixture_PlanarJoint",
            "Fixture_BallJoint",
            "get_assembly_joints did not report created motion joint",
            "create_section_analysis",
            "delete_section_analysis",
            "create_revolute_joint",
            "create_slider_joint",
            "create_cylindrical_joint",
            "create_pin_slot_joint",
            "create_planar_joint",
            "create_ball_joint",
            "set_joint_limits",
            "create_flange",
            "create_bend",
            "unfold_sheet_metal",
            "refold_sheet_metal",
            "patch_surface",
            "stitch_surfaces",
            "thicken_surface",
            "trim_surface",
            "extend_surface",
            "create_ruled_surface",
            "create_construction_point",
            "create_construction_axis",
            "revolve_feature",
            "loft_feature",
            "sweep_feature",
            "shell_body",
            "offset_face_or_press_pull",
            "pattern_feature",
            "mirror_features_or_bodies",
            "inspect_printability",
            "inspect_selection_sets",
            "inspect_3mf_archive",
            "plan_multibody_3mf_export",
            "plan_multicolor_3mf_export",
            "inspect_mesh_bodies",
            "plan_mesh_conversion",
            "inspect_design_configurations",
            "plan_design_variant",
            "apply_design_variant_parameters",
            "inspect_render_workspace",
            "plan_render_output",
            "render_viewport_output",
            "inspect_document_management_state",
            "plan_document_management_action",
            "export_document_copy",
            "inspect_electronics_workspace",
            "plan_pcb_enclosure_fit",
            "inspect_simulation_workspace",
            "list_simulation_studies",
            "plan_simulation_study",
            "capture_demo_sequence",
            "doctor",
            "recommend_mcp_workflow",
            "get_runtime_diagnostics",
            "run_fusion_script",
            "script_intent",
            "mcp_tool_gap",
            "streamable_http_url",
            "/mcp",
            "legacyStreamableUri",
            "Fusion MCP Streamable HTTP endpoint",
            "bearer_sse_url",
            "Authorization",
            "TaskManager is not running",
            "KeepFixtureDocument",
            "ReportPath",
            "Add-FixtureProbe",
            "Write-FixtureReport",
            "fixtureProbeResults",
            "exact_interference_check",
            "plan_manufacturing_operation",
            "script:fixtureCreated",
            "Invoke-FixtureDocumentCleanup",
            "Fixture cleanup after failure",
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
            "Development Status :: 4 - Beta",
            "Repository = \"https://github.com/NeonN3mesis/fusion-toolsmith-mcp\"",
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
            "fusion-mcp test-fixture",
            "fusion-mcp test-3mf-fixture",
            "fusion-mcp print-client-config",
            "fusion-mcp dump-schemas",
            "Tool Profiles",
            "Feature Matrix",
            "presentation",
            "document",
            "inspect_printability",
            "inspect_selection_sets",
            "inspect_3mf_archive",
            "plan_multibody_3mf_export",
            "plan_multicolor_3mf_export",
            "inspect_mesh_bodies",
            "plan_mesh_conversion",
            "inspect_design_configurations",
            "plan_design_variant",
            "inspect_render_workspace",
            "plan_render_output",
            "render_viewport_output",
            "inspect_document_management_state",
            "plan_document_management_action",
            "export_document_copy",
            "inspect_electronics_workspace",
            "plan_pcb_enclosure_fit",
            "inspect_simulation_workspace",
            "list_simulation_studies",
            "plan_simulation_study",
            "capture_demo_sequence",
            "offset_face_or_press_pull",
            "dangerous",
            "bearer_sse_url",
            "streamable_http_url",
            "initialize instructions",
            "tool/resource annotation",
            "fusion://agent/server-capabilities",
            "fusion://runtime/change-journal",
            "get_change_journal",
            "fusion://docs/fusion-api",
            "search_local_fusion_docs",
            "examples/prompts.md",
            "docs/mock-payload-examples.md",
            "docs/tooling-roadmap.md",
            "docs/external-fusion-mcp-sweep.md",
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
        self.assertIn("dump-schemas", completed.stdout)
        self.assertIn("mock-server", completed.stdout)
        self.assertIn("test-fixture", completed.stdout)
        self.assertIn("test-3mf-fixture", completed.stdout)
        self.assertIn("validate-fixture-report", completed.stdout)
        self.assertIn("fixture-report-matrix", completed.stdout)

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
        self.assertIn("test-fixture", completed.stdout)
        self.assertIn("test-3mf-fixture", completed.stdout)
        self.assertIn("dump-schemas", completed.stdout)
        self.assertIn("mock-server", completed.stdout)
        self.assertIn("validate-fixture-report", completed.stdout)
        self.assertIn("fixture-report-matrix", completed.stdout)

    def test_cli_test_fixture_wraps_structural_live_fixture(self):
        with open(os.path.join(ROOT, "fusion_mcp_cli", "cli.py"), "r", encoding="utf-8") as f:
            cli = f.read()
        for text in [
            "command_test_fixture",
            "command_test_3mf_fixture",
            "scripts\" / \"test_fusion_mcp_inspection_fixture.ps1",
            "scripts\" / \"test_fusion_mcp_3mf_fixture.ps1",
            "-DiscoveryPath",
            "-ExpectedPort",
            "-TimeoutSec",
            "-ReportPath",
            "-SkipFixtureCreation",
            "-KeepFixtureDocument",
            "test-fixture",
            "test-3mf-fixture",
            "--report-path",
            "--skip-fixture-creation",
            "--keep-fixture-document",
        ]:
            self.assertIn(text, cli)

    def test_live_3mf_fixture_uses_structured_document_setup_and_cleanup(self):
        script_path = os.path.join(ROOT, "scripts", "test_fusion_mcp_3mf_fixture.ps1")
        with open(script_path, "r", encoding="utf-8") as f:
            script = f.read()
        for text in [
            "create_design_document",
            "create_box",
            "inspect_body_style",
            "list_appearances",
            "plan_multicolor_3mf_export",
            "apply_appearance",
            "export_asset",
            "close_active_document",
        ]:
            self.assertIn(text, script)
        self.assertNotIn("mcp_tool_gap", script)
        self.assertNotIn("doc.close(False)", script)

    def test_cli_validate_fixture_report_accepts_expected_unsupported_probes(self):
        from fusion_mcp_cli.cli import REQUIRED_FIXTURE_PROBES

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = os.path.join(temp_dir, "fixture-report.json")
            probes = []
            for name in REQUIRED_FIXTURE_PROBES:
                status = "unsupported" if name in {"thicken_surface", "add_drawing_callout"} else "passed"
                if name in {"create_flange", "generate_toolpaths", "post_process"}:
                    status = "preflight_blocked"
                probes.append({"name": name, "status": status, "detail": {}})
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump({
                    "status": "passed",
                    "fixtureDocumentOpen": False,
                    "failure": None,
                    "probes": probes,
                }, f)

            completed = subprocess.run(
                [sys.executable, "-m", "fusion_mcp_cli", "validate-fixture-report", report_path],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            validation = json.loads(completed.stdout)
            self.assertTrue(validation["ok"])
            self.assertGreaterEqual(validation["probeCount"], len(REQUIRED_FIXTURE_PROBES))

    def test_cli_validate_fixture_report_rejects_missing_or_required_passed_probe(self):
        from fusion_mcp_cli.cli import REQUIRED_FIXTURE_PROBES

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = os.path.join(temp_dir, "fixture-report.json")
            probes = [
                {"name": name, "status": "passed", "detail": {}}
                for name in REQUIRED_FIXTURE_PROBES
                if name != "exact_clearance_check"
            ]
            probes.append({"name": "thicken_surface", "status": "unsupported", "detail": {}})
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump({
                    "status": "passed",
                    "fixtureDocumentOpen": False,
                    "failure": None,
                    "probes": probes,
                }, f)

            missing_completed = subprocess.run(
                [sys.executable, "-m", "fusion_mcp_cli", "validate-fixture-report", report_path],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(missing_completed.returncode, 1)
            self.assertIn("exact_clearance_check", missing_completed.stdout)

            strict_completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fusion_mcp_cli",
                    "validate-fixture-report",
                    report_path,
                    "--require-passed",
                    "thicken_surface",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(strict_completed.returncode, 1)
            self.assertIn("thicken_surface=unsupported", strict_completed.stdout)

    def test_cli_validate_fixture_report_requires_motion_joint_probe_surface(self):
        from fusion_mcp_cli.cli import REQUIRED_FIXTURE_PROBES

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = os.path.join(temp_dir, "fixture-report.json")
            omitted = {
                "create_revolute_joint",
                "create_slider_joint",
                "create_cylindrical_joint",
                "create_pin_slot_joint",
                "create_planar_joint",
                "create_ball_joint",
            }
            probes = [
                {"name": name, "status": "passed", "detail": {}}
                for name in REQUIRED_FIXTURE_PROBES
                if name not in omitted
            ]
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump({
                    "status": "passed",
                    "fixtureDocumentOpen": False,
                    "failure": None,
                    "probes": probes,
                }, f)

            completed = subprocess.run(
                [sys.executable, "-m", "fusion_mcp_cli", "validate-fixture-report", report_path],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn("create_revolute_joint", completed.stdout)
            self.assertIn("create_ball_joint", completed.stdout)

    def test_cli_fixture_report_matrix_summarizes_multiple_reports(self):
        from fusion_mcp_cli.cli import REQUIRED_FIXTURE_PROBES

        with tempfile.TemporaryDirectory() as temp_dir:
            first = os.path.join(temp_dir, "fusion-2026-1.json")
            second = os.path.join(temp_dir, "fusion-2026-2.json")
            self._write_fixture_report(first, REQUIRED_FIXTURE_PROBES)
            self._write_fixture_report(
                second,
                REQUIRED_FIXTURE_PROBES,
                {"create_revolute_joint": "unsupported", "generate_toolpaths": "preflight_blocked"},
            )

            completed = subprocess.run(
                [sys.executable, "-m", "fusion_mcp_cli", "fixture-report-matrix", first, second],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            matrix = json.loads(completed.stdout)
            self.assertTrue(matrix["ok"])
            self.assertEqual(matrix["runCount"], 2)
            self.assertIn("create_revolute_joint", matrix["probeNames"])
            self.assertEqual(matrix["runs"][1]["statuses"]["create_revolute_joint"], "unsupported")
            self.assertEqual(matrix["runs"][1]["statuses"]["generate_toolpaths"], "preflight_blocked")

    def test_cli_fixture_report_matrix_can_print_markdown(self):
        from fusion_mcp_cli.cli import REQUIRED_FIXTURE_PROBES

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = os.path.join(temp_dir, "fusion-2026-1.json")
            self._write_fixture_report(
                report_path,
                REQUIRED_FIXTURE_PROBES,
                {"create_revolute_joint": "unsupported"},
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fusion_mcp_cli",
                    "fixture-report-matrix",
                    report_path,
                    "--format",
                    "markdown",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("# FusionMCP Fixture Report Matrix", completed.stdout)
            self.assertIn("| Probe | fusion-2026-1 |", completed.stdout)
            self.assertIn("| create_revolute_joint | unsupported |", completed.stdout)

    def test_cli_fixture_report_matrix_can_write_markdown(self):
        from fusion_mcp_cli.cli import REQUIRED_FIXTURE_PROBES

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = os.path.join(temp_dir, "fusion-2026-1.json")
            output_path = os.path.join(temp_dir, "matrix.md")
            self._write_fixture_report(report_path, REQUIRED_FIXTURE_PROBES)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fusion_mcp_cli",
                    "fixture-report-matrix",
                    report_path,
                    "--format",
                    "markdown",
                    "--output",
                    output_path,
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with open(output_path, "r", encoding="utf-8") as f:
                markdown = f.read()
            self.assertIn("# FusionMCP Fixture Report Matrix", markdown)
            self.assertIn("| fixture_cleanup | passed |", markdown)

    def test_cli_fixture_report_matrix_rejects_invalid_report(self):
        from fusion_mcp_cli.cli import REQUIRED_FIXTURE_PROBES

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = os.path.join(temp_dir, "bad-report.json")
            probes = [
                {"name": name, "status": "passed", "detail": {}}
                for name in REQUIRED_FIXTURE_PROBES
                if name != "fixture_cleanup"
            ]
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump({
                    "status": "passed",
                    "fixtureDocumentOpen": False,
                    "failure": None,
                    "probes": probes,
                }, f)

            completed = subprocess.run(
                [sys.executable, "-m", "fusion_mcp_cli", "fixture-report-matrix", report_path],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 1)
            matrix = json.loads(completed.stdout)
            self.assertFalse(matrix["ok"])
            self.assertEqual(matrix["runs"][0]["statuses"]["fixture_cleanup"], "missing")

    def _write_fixture_report(self, path, probe_names, status_for=None):
        status_for = status_for or {}
        probes = [
            {"name": name, "status": status_for.get(name, "passed"), "detail": {}}
            for name in probe_names
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "status": "passed",
                "startedAt": "2026-07-16T00:00:00Z",
                "completedAt": "2026-07-16T00:01:00Z",
                "mcpPath": "/mcp",
                "fixtureDocumentOpen": False,
                "failure": None,
                "probes": probes,
            }, f)

    def test_cli_doctor_checks_required_live_tools(self):
        with open(os.path.join(ROOT, "fusion_mcp_cli", "cli.py"), "r", encoding="utf-8") as f:
            cli = f.read()
        for text in [
            "REQUIRED_LIVE_TOOLS",
            "tools/list",
            "missingRequiredTools",
            "edit_extrude_feature",
            "edit_fillet_radius",
            "edit_chamfer_distance",
            "edit_shell_thickness",
            "edit_pattern_parameter",
            "edit_hole_parameter",
            "inspect_analysis_capabilities",
            "verify_insert_alignment",
            "exact_interference_check",
            "exact_clearance_check",
            "inspect_sheet_metal_rules",
            "preflight_flat_pattern",
            "plan_sheet_metal_workflow",
            "export_flat_pattern",
            "inspect_surface_bodies",
            "plan_surface_repair",
            "inspect_drawing_documents",
            "preflight_drawing_creation",
            "plan_drawing_views",
            "inspect_simulation_workspace",
            "list_simulation_studies",
            "plan_simulation_study",
            "add_drawing_view",
            "add_drawing_dimension",
            "add_drawing_callout",
            "add_parts_list",
            "add_revision_table",
            "inspect_manufacturing_workspace",
            "list_manufacturing_setups",
            "inspect_operation",
            "plan_manufacturing_operation",
            "create_manufacturing_setup",
            "create_manufacturing_operation",
            "generate_toolpaths",
            "post_process",
            "create_revolute_joint",
            "create_slider_joint",
            "create_cylindrical_joint",
            "create_pin_slot_joint",
            "create_planar_joint",
            "create_ball_joint",
            "plan_joint_limits",
            "set_joint_limits",
            "create_flange",
            "create_bend",
            "unfold_sheet_metal",
            "refold_sheet_metal",
            "patch_surface",
            "stitch_surfaces",
            "thicken_surface",
            "trim_surface",
            "extend_surface",
            "create_ruled_surface",
            "create_section_analysis",
            "get_runtime_diagnostics",
            "create_design_document",
            "close_active_document",
            "sourceFingerprint",
            "installed_metadata_path",
            "default_addins_root() / ADDIN_NAME",
            "installed",
            "matchesCheckout",
            "fromHealth",
            "fromDiagnostics",
            "installed_mismatch",
            "diagnosticsError",
            "fingerprint_mismatch",
            "Live FusionMCP source fingerprint differs",
            "Installed FusionMCP source fingerprint differs",
            "restartRecommended",
            "Stop and run the FusionMCP add-in again",
            "return 1 if missing_required_tools or fingerprint_mismatch or installed_mismatch else 0",
        ]:
            self.assertIn(text, cli)

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

    def test_cli_install_quarantines_legacy_addin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            addins_root = os.path.join(temp_dir, "API", "AddIns")
            legacy_root = os.path.join(addins_root, "Fusion MCP Addin")
            os.makedirs(legacy_root)
            with open(os.path.join(legacy_root, "Fusion MCP Addin.manifest"), "w", encoding="utf-8") as f:
                f.write("{}")

            completed = subprocess.run(
                [sys.executable, "-m", "fusion_mcp_cli", "install-addin", "--addins-root", addins_root],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(os.path.exists(legacy_root))
            self.assertTrue(os.path.isdir(os.path.join(addins_root, "FusionMCP")))
            install_metadata_path = os.path.join(addins_root, "FusionMCP", ".fusion_mcp_install.json")
            self.assertTrue(os.path.isfile(install_metadata_path))
            with open(install_metadata_path, "r", encoding="utf-8") as f:
                install_metadata = json.load(f)
            self.assertIn("installedAt", install_metadata)
            self.assertIn("sourceFingerprint", install_metadata)
            self.assertTrue(install_metadata["sourceFingerprint"]["fingerprint"])
            disabled_root = os.path.join(temp_dir, "API", "AddInsDisabled")
            self.assertTrue(os.path.isdir(os.path.join(disabled_root, "Fusion MCP Addin.disabled-legacy")))
            self.assertIn("Moved legacy Fusion MCP add-in outside Fusion scan path", completed.stdout)

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
        self.assertIn("presentation", payload["profiles"])
        self.assertIn("document", payload["profiles"])

    def test_cli_dump_schemas_outputs_offline_mcp_surface(self):
        completed = subprocess.run(
            [sys.executable, "-m", "fusion_mcp_cli", "dump-schemas"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertIn("server", payload)
        self.assertIn("instructions", payload["server"])
        self.assertIn("tools", payload)
        self.assertIn("resources", payload)
        self.assertIn("resourceTemplates", payload)
        self.assertIn("prompts", payload)
        self.assertIn("profiles", payload)
        self.assertIn("serverCapabilities", payload)
        tool_by_name = {tool["name"]: tool for tool in payload["tools"]}
        self.assertIn("inspect_design", tool_by_name)
        self.assertTrue(tool_by_name["inspect_design"]["annotations"]["readOnlyHint"])
        resource_by_uri = {resource["uri"]: resource for resource in payload["resources"]}
        self.assertIn("fusion://agent/server-capabilities", resource_by_uri)
        self.assertIn("annotations", resource_by_uri["fusion://agent/server-capabilities"])
        self.assertTrue(any(prompt["name"] == "tool_first_workflow" for prompt in payload["prompts"]))

    def test_cli_dump_schemas_can_write_output_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "schemas.json")
            completed = subprocess.run(
                [sys.executable, "-m", "fusion_mcp_cli", "dump-schemas", "--output", output],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(os.path.isfile(output))
            with open(output, "r", encoding="utf-8") as f:
                payload = json.load(f)
        self.assertIn("serverCapabilities", payload)
        self.assertIn("Wrote FusionMCP MCP schemas", completed.stdout)

    def test_mock_server_exposes_streamable_http_without_fusion(self):
        from fusion_mcp_cli.mock_server import create_mock_http_server

        server = create_mock_http_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"

        def get_json(path):
            with urllib.request.urlopen(base_url + path, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))

        def rpc(method, params=None, request_id=1, session_id=None):
            payload = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}).encode("utf-8")
            request = urllib.request.Request(
                base_url + "/sse",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            if session_id:
                request.add_header("Mcp-Session-Id", session_id)
            with urllib.request.urlopen(request, timeout=5) as response:
                return response, json.loads(response.read().decode("utf-8"))

        try:
            health = get_json("/health")
            self.assertTrue(health["mock"])
            self.assertEqual(health["transport"], "streamable_http")

            response, initialized = rpc("initialize")
            session_id = response.headers["Mcp-Session-Id"]
            self.assertIn("instructions", initialized["result"])
            self.assertTrue(session_id.startswith("mock-"))

            _response, tools_payload = rpc("tools/list", request_id=2, session_id=session_id)
            tool_names = {tool["name"] for tool in tools_payload["result"]["tools"]}
            self.assertIn("doctor", tool_names)
            self.assertIn("inspect_design", tool_names)

            _response, doctor_payload = rpc("tools/call", {"name": "doctor", "arguments": {}}, request_id=3, session_id=session_id)
            doctor_text = doctor_payload["result"]["content"][0]["text"]
            self.assertIn("fusion-mcp-mock", doctor_text)
            self.assertIn('"toolExecutionReady": true', doctor_text)

            _response, edit_payload = rpc(
                "tools/call",
                {"name": "edit_fillet_radius", "arguments": {"feature_name": "MockFillet", "radius": "2 mm"}},
                request_id=5,
                session_id=session_id,
            )
            edit_text = edit_payload["result"]["content"][0]["text"]
            self.assertIn("MockFillet", edit_text)
            self.assertIn("Mock mode does not edit Fusion geometry", edit_text)

            _response, flat_payload = rpc(
                "tools/call",
                {"name": "export_flat_pattern", "arguments": {"export_path": "C:\\Temp\\panel.dxf"}},
                request_id=6,
                session_id=session_id,
            )
            flat_text = flat_payload["result"]["content"][0]["text"]
            self.assertIn('"exported": true', flat_text)
            self.assertIn("Mock mode does not write flat-pattern files", flat_text)

            _response, resource_payload = rpc("resources/read", {"uri": "fusion://design/summary"}, request_id=4, session_id=session_id)
            self.assertIn("Mock Fusion Toolsmith Design", resource_payload["result"]["contents"][0]["text"])

            delete_request = urllib.request.Request(
                base_url + "/sse",
                headers={"Mcp-Session-Id": session_id},
                method="DELETE",
            )
            with urllib.request.urlopen(delete_request, timeout=5) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_mock_server_specializes_high_value_tool_flows(self):
        from fusion_mcp_cli.mock_server import SPECIALIZED_MOCK_TOOLS, _mock_tool_result

        required = {
            "inspect_analysis_capabilities",
            "verify_insert_alignment",
            "exact_interference_check",
            "exact_clearance_check",
            "export_asset",
            "export_flat_pattern",
            "plan_sheet_metal_workflow",
            "plan_surface_repair",
            "create_2d_drawing",
            "plan_drawing_views",
            "add_drawing_view",
            "add_drawing_dimension",
            "add_drawing_callout",
            "add_parts_list",
            "add_revision_table",
            "inspect_simulation_workspace",
            "list_simulation_studies",
            "plan_simulation_study",
            "plan_manufacturing_operation",
            "create_manufacturing_setup",
            "create_manufacturing_operation",
            "generate_toolpaths",
            "post_process",
            "capture_demo_sequence",
            "create_offset_plane",
            "create_construction_point",
            "create_construction_axis",
            "create_rigid_joint",
            "plan_joint_limits",
            "set_joint_limits",
            "create_flange",
            "create_bend",
            "unfold_sheet_metal",
            "refold_sheet_metal",
            "patch_surface",
            "stitch_surfaces",
            "thicken_surface",
            "trim_surface",
            "extend_surface",
            "create_ruled_surface",
            "add_sketch_constraint",
            "delete_sketch_constraint",
            "delete_named_experiment",
            "create_rounded_rectangle_body",
            "create_rounded_slot_cut",
            "create_rounded_pocket",
            "create_hole_pattern",
            "create_counterbore_hole_pattern",
            "copy_profile_loop",
            "offset_profile_loop",
            "create_insert_socket",
            "extrude_existing_profile",
            "mirror_features_or_bodies",
            "pattern_feature",
            "repair_mesh_body",
            "reduce_mesh_body",
            "remesh_body",
            "inspect_mesh_bodies",
            "plan_mesh_conversion",
            "inspect_design_configurations",
            "plan_design_variant",
            "inspect_render_workspace",
            "plan_render_output",
            "inspect_document_management_state",
            "plan_document_management_action",
            "export_document_copy",
            "inspect_electronics_workspace",
            "plan_pcb_enclosure_fit",
            "inspect_simulation_workspace",
            "list_simulation_studies",
            "plan_simulation_study",
            "set_visibility",
            "apply_appearance",
            "inspect_3mf_archive",
            "plan_multicolor_3mf_export",
            "apply_design_variant_parameters",
            "modify_parameters",
            "set_parameter",
            "export_parameters_csv",
            "import_parameters_csv",
        }
        self.assertTrue(required <= SPECIALIZED_MOCK_TOOLS)

        analysis_result = _mock_tool_result("inspect_analysis_capabilities", {})
        self.assertTrue(analysis_result["result"]["readOnly"])
        self.assertFalse(analysis_result["result"]["exactInterference"]["supported"])

        exact_interference = _mock_tool_result("exact_interference_check", {})
        self.assertTrue(exact_interference["result"]["readOnly"])
        self.assertFalse(exact_interference["result"]["validatedExact"])

        exact_clearance = _mock_tool_result("exact_clearance_check", {"minimum_clearance": "0.5 mm"})
        self.assertTrue(exact_clearance["result"]["readOnly"])
        self.assertEqual(exact_clearance["result"]["method"], "measure_manager_minimum_distance")

        alignment = _mock_tool_result("verify_insert_alignment", {
            "plate_body_name": "MockPlate",
            "socket_body_name": "MockSocket",
            "logo_body_names": ["MockLogo"],
            "mock_separated_logo": True,
        })
        self.assertTrue(alignment["result"]["readOnly"])
        self.assertFalse(alignment["result"]["okToExport"])
        self.assertTrue(alignment["result"]["checks"]["mirroredOrSeparatedGeometrySuspect"])

        cleanup = _mock_tool_result("delete_named_experiment", {
            "names": ["MockExperimentFeature"],
            "reason": "Mock cleanup preview.",
        })
        self.assertTrue(cleanup["result"]["dryRun"])
        self.assertFalse(cleanup["result"]["deleted"])

        socket = _mock_tool_result("create_insert_socket", {
            "source_sketch_name": "MockSketch",
            "target_body_name": "MockTarget",
            "insert_thickness": "2 mm",
            "reason": "Mock insert socket.",
        })
        self.assertTrue(socket["result"]["created"])
        self.assertTrue(socket["result"]["alignmentVerification"]["okToExport"])

        mesh_inspection = _mock_tool_result("inspect_mesh_bodies", {})
        self.assertTrue(mesh_inspection["result"]["readOnly"])
        self.assertEqual(mesh_inspection["result"]["meshBodyCount"], 1)

        mesh_plan = _mock_tool_result("plan_mesh_conversion", {"body_name": "Mock Mesh Body"})
        self.assertTrue(mesh_plan["result"]["readOnly"])
        self.assertFalse(mesh_plan["result"]["ready"])

        mesh_repair = _mock_tool_result("repair_mesh_body", {"mesh_body_name": "Mock Mesh Body"})
        self.assertTrue(mesh_repair["result"]["repaired"])
        mesh_reduce = _mock_tool_result("reduce_mesh_body", {"mesh_body_name": "Mock Mesh Body"})
        self.assertTrue(mesh_reduce["result"]["reduced"])
        mesh_remesh = _mock_tool_result("remesh_body", {"mesh_body_name": "Mock Mesh Body"})
        self.assertTrue(mesh_remesh["result"]["remeshed"])

        config_inspection = _mock_tool_result("inspect_design_configurations", {})
        self.assertTrue(config_inspection["result"]["readOnly"])
        self.assertEqual(config_inspection["result"]["configurationCount"], 2)

        variant_plan = _mock_tool_result("plan_design_variant", {"variant_name": "Wide"})
        self.assertTrue(variant_plan["result"]["readOnly"])
        self.assertFalse(variant_plan["result"]["okToProceed"])

        variant_apply = _mock_tool_result("apply_design_variant_parameters", {
            "variant_name": "Wide",
            "parameter_changes": {"width": "100 mm"},
            "requires_user_approval": True,
        })
        self.assertTrue(variant_apply["result"]["applied"])
        self.assertEqual(variant_apply["result"]["parameterCount"], 1)

        render_workspace = _mock_tool_result("inspect_render_workspace", {})
        self.assertTrue(render_workspace["result"]["readOnly"])
        self.assertTrue(render_workspace["result"]["activeViewportAvailable"])

        render_plan = _mock_tool_result("plan_render_output", {"camera_name": "activeViewport"})
        self.assertTrue(render_plan["result"]["readOnly"])
        self.assertFalse(render_plan["result"]["okToProceed"])

        render_output = _mock_tool_result("render_viewport_output", {"camera_name": "activeViewport", "output_path": "C:/Temp/mock-render.png"})
        self.assertTrue(render_output["result"]["rendered"])
        self.assertGreater(render_output["result"]["sizeBytes"], 0)

        document_state = _mock_tool_result("inspect_document_management_state", {})
        self.assertTrue(document_state["result"]["readOnly"])
        self.assertTrue(document_state["result"]["cloudDataAvailable"])

        document_plan = _mock_tool_result("plan_document_management_action", {"action": "export_copy"})
        self.assertTrue(document_plan["result"]["readOnly"])
        self.assertFalse(document_plan["result"]["okToProceed"])

        document_copy = _mock_tool_result("export_document_copy", {"target_path": "C:/Temp/mock-copy.f3d"})
        self.assertTrue(document_copy["result"]["exported"])
        self.assertGreater(document_copy["result"]["sizeBytes"], 0)

        electronics_workspace = _mock_tool_result("inspect_electronics_workspace", {})
        self.assertTrue(electronics_workspace["result"]["readOnly"])
        self.assertTrue(electronics_workspace["result"]["workspaceAvailable"])

        pcb_fit_plan = _mock_tool_result("plan_pcb_enclosure_fit", {"board_outline": {"width": "80 mm"}})
        self.assertTrue(pcb_fit_plan["result"]["readOnly"])
        self.assertFalse(pcb_fit_plan["result"]["okToProceed"])

        simulation_workspace = _mock_tool_result("inspect_simulation_workspace", {})
        self.assertTrue(simulation_workspace["result"]["readOnly"])
        self.assertTrue(simulation_workspace["result"]["workspaceAvailable"])

        simulation_plan = _mock_tool_result("plan_simulation_study", {"study_name": "Mock Study"})
        self.assertTrue(simulation_plan["result"]["readOnly"])
        self.assertFalse(simulation_plan["result"]["okToProceed"])

        surface_plan = _mock_tool_result("plan_surface_repair", {
            "operation": "stitch_surfaces",
            "body_name": "Mock Surface",
            "edge_entity_tokens": ["edge-token"],
            "reason": "mock test",
        })
        self.assertTrue(surface_plan["result"]["readOnly"])
        self.assertTrue(surface_plan["result"]["okToProceed"])
        self.assertEqual(surface_plan["result"]["operation"], "stitch_surfaces")

        surface_patch = _mock_tool_result("patch_surface", {
            "body_name": "Mock Surface",
            "edge_entity_tokens": ["edge-token"],
            "parameters": {"tolerance": "0.01 mm"},
            "reason": "mock test",
        })
        self.assertEqual(surface_patch["result"]["operation"], "patch_surface")
        self.assertIn("stateComparison", surface_patch["result"])

        sheet_plan = _mock_tool_result("plan_sheet_metal_workflow", {
            "operation": "create_flange",
            "body_name": "Mock Sheet Metal Body",
            "edge_entity_tokens": ["edge-token"],
            "rule_name": "Mock Sheet Metal Rule",
            "reason": "mock test",
        })
        self.assertTrue(sheet_plan["result"]["readOnly"])
        self.assertTrue(sheet_plan["result"]["okToProceed"])
        self.assertEqual(sheet_plan["result"]["operation"], "create_flange")

        flange_result = _mock_tool_result("create_flange", {
            "body_name": "Mock Sheet Metal Body",
            "edge_entity_tokens": ["edge-token"],
            "rule_name": "Mock Sheet Metal Rule",
            "parameters": {"height": "12 mm"},
            "reason": "mock test",
        })
        self.assertEqual(flange_result["result"]["operation"], "create_flange")
        self.assertIn("stateComparison", flange_result["result"])

        joint_plan = _mock_tool_result("plan_joint_limits", {
            "joint_name": "Mock Joint",
            "limit_type": "rotation",
            "minimum": "0 deg",
            "maximum": "90 deg",
            "reason": "mock test",
        })
        self.assertTrue(joint_plan["result"]["readOnly"])
        self.assertTrue(joint_plan["result"]["okToProceed"])
        self.assertEqual(joint_plan["result"]["limitType"], "rotation")

        joint_limits = _mock_tool_result("set_joint_limits", {
            "joint_name": "Mock Joint",
            "limit_type": "rotation",
            "minimum": "0 deg",
            "maximum": "90 deg",
            "reason": "mock test",
        })
        self.assertEqual(joint_limits["result"]["jointName"], "Mock Joint")
        self.assertIn("stateComparison", joint_limits["result"])

        export_result = _mock_tool_result("export_asset", {"format": "step", "export_path": "C:\\Temp\\model.step"})
        self.assertTrue(export_result["result"]["exported"])
        self.assertIn("preflight", export_result["result"])
        self.assertIn("Mock mode does not write export files", export_result["result"]["note"])

        drawing_result = _mock_tool_result("create_2d_drawing", {"drawing_name": "Client Flow Drawing"})
        self.assertTrue(drawing_result["result"]["created"])
        self.assertEqual(drawing_result["result"]["drawingDocumentName"], "Client Flow Drawing")
        self.assertIn("stateComparison", drawing_result["result"])

        plan_result = _mock_tool_result("plan_drawing_views", {"views": {"name": "Front", "orientation": "front", "scale": 0.5}})
        self.assertTrue(plan_result["result"]["readOnly"])
        self.assertEqual(plan_result["result"]["views"][0]["name"], "Front")
        self.assertIn("preflight", plan_result["result"])

        drawing_callout = _mock_tool_result("add_drawing_callout", {
            "text": "CHECK FIT",
            "reason": "mock test",
        })
        self.assertEqual(drawing_callout["result"]["operation"], "add_drawing_callout")
        self.assertIn("stateComparison", drawing_callout["result"])

        cam_plan = _mock_tool_result("plan_manufacturing_operation", {
            "setup_name": "Setup1",
            "operation_name": "Adaptive1",
            "operation_type": "adaptive",
            "machine": {"name": "Shop Mill"},
            "stock": {"material": "6061"},
            "wcs": {"origin": "stock"},
            "tool": {"name": "6mm flat"},
            "feeds": {"cut": 500},
            "speeds": {"rpm": 12000},
            "post_processor": {"name": "generic"},
            "requires_user_approval": True,
        })
        self.assertTrue(cam_plan["result"]["readOnly"])
        self.assertTrue(cam_plan["result"]["okToProceed"])
        self.assertEqual(cam_plan["result"]["operation"]["type"], "adaptive")

        toolpaths = _mock_tool_result("generate_toolpaths", {
            "setup_name": "Setup1",
            "operation_name": "Adaptive1",
            "requires_user_approval": True,
        })
        self.assertTrue(toolpaths["result"]["generated"])
        self.assertIn("stateComparison", toolpaths["result"])

        posted = _mock_tool_result("post_process", {
            "setup_name": "Setup1",
            "operation_name": "Adaptive1",
            "output_path": "C:\\Temp\\part.nc",
            "requires_user_approval": True,
        })
        self.assertTrue(posted["result"]["posted"])
        self.assertEqual(posted["result"]["outputPath"], "C:\\Temp\\part.nc")

        demo_result = _mock_tool_result("capture_demo_sequence", {"steps": [{"camera": "front"}, {"camera": "iso"}]})
        self.assertEqual(demo_result["result"]["frameCount"], 2)
        self.assertEqual(demo_result["result"]["frames"][1]["path"], "mock://capture/demo-frame-2.png")

    def test_mock_server_specializes_registered_mutating_tool_prefixes(self):
        from fusion_mcp_cli.mock_server import SPECIALIZED_MOCK_TOOLS
        from fusion_mcp_cli.offline_schema import load_offline_mcp_surface

        surface = load_offline_mcp_surface()
        mutating_prefixes = (
            "create_",
            "add_",
            "edit_",
            "set_",
            "export_",
            "generate_",
            "post_",
            "patch_",
            "stitch_",
            "thicken_",
            "trim_",
            "extend_",
            "unfold_",
            "refold_",
            "delete_",
            "suppress_",
            "apply_",
            "modify_",
            "import_",
            "mirror_",
            "pattern_",
            "offset_",
            "shell_",
            "revolve_",
            "loft_",
            "sweep_",
            "convert_",
            "reorganize_",
        )
        mutating_tools = {
            tool["name"]
            for tool in surface["tools"]
            if tool["name"].startswith(mutating_prefixes)
        }

        self.assertEqual(sorted(mutating_tools - SPECIALIZED_MOCK_TOOLS), [])

    def test_mock_payload_examples_match_generator(self):
        from fusion_mcp_cli.mock_server import _mock_tool_result

        examples_path = os.path.join(ROOT, "docs", "mock-payload-examples.md")
        with open(examples_path, "r", encoding="utf-8") as f:
            docs = f.read()

        sections = re.findall(
            r"## `([^`]+)`\s+Arguments:\s+```json\s+(.*?)\s+```\s+Response payload:\s+```json\s+(.*?)\s+```",
            docs,
            flags=re.DOTALL,
        )
        self.assertGreaterEqual(len(sections), 5)
        documented_tools = set()
        for tool_name, arguments_text, response_text in sections:
            documented_tools.add(tool_name)
            arguments = json.loads(arguments_text)
            expected_response = json.loads(response_text)
            self.assertEqual(expected_response, _mock_tool_result(tool_name, arguments))

        for tool_name in [
            "inspect_analysis_capabilities",
            "plan_surface_repair",
            "create_revolute_joint",
            "plan_manufacturing_operation",
            "revolve_feature",
        ]:
            self.assertIn(tool_name, documented_tools)

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
            "inspect_selection_sets",
            "inspect_3mf_archive",
            "plan_multibody_3mf_export",
            "plan_multicolor_3mf_export",
            "inspect_mesh_bodies",
            "plan_mesh_conversion",
            "repair_mesh_body",
            "reduce_mesh_body",
            "remesh_body",
            "inspect_design_configurations",
            "plan_design_variant",
            "apply_design_variant_parameters",
            "inspect_render_workspace",
            "plan_render_output",
            "render_viewport_output",
            "inspect_document_management_state",
            "plan_document_management_action",
            "export_document_copy",
            "inspect_electronics_workspace",
            "plan_pcb_enclosure_fit",
            "inspect_simulation_workspace",
            "list_simulation_studies",
            "plan_simulation_study",
            "capture_demo_sequence",
            "render_viewport_output",
            "fusion://agent/server-capabilities",
            "Initialize-time agent instructions",
            "MCP tool risk annotations",
            "MCP resource ranking annotations",
            "Offline MCP schema export",
            "docs/mock-payload-examples.md",
        ]:
            self.assertIn(text, roadmap)

    def test_external_fusion_mcp_sweep_documents_adopted_patterns(self):
        with open(os.path.join(ROOT, "docs", "external-fusion-mcp-sweep.md"), "r", encoding="utf-8") as f:
            sweep = f.read()
        for text in [
            "frankhommers/autodesk-fusion-mcp",
            "faust-machines/fusion360-mcp-server",
            "ndoo/fusion360-mcp-bridge",
            "JustusBraitinger/FusionMCP",
            "Streamable HTTP",
            "fusion-mcp dump-schemas",
            "run_fusion_script",
            "project-specific tools",
        ]:
            self.assertIn(text, sweep)


if __name__ == "__main__":
    unittest.main()
