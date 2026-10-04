"""Exercise bootstrap downloads/extraction without running the real installer."""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_URL = "https://github.com/flamexnreal/davinci-resolve-ai-bridge-mcp/archive/refs/heads/main"
POWERSHELL = (
    os.environ.get("RESOLVE_BRIDGE_TEST_POWERSHELL")
    or shutil.which("pwsh")
    or shutil.which("powershell")
)
BASH = shutil.which("bash") if os.name != "nt" else None
INSTALL_ARGS = ["--with-ffmpeg", "--no-menu"]

FAKE_INSTALLER = """
import json, os, sys
from pathlib import Path
Path(os.environ["BRIDGE_BOOTSTRAP_RECORD"]).write_text(json.dumps({
    "args": sys.argv[1:], "folder": Path.cwd().name,
}), encoding="utf-8")
code = int(os.environ.get("BRIDGE_BOOTSTRAP_EXIT", "0"))
print("INSTALL COMPLETE" if not code else "Simulated installer failure")
sys.exit(code)
"""

POWERSHELL_HARNESS = r"""
$ErrorActionPreference = "Stop"
$global:bootstrapUrl = $null
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch]$UseBasicParsing)
    $global:bootstrapUrl = $Uri
    if ($env:BRIDGE_BOOTSTRAP_DOWNLOAD_FAIL -eq "1") {
        throw "Simulated download failure"
    }
    Copy-Item -LiteralPath $env:BRIDGE_BOOTSTRAP_ARCHIVE -Destination $OutFile
}
function Get-Command {
    param($Name, $ErrorAction)
    if ($Name -eq $env:BRIDGE_BOOTSTRAP_COMMAND) {
        return [pscustomobject]@{ Name = $Name }
    }
    return $null
}
function py {
    & $env:BRIDGE_BOOTSTRAP_PYTHON @args
    $global:LASTEXITCODE = $LASTEXITCODE
}
function python3 {
    & $env:BRIDGE_BOOTSTRAP_PYTHON @args
    $global:LASTEXITCODE = $LASTEXITCODE
}
function python {
    & $env:BRIDGE_BOOTSTRAP_PYTHON @args
    $global:LASTEXITCODE = $LASTEXITCODE
}
$caught = $false
$failureMessage = $null
try {
    if ($env:BRIDGE_BOOTSTRAP_PIPELINE -eq "1") {
        Get-Content -LiteralPath $env:BRIDGE_BOOTSTRAP_SCRIPT -Raw | Invoke-Expression
    } else {
        & $env:BRIDGE_BOOTSTRAP_SCRIPT --with-ffmpeg --no-menu
    }
} catch {
    $caught = $true
    $failureMessage = $_.Exception.Message
} finally {
    [ordered]@{
        url = $global:bootstrapUrl
        location = (Get-Location).Path
        error = $failureMessage
    } | ConvertTo-Json -Compress |
        Set-Content -LiteralPath $env:BRIDGE_BOOTSTRAP_STATE -Encoding utf8
}
if ($caught) { exit 1 }
"""


class BootstrapFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bridge bootstrap ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.downloads = self.root / "downloads [test]"
        self.downloads.mkdir()
        self.cwd = self.root / "working directory [test]"
        self.cwd.mkdir()
        self.record = self.root / "installer.json"
        self.env = dict(os.environ, **{
            "TMPDIR": str(self.downloads),
            "TMP": str(self.downloads),
            "TEMP": str(self.downloads),
            "BRIDGE_BOOTSTRAP_RECORD": str(self.record),
            "BRIDGE_BOOTSTRAP_PYTHON": sys.executable,
            "BRIDGE_BOOTSTRAP_STATE": str(self.root / "state.json"),
        })

    def archive(self, suffix, folders):
        path = self.root / ("fixture." + suffix)
        if suffix == "zip":
            with zipfile.ZipFile(path, "w") as archive:
                for folder in folders:
                    archive.writestr(folder + "/install.py", FAKE_INSTALLER)
        else:
            with tarfile.open(path, "w:gz") as archive:
                for folder in folders:
                    data = FAKE_INSTALLER.encode()
                    entry = tarfile.TarInfo(folder + "/install.py")
                    entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
        self.env["BRIDGE_BOOTSTRAP_ARCHIVE"] = str(path)

    def installed(self):
        return json.loads(self.record.read_text(encoding="utf-8"))

    def assert_cleaned(self):
        self.assertEqual(list(self.downloads.iterdir()), [])


@unittest.skipUnless(POWERSHELL, "PowerShell is not installed")
class PowerShellBootstrapTests(BootstrapFixture):
    def run_bootstrap(self, folders=("davinci-resolve-ai-bridge-mcp-main",),
                      command="py", exit_code=0, pipeline=False, download_fail=False):
        self.archive("zip", folders)
        self.env.update({
            "BRIDGE_BOOTSTRAP_COMMAND": command,
            "BRIDGE_BOOTSTRAP_EXIT": str(exit_code),
            "BRIDGE_BOOTSTRAP_DOWNLOAD_FAIL": str(int(download_fail)),
            "BRIDGE_BOOTSTRAP_PIPELINE": str(int(pipeline)),
            "BRIDGE_BOOTSTRAP_SCRIPT": str(ROOT / "install.ps1"),
        })
        harness = self.root / "harness.ps1"
        harness.write_text(POWERSHELL_HARNESS, encoding="utf-8")
        result = subprocess.run(
            [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(harness)],
            cwd=self.cwd, env=self.env, capture_output=True, text=True, timeout=30,
        )
        state = json.loads((self.root / "state.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(Path(state["location"]).resolve(), self.cwd.resolve())
        self.assertEqual(state["url"], ARCHIVE_URL + ".zip")
        self.assert_cleaned()
        return result, state

    def test_archive_discovery_and_python_fallbacks(self):
        for command, folder in (
            ("py", "davinci-resolve-ai-bridge-mcp-main"),
            ("python3", "renamed project-main"),
            ("python", "renamed project [test]-main"),
        ):
            with self.subTest(command=command, folder=folder):
                result, state = self.run_bootstrap(folders=(folder,), command=command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIsNone(state["error"])
                self.assertEqual(self.installed(), {"args": INSTALL_ARGS, "folder": folder})
                self.assertIn("INSTALL COMPLETE", result.stdout)

    def test_documented_invoke_expression_route(self):
        result, state = self.run_bootstrap(pipeline=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNone(state["error"])
        self.assertEqual(self.installed()["args"], [])

    def test_installer_failure_is_reported(self):
        result, state = self.run_bootstrap(exit_code=7)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exit code 7", state["error"])
        self.assertNotIn("INSTALL COMPLETE", result.stdout)

    def test_invalid_archives_do_not_run_installer(self):
        for folders in ((), ("first", "second")):
            with self.subTest(folders=folders):
                result, state = self.run_bootstrap(folders=folders)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exactly one project folder", state["error"])
                self.assertFalse(self.record.exists())

    def test_missing_python_is_reported(self):
        result, state = self.run_bootstrap(command="missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python 3.10 or newer is required", state["error"])
        self.assertFalse(self.record.exists())

    def test_download_failure_cleans_up(self):
        result, state = self.run_bootstrap(download_fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Simulated download failure", state["error"])
        self.assertFalse(self.record.exists())


@unittest.skipUnless(BASH, "POSIX Bash is not available")
class ShellBootstrapTests(BootstrapFixture):
    def run_bootstrap(self, folders=("davinci-resolve-ai-bridge-mcp-main",),
                      command="python3", downloader="curl", exit_code=0,
                      download_fail=False):
        self.archive("tar.gz", folders)
        bin_dir = self.root / "bin"
        bin_dir.mkdir(exist_ok=True)
        for entry in bin_dir.iterdir():
            entry.unlink()
        for command_name in ("mktemp", "tar", "dirname", "rm"):
            (bin_dir / command_name).symlink_to(shutil.which(command_name))
        if command:
            (bin_dir / command).symlink_to(sys.executable)
        if downloader:
            executable = bin_dir / downloader
            executable.write_text(
                "#!" + sys.executable + "\n"
                "import os, sys\nfrom pathlib import Path\n"
                "Path(os.environ['BRIDGE_BOOTSTRAP_STATE']).write_text(sys.argv[-1])\n"
                "sys.stdout.buffer.write(Path(os.environ['BRIDGE_BOOTSTRAP_ARCHIVE']).read_bytes())\n"
                "sys.exit(22 if os.environ['BRIDGE_BOOTSTRAP_DOWNLOAD_FAIL'] == '1' else 0)\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
        self.env.update({
            "PATH": str(bin_dir),
            "BRIDGE_BOOTSTRAP_EXIT": str(exit_code),
            "BRIDGE_BOOTSTRAP_DOWNLOAD_FAIL": str(int(download_fail)),
        })
        result = subprocess.run(
            [BASH, str(ROOT / "install.sh"), *INSTALL_ARGS],
            cwd=self.cwd, env=self.env, capture_output=True, text=True, timeout=30,
        )
        if downloader:
            self.assertEqual((self.root / "state.json").read_text(), ARCHIVE_URL + ".tar.gz")
        self.assert_cleaned()
        return result

    def test_archive_discovery_and_command_fallbacks(self):
        for downloader, command, folder in (
            ("curl", "python3", "davinci-resolve-ai-bridge-mcp-main"),
            ("wget", "python", "renamed project [test]-main"),
        ):
            with self.subTest(downloader=downloader, command=command):
                result = self.run_bootstrap(folders=(folder,), command=command,
                                            downloader=downloader)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.installed(), {"args": INSTALL_ARGS, "folder": folder})
                self.assertIn("INSTALL COMPLETE", result.stdout)

    def test_installer_failure_keeps_nonzero_exit(self):
        result = self.run_bootstrap(exit_code=7)
        self.assertEqual(result.returncode, 7)
        self.assertNotIn("INSTALL COMPLETE", result.stdout)

    def test_invalid_archives_do_not_run_installer(self):
        for folders in ((), ("first", "second")):
            with self.subTest(folders=folders):
                result = self.run_bootstrap(folders=folders)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exactly one project folder", result.stderr)
                self.assertFalse(self.record.exists())

    def test_missing_python_is_reported(self):
        result = self.run_bootstrap(command=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python 3.10 or newer is required", result.stderr)
        self.assertFalse(self.record.exists())

    def test_download_failure_does_not_run_installer(self):
        result = self.run_bootstrap(download_fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.record.exists())

    def test_missing_downloader_is_reported(self):
        result = self.run_bootstrap(downloader=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("curl or wget is required", result.stderr)
        self.assertFalse(self.record.exists())
