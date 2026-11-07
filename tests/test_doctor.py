"""Offline diagnostics for a temporary runtime and menu installation."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import install
from tools import doctor
from installer_fakes import isolated_user_profile


class DoctorTests(unittest.TestCase):
    def test_reports_the_lua_launcher_and_dependencies_even_with_a_bad_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory).resolve()
            home = profile / "runtime"
            with isolated_user_profile(profile), patch.object(install, "HOME", home):
                install.copy_runtime()
                python = install.venv_python()
                python.parent.mkdir(parents=True)
                python.touch()
                install.write_configs()
                launcher = doctor.menu_script_folders()[0]
                launcher.mkdir(parents=True)
                (launcher / "Start AI Bridge.py").touch()
                (home / "token.txt").write_text("rab_" + "test" * 12, encoding="utf-8")
                (home / "agent.json").write_text('{"time":"invalid"}', encoding="utf-8")
                (home / "lua" / "sha256.lua").unlink()
                env = dict(os.environ, HOME=str(profile), RESOLVE_AI_BRIDGE_HOME=str(home))
                command = [sys.executable, str(doctor.ROOT / "tools" / "doctor.py"), "--offline"]
                broken = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(broken.returncode, 1, broken.stderr)
                self.assertIn("Installed Lua worker: missing lua/sha256.lua", broken.stdout)
                self.assertIn("Workspace > Scripts Lua launcher: not installed", broken.stdout)
                self.assertIn("heartbeat invalid/stale", broken.stdout)
                (home / "lua" / "sha256.lua").write_bytes((install.ROOT / "agent/lua/sha256.lua").read_bytes())
                (launcher / "Start AI Bridge (Lua).lua").touch()
                healthy = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(healthy.returncode, 0, healthy.stdout + healthy.stderr)
                self.assertIn("[OK]   Workspace > Scripts Lua launcher", healthy.stdout)
                self.assertIn("A live connection was not tested", healthy.stdout)
