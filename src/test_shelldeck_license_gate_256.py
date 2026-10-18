import unittest
from shelldeck_license_gate_256 import audit


class LicenseGateTests(unittest.TestCase):
    def setUp(self):
        self.report = {"lock_present": True, "locked_packages": [
            {"name": "sample", "version": "1.2.3", "source": "registry+example"}]}

    def test_no_lock_is_blocked(self):
        result = audit({"lock_present": False, "locked_packages": []}, {"packages": []})
        self.assertFalse(result["evidence_complete"])

    def test_missing_evidence_is_blocked(self):
        self.assertFalse(audit(self.report, {"packages": []})["evidence_complete"])

    def test_complete_inventory_still_requires_legal_review(self):
        proof = {"packages": [{"name": "sample", "version": "1.2.3",
            "source": "registry+example", "license_expression": "MIT",
            "license_file_checked": True, "redistribution_checked": True,
            "reviewer": "manual"}]}
        result = audit(self.report, proof)
        self.assertTrue(result["evidence_complete"])
        self.assertFalse(result["license_approved"])

    def test_wrong_version_does_not_count(self):
        proof = {"packages": [{"name": "sample", "version": "9.9.9",
            "source": "registry+example", "license_expression": "MIT",
            "license_file_checked": True, "redistribution_checked": True,
            "reviewer": "manual"}]}
        self.assertFalse(audit(self.report, proof)["evidence_complete"])
