import unittest
from check_release_version import validate

class VersionTests(unittest.TestCase):
    def test_batch_does_not_force_shared_versions(self):
        self.assertEqual(validate('v1.0.0', {'first':'1.2.0','second':'3.0.0'}), ('', '1.0.0'))

    def test_single_plugin_stable_and_prerelease(self):
        for version in ('1.0.1','1.1.0-beta.1'):
            self.assertEqual(validate('code-highlight/v'+version, {'code-highlight':version,'spreadsheet':'1.0.0'}), ('code-highlight',version))

    def test_rejects_invalid_tags_unknown_plugins_and_wrong_versions(self):
        for tag in ('v1.0', 'release-1.0.0','code-highlight/v1.0.0-','../v1.0.0','missing/v1.0.0','code-highlight/v1.0.1'):
            with self.assertRaises(ValueError):
                validate(tag, {'code-highlight':'1.0.0'})
        with self.assertRaises(ValueError):
            validate('v1.0.0', {})
        with self.assertRaises(ValueError):
            validate('v1.0.0', {'plugin':'broken'})
