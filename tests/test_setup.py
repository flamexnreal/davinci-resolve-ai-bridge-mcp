import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from bridge.operations import AGENT_VERSION
from installer_fakes import isolated_user_profile
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('installer',ROOT/'install.py');installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.home=Path(self.tmp.name)
        self.config=self.home/'.cursor/mcp.json';self.config.parent.mkdir()
    def configure(self):
        with isolated_user_profile(self.home),patch('shutil.which',return_value=None):
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
    def test_unchanged_client_registration_does_not_write_or_rotate_backups(self):
        content = b'{"mcpServers":{"resolve-ai-bridge":{"command":"python","args":["server.py"]}}}'
        self.config.write_bytes(content)
        self.configure()
        self.assertEqual(self.config.read_bytes(), content)
        self.assertEqual(list(self.config.parent.glob('*.backup-*')), [])

    def test_failed_client_replacement_keeps_previous_config_and_backups(self):
        content = b'{"mcpServers":{"unrelated":{"command":"keep"}}}'
        self.config.write_bytes(content)
        backups = [self.config.with_name('mcp.json.backup-%d' % i)
                   for i in range(installer.CONFIG_BACKUPS_KEPT)]
        for backup in backups:
            backup.write_text('old backup')
        with patch.object(installer.os, 'replace', side_effect=PermissionError('file in use')):
            self.configure()
        self.assertEqual(self.config.read_bytes(), content)
        self.assertTrue(all(backup.read_text() == 'old backup' for backup in backups))

    def test_changed_client_config_is_not_overwritten_during_registration(self):
        content = b'{"mcpServers":{"initial":{"command":"keep"}}}'
        changed = b'{"mcpServers":{"concurrent":{"command":"keep"}}}'
        self.config.write_bytes(content)
        fsync = os.fsync
        def update_on_backup(fd):
            fsync(fd)
            self.config.write_bytes(changed)
        with patch.object(installer.os, 'fsync', side_effect=update_on_backup):
            self.configure()
        self.assertEqual(self.config.read_bytes(), changed)

    def test_python_menu_uses_installed_runtime_and_preserves_unowned_scripts(self):
        runtime = self.home / "custom runtime's folder"
        runtime.mkdir()
        scripts = self.home / "resolve scripts"
        folder = scripts / "Utility" / installer.MENU_FOLDER
        folder.mkdir(parents=True)
        custom_script = folder / "My own script.py"
        custom_script.write_text("# user's Resolve script")
        unrelated_script = folder.parent / "add_explosion_overlay.py"
        unrelated_script.write_text("# unrelated user script")
        (runtime / "ResolveConsole.py").write_text(
            "def start_menu_bridge(namespace):\n"
            "    print(namespace['RESOLVE_AI_BRIDGE_RUNTIME_HOME'])\n",
            encoding="utf-8",
        )
        with patch.object(installer, 'HOME', runtime), \
                patch.object(installer, 'resolve_script_roots', return_value=[scripts]):
            self.assertEqual(installer.install_menu_scripts(), [str(folder)])
            launcher = folder / "Start AI Bridge.py"
            env = dict(os.environ, RESOLVE_AI_BRIDGE_HOME=str(self.home / 'other runtime'))
            run = subprocess.run([installer.sys.executable, str(launcher)], env=env,
                                 capture_output=True, text=True, check=True)
            self.assertEqual(run.stdout.strip(), str(runtime))
            status = folder / "Bridge Status.py"
            status.write_text("# user modified the launcher")
            self.assertEqual(len(installer.remove_menu_scripts()), len(installer.MENU_SCRIPTS) - 1)
            self.assertFalse(launcher.exists())
            self.assertTrue(status.is_file())
            self.assertTrue(custom_script.is_file())
            self.assertTrue(unrelated_script.is_file())

    def test_failed_menu_update_keeps_existing_launcher_and_reports_error(self):
        scripts = self.home / "resolve scripts"
        folder = scripts / "Utility" / installer.MENU_FOLDER
        folder.mkdir(parents=True)
        start = folder / "Start AI Bridge.py"
        start.write_text("existing launcher")
        output = io.StringIO()
        with patch.object(installer, 'resolve_script_roots', return_value=[scripts]), \
                patch.object(installer.os, 'replace', side_effect=PermissionError('file in use')), \
                redirect_stdout(output):
            self.assertEqual(installer.install_menu_scripts(), [])
        self.assertEqual(start.read_text(), "existing launcher")
        self.assertIn("Could not install", output.getvalue())
        self.assertEqual(list(folder.iterdir()), [start])

    def test_unwritable_existing_menu_root_falls_back_to_the_user_root(self):
        user = self.home / "user scripts"
        system = self.home / "existing Resolve scripts"
        system.mkdir()
        mkdir = Path.mkdir
        def make(path, *args, **kwargs):
            if system in path.parents:
                raise PermissionError("system menu folder is read-only")
            return mkdir(path, *args, **kwargs)
        with patch.object(installer, 'HOME', self.home), \
                patch.object(installer, 'resolve_script_roots', return_value=[user, system]), \
                patch.object(Path, 'mkdir', make), redirect_stdout(io.StringIO()):
            paths = installer.install_menu_scripts()
        folder = user / "Utility" / installer.MENU_FOLDER
        self.assertEqual(paths, [str(folder)])
        self.assertTrue((folder / "Start AI Bridge (Lua).lua").is_file())

    @unittest.skipUnless(os.name != "nt" and shutil.which("node"), "requires Node and a POSIX script fixture")
    def test_node_serve_expands_tilde_in_custom_runtime(self):
        runtime = self.home / "custom runtime"
        python = runtime / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\nprintf "%s\\n" "$RESOLVE_AI_BRIDGE_HOME" "$1"\n')
        python.chmod(0o700)
        server = runtime / "bridge" / "server.py"
        server.parent.mkdir()
        server.touch()
        env = dict(os.environ, HOME=str(self.home), RESOLVE_AI_BRIDGE_HOME="~/custom runtime")
        run = subprocess.run([shutil.which("node"), str(ROOT / "bin" / "cli.js"), "--serve"],
                             env=env, capture_output=True, text=True, check=True)
        self.assertEqual(run.stdout.splitlines(), [str(runtime), str(server)])
    def test_windows_appdata_is_isolated_from_the_client_profile(self):
        with tempfile.TemporaryDirectory() as ambient:
            outside = Path(ambient) / 'Claude' / 'claude_desktop_config.json'
            inside = self.home / 'AppData' / 'Roaming' / 'Claude' / outside.name
            for config in (outside, inside):
                config.parent.mkdir(parents=True)
                config.write_text('{"mcpServers":{"resolve-ai-bridge":{"command":"existing"}}}')
            before = outside.read_bytes()
            windows = Mock(wraps=os)
            windows.name = 'nt'
            for flag in ('O_WRONLY', 'O_CREAT', 'O_EXCL'):
                setattr(windows, flag, getattr(os, flag))
            with patch.dict(os.environ, APPDATA=ambient), patch.object(installer, 'os', windows), \
                    patch.object(installer, 'sys', SimpleNamespace(platform='win32')):
                self.configure()
            self.assertEqual(outside.read_bytes(), before)
            self.assertEqual(list(outside.parent.iterdir()), [outside])
            self.assertEqual(json.loads(inside.read_text())['mcpServers']['resolve-ai-bridge']['command'], 'python')
    def test_version_consistency(self):
        self.assertEqual(installer.VERSION,AGENT_VERSION)
        self.assertEqual(json.loads((ROOT/'package.json').read_text())['version'],AGENT_VERSION)
        self.assertIn('version = "%s"'%AGENT_VERSION,(ROOT/'pyproject.toml').read_text())
        self.assertIn('VERSION="%s"'%AGENT_VERSION,(ROOT/'agent/lua/rpc.lua').read_text())
    def test_required_npm_payload(self):
        package=json.loads((ROOT/'package.json').read_text());self.assertIn('requirements.txt',package['files'])
        self.assertNotIn('react',package.get('dependencies',{}));self.assertNotIn('main',package)
    def test_python_sources_compile(self):
        for p in list((ROOT/'bridge').glob('*.py'))+list((ROOT/'agent').rglob('*.py'))+[ROOT/'install.py']:
            compile(p.read_text(),str(p),'exec')
