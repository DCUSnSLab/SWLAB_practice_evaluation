import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from llm_config import llm_settings
from llm_cases import LLMClient


class Settings:
    def value(self, key, default=None):
        return {'llm_url': 'https://saved.example.invalid', 'llm_model': 'saved-model'}.get(key, default)


class LLMConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'settings.local.json'
        env = patch.dict(os.environ, {'SWLAB_CONFIG': str(self.path)})
        env.start(); self.addCleanup(env.stop)
        for variable in ('SWLAB_LLM_URL', 'SWLAB_LLM_MODEL', 'SWLAB_LLM_API_KEY'):
            os.environ.pop(variable, None)

    def test_no_deployment_defaults_and_no_network_if_unconfigured(self):
        self.assertEqual(llm_settings(), {'url': '', 'model': '', 'api_key': ''})
        with patch('urllib.request.urlopen') as request:
            with self.assertRaisesRegex(ValueError, 'SWLAB_LLM_URL'):
                LLMClient()
            with self.assertRaisesRegex(ValueError, 'SWLAB_LLM_MODEL'):
                LLMClient('https://example.invalid')
            request.assert_not_called()

    def test_environment_saved_settings_and_local_file_precedence(self):
        self.path.write_text(json.dumps({'llm': {'url': 'https://local.example.invalid',
            'model': 'local-model', 'api_key': 'local-test-key'}}), encoding='utf-8')
        client = LLMClient()
        self.assertEqual(client.base_url, 'https://local.example.invalid/v1')
        self.assertEqual(client.model, 'local-model')
        self.assertEqual(llm_settings(Settings())['model'], 'saved-model')
        with patch.dict(os.environ, {'SWLAB_LLM_URL': 'https://env.example.invalid/v1',
                'SWLAB_LLM_MODEL': 'env-model', 'SWLAB_LLM_API_KEY': 'env-test-key'}):
            self.assertEqual(llm_settings(Settings())['model'], 'env-model')
            client = LLMClient('https://explicit.example.invalid', 'explicit-model', api_key='explicit-test-key')
            self.assertEqual(client.base_url, 'https://explicit.example.invalid/v1')
            self.assertEqual(client.model, 'explicit-model')
            self.assertEqual(client.api_key, 'explicit-test-key')
            with self.assertRaises(ValueError):
                LLMClient('', 'explicit-model')

    def test_model_discovery_works_before_model_selection(self):
        client = LLMClient('https://example.invalid', '', require_model=False)
        with patch.object(client, '_request', return_value={'data': [{'id': 'available-model'}]}) as request:
            self.assertEqual(client.models(), ['available-model'])
            self.assertEqual(request.call_args.args, ('/models',))
            with self.assertRaisesRegex(ValueError, 'SWLAB_LLM_MODEL'):
                client.generate('problem')

    def test_invalid_local_config_is_actionable(self):
        for contents in ('invalid json', '[]', '{"llm": []}', '{"llm": {"model": 123}}'):
            self.path.write_text(contents, encoding='utf-8')
            with self.subTest(contents=contents), self.assertRaises(ValueError):
                llm_settings()


if __name__ == '__main__':
    unittest.main()
