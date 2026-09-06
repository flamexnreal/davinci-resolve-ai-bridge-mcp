import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge.operations import AGENT_VERSION
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('installer',ROOT/'install.py');installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.home=Path(self.tmp.name)
        self.config=self.home/'.cursor/mcp.json';self.config.parent.mkdir()
    def configure(self):
        with patch.object(Path,'home',return_value=self.home),patch('shutil.which',return_value=None):
            installer.auto_configure_clients({'command':'python','args':['server.py']})
    def test_invalid_config_preserved(self):
        content='{"mcpServers":{"other":{}},BROKEN}'
        self.config.write_text(content);self.configure();self.assertEqual(self.config.read_text(),content)
    def test_nonobject_config_preserved(self):
        self.config.write_text('[]');self.configure();self.assertEqual(self.config.read_text(),'[]')
    def test_existing_entries_preserved_and_backed_up(self):
        self.config.write_text(json.dumps({'mcpServers':{'other':{'command':'other'}},'setting':True}));before=self.config.read_text()
        self.configure();data=json.loads(self.config.read_text());self.assertIn('other',data['mcpServers']);self.assertTrue(data['setting'])
        self.assertEqual(next(self.config.parent.glob('*.backup-*')).read_text(),before)
    def test_version_consistency(self):
        self.assertEqual(installer.VERSION,AGENT_VERSION)
        self.assertEqual(json.loads((ROOT/'package.json').read_text())['version'],AGENT_VERSION)
        self.assertIn('version = "%s"'%AGENT_VERSION,(ROOT/'pyproject.toml').read_text())
    def test_required_npm_payload(self):
        package=json.loads((ROOT/'package.json').read_text());self.assertIn('requirements.txt',package['files'])
        self.assertNotIn('react',package.get('dependencies',{}));self.assertNotIn('main',package)
    def test_python_sources_compile(self):
        for p in list((ROOT/'bridge').glob('*.py'))+list((ROOT/'agent').rglob('*.py'))+[ROOT/'install.py']:
            compile(p.read_text(),str(p),'exec')
