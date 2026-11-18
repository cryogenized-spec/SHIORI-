"""Validate SHIORI's *planned* remote operation registry without network.

This is a contract-consistency test, not a declaration that any remote
operation has been implemented. Full JSON Schema and auth tests are a
separate gate before a tool is marked available.
"""
import json
import unittest
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "docs/api/operations.v1.json"
WRITE_EFFECTS = {"write", "view_write", "external", "destructive"}
EFFECTS = WRITE_EFFECTS | {"read", "transient"}
CODES = {"VALIDATION_FAILED", "NOT_FOUND", "UNAUTHENTICATED", "FORBIDDEN",
         "CONFLICT", "PRECONDITION_REQUIRED", "RATE_LIMITED",
         "UNSUPPORTED_CAPABILITY", "UNAVAILABLE", "INTERNAL_ERROR"}


class TestRemoteOperationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.ops = cls.catalog["operations"]

    def test_unique_individually_addressable_tools_and_http_paths(self):
        self.assertGreaterEqual(len(self.ops), 100)
        for field in ("id", "mcp_tool"):
            values = [op[field] for op in self.ops]
            self.assertEqual(len(values), len(set(values)), field)
        paths = [op["http"]["path"] for op in self.ops]
        self.assertEqual(len(paths), len(set(paths)))
        for op in self.ops:
            self.assertEqual(op["http"]["method"], "POST")
            self.assertEqual(op["http"]["path"], "/api/v1/ops/" + op["id"])
            self.assertEqual(op["mcp_tool"], "shiori_" + op["id"].replace(".", "_"))
            alpha = {"system.capabilities.read", "system.operations.list", "tasks.list", "tasks.get",
                     "tasks.create", "tasks.status.set", "tasks.dependencies.list",
                     "spatial.scene.read", "spatial.node.position.set",
                     "spatial.edge.style.set", "tasks.dependencies.add",
                     "tasks.update", "tasks.delete", "tasks.restore",
                     "tasks.priority.set", "tasks.dependencies.remove",
                     "spatial.node.position.read", "spatial.viewport.read",
                     "spatial.viewport.save", "spatial.layout.lock.set",
                     "spatial.node.inspect", "spatial.scene.export",
                     "sync.manifest.read","sync.device.pair","sync.import.preview",
                     "sync.import.apply","sync.import.receipt.read","sync.changes.read",
                     "sync.baseline.read","sync.device.status.read","sync.device.revoke"}
            self.assertEqual(
                op["availability"],
                "cloudflare_alpha" if op["id"] in alpha else "planned"
            )
            if op["id"] == "system.operations.list":
                self.assertEqual(op["data_source"], "bundled-static-schema-not-task-data")
            elif op["id"] in alpha:
                self.assertEqual(
                    op["data_source"], "isolated_remote_d1_not_synced_with_local_rust"
                )
        self.assertEqual(self.catalog["mcp"]["endpoint"], "/mcp")
        self.assertEqual(len([op for op in self.ops if op["availability"] == "cloudflare_alpha"]), 31)

    def test_every_operation_has_typed_bounded_input_and_output(self):
        for op in self.ops:
            with self.subTest(op=op["id"]):
                request, response = op["inputSchema"], op["outputSchema"]
                self.assertEqual(request["type"], "object")
                self.assertIs(request["additionalProperties"], False)
                self.assertIn("workspace_id", request["required"])
                self.assertIn("workspace_id", request["properties"])
                self.assertEqual(len(request["required"]), len(set(request["required"])))
                self.assertTrue(set(request["required"]) <= set(request["properties"]))
                self.assertEqual(response["type"], "object")
                self.assertIs(response["additionalProperties"], False)
                self.assertEqual(response["properties"]["operation_id"]["const"], op["id"])
                self.assertIn("data", response["required"])
                self.assertIn("data", response["properties"])
                self.assertIn(op["effect"], EFFECTS)
                self.assertIn(op["phase"], {"A", "B", "C", "D"})
                if op["effect"] in WRITE_EFFECTS:
                    self.assertIn("idempotency_key", request["required"])

    def test_agent_ui_commands_require_attached_session(self):
        for name in ("spatial.focus.set", "spatial.selection.set",
                     "spatial.zoom.toggle", "spatial.camera.fit",
                     "spatial.context_menu.open", "companion.dock.set"):
            op = next(o for o in self.ops if o["id"] == name)
            self.assertIn("ui_session_id", op["inputSchema"]["required"])
            self.assertEqual(op["effect"], "transient")

    def test_semantic_edits_and_external_effects_are_reviewed(self):
        expected = ("graph.edges.create", "graph.edges.delete",
                    "graph.restructure.apply", "tasks.dependencies.apply",
                    "inbox.convert.apply", "eai.scene.save")
        for name in expected:
            op = next(o for o in self.ops if o["id"] == name)
            self.assertEqual(op["approval"], "reviewed_diff_required")
        for op in self.ops:
            if op["effect"] in {"external", "destructive"}:
                self.assertNotEqual(op["approval"], "none")

    def test_structural_scopes_and_core_coverage(self):
        by_id = {op["id"]: op for op in self.ops}
        for name in ("tasks.get", "inbox.capture", "artifacts.attachments.list",
                     "graph.traverse.read", "retrieval.context.fetch",
                     "spatial.node.position.set", "spatial.edge.style.set",
                     "eai.object.add", "companion.threads.list",
                     "automations.run.preview", "providers.github.tree.preview",
                     "providers.clickup.sync.preview", "scheduling.plan.preview"):
            self.assertIn(name, by_id)
        self.assertTrue(CODES <= set(self.catalog["error_codes"]))
        for op in self.ops:
            self.assertTrue(op["scope"].startswith(op["id"].split(".")[0] + ":"))


if __name__ == "__main__":
    unittest.main()
