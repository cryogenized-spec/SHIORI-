"""Guard the planned contextual-intent MCP contract against accidental exposure.

These operations are *not* deployed. Live agent use requires authenticated
SHIORI application services, host-verified source/outcome evidence, and sync.
"""
import json
import unittest
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "docs/api/operations.v1.json"

EXPECTED = {
    "intent.resolve": ("read", "none"),
    "intent.rules.list": ("read", "none"),
    "intent.correction.record": ("write", "explicit_user_action"),
    "intent.outcome.record": ("write", "explicit_user_action"),
    "intent.rules.revoke": ("destructive", "explicit_user_action"),
}


class TestContextualIntentRegistry(unittest.TestCase):
    def test_intent_contract_is_discoverable_but_not_deployed(self):
        catalog = json.loads(MANIFEST.read_text(encoding="utf-8"))
        by_id = {operation["id"]: operation for operation in catalog["operations"]}
        for name, (effect, approval) in EXPECTED.items():
            with self.subTest(operation=name):
                self.assertIn(name, by_id)
                op = by_id[name]
                self.assertEqual(op["availability"], "planned")
                self.assertEqual(op["effect"], effect)
                self.assertEqual(op["approval"], approval)
                self.assertEqual(op["scope"], "intent:read" if effect == "read"
                                 else "intent:write")
                self.assertEqual(op["mcp_tool"], "shiori_" + name.replace(".", "_"))
                self.assertNotIn("implementation", op)
                self.assertEqual(op["inputSchema"]["additionalProperties"], False)
                self.assertEqual(op["outputSchema"]["additionalProperties"], False)
                if effect != "read":
                    self.assertIn("idempotency_key", op["inputSchema"]["required"])

    def test_explanation_only_never_executes(self):
        catalog = json.loads(MANIFEST.read_text(encoding="utf-8"))
        lookup = next(op for op in catalog["operations"] if op["id"] == "intent.resolve")
        response = lookup["outputSchema"]["properties"]["data"]
        self.assertEqual(response["properties"]["executed"], {"const": False})
        self.assertIn("expression", lookup["inputSchema"]["required"])

    def test_outcome_requires_trusted_receipt_and_revision(self):
        catalog = json.loads(MANIFEST.read_text(encoding="utf-8"))
        outcome = next(op for op in catalog["operations"]
                       if op["id"] == "intent.outcome.record")
        for field in ("rule_id", "receipt_id", "expected_revision",
                      "idempotency_key"):
            self.assertIn(field, outcome["inputSchema"]["required"])


if __name__ == "__main__":
    unittest.main()
