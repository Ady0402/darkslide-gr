"""Saved bundle ingress count; the core verifier has separate byte tests."""
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
try:
    import verify_four_validation as reader
except ImportError:  # dev-only verifier, not part of the published app
    raise unittest.SkipTest("开发仓库根目录 tools/ 下的独立核对工具不随发布包分发；在开发仓库里运行时这项测试照常执行")


class FourBundleTests(unittest.TestCase):
    def test_saved_plan_accepts49_rejects_legacy47(self):
        raw = bytes(range(64))  # Entirely self-authored fixture, no firmware.
        sha = hashlib.sha256(raw).hexdigest()
        rows = [dict(address=i, expected_sha256=hashlib.sha256(raw[i:i+1]).hexdigest(),
                     replacement_hex='01') for i in range(49)]
        bundle = dict(original_bytes=len(raw), original_sha256=sha,
                      edits=[], profiles={}, windows=rows)
        with patch.object(reader, 'ORIGINAL_BYTES', len(raw)), \
             patch.object(reader, 'ORIGINAL_SHA', sha), \
             patch.object(reader, '_offset', side_effect=lambda address, count: address), \
             patch.object(reader, 'verify_plan', return_value={'passed': True}) as core:
            self.assertTrue(reader.verify_bundle(raw, bundle)['passed'])
            self.assertEqual(len(core.call_args[0][1]['windows']), 49)
            core.reset_mock()
            with self.assertRaises(ValueError):
                reader.verify_bundle(raw, dict(bundle, windows=rows[:47]))
            core.assert_not_called()


if __name__ == '__main__':
    unittest.main()
