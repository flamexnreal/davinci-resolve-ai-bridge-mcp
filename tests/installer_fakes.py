"""Keep installer tests away from actual client profiles and user files."""

import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


@contextmanager
def isolated_user_profile(home):
    with patch.object(Path, "home", return_value=home), patch.dict(os.environ, {
        "APPDATA": str(home / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "USERPROFILE": str(home),
    }):
        yield
