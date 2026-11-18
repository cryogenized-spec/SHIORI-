"""Contract-level guardrails for the S3 paired-device owner controls."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = json.loads((ROOT / "docs/api/operations.v1.json").read_text(encoding="utf-8"))["operations"]


class DeviceRevocationContract(unittest.TestCase):
    def test_separate_read_and_write_permissions(self):
        operations = {x["id"]: x for x in OPERATIONS}
        status = operations["sync.device.status.read"]
        revoke = operations["sync.device.revoke"]
        self.assertEqual(status["availability"], "cloudflare_alpha")
        self.assertEqual(revoke["availability"], "cloudflare_alpha")
        self.assertEqual((status["effect"], status["scope"], status["approval"]), ("read", "sync:read", "none"))
        self.assertEqual((revoke["effect"], revoke["scope"], revoke["approval"]), ("write", "sync:write", "contextual"))
        self.assertEqual(status["mcp_tool"], "shiori_sync_device_status_read")
        self.assertEqual(revoke["mcp_tool"], "shiori_sync_device_revoke")

    def test_revoke_requires_explicit_confirmation_and_idempotency(self):
        operations = {x["id"]: x for x in OPERATIONS}
        revoke = operations["sync.device.revoke"]["inputSchema"]
        status = operations["sync.device.status.read"]["inputSchema"]
        self.assertFalse(revoke["additionalProperties"])
        self.assertEqual(set(revoke["required"]), {"workspace_id", "device_id", "confirm_revocation", "idempotency_key"})
        self.assertEqual(revoke["properties"]["confirm_revocation"]["type"], "boolean")
        self.assertGreaterEqual(revoke["properties"]["idempotency_key"]["minLength"], 8)
        self.assertNotIn("confirm_revocation", status["properties"])
        self.assertEqual(set(status["required"]), {"workspace_id", "device_id"})

    def test_status_is_metadata_only_and_revoke_is_not_a_delete(self):
        operations = {x["id"]: x for x in OPERATIONS}
        status = operations["sync.device.status.read"]["outputSchema"]["properties"]["data"]["properties"]
        revoke = operations["sync.device.revoke"]["outputSchema"]["properties"]["data"]["properties"]
        self.assertEqual(set(status), {"device_id", "paired_at", "revoked_at", "can_import"})
        self.assertEqual(set(revoke), {"changed", "device_id", "revoked_at"})
        self.assertNotIn("token", json.dumps(status).lower())
        self.assertNotIn("token", json.dumps(revoke).lower())
        self.assertEqual(len(operations), 124)


if __name__ == "__main__":
    unittest.main()
