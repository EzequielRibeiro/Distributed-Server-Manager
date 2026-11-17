from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents/linux/runtime"))
from dayz_dlc_policy import inaccessible_dlc_paths

@pytest.mark.parametrize("mission", ["hardcore.namalsk", "dayzOffline.chernarusplus", "dayzOffline.nasdara", "dayzOffline.futuremap"])
def test_installed_dayz_dlc_data_remains_visible_for_all_missions(mission):
    assert inaccessible_dlc_paths("/srv/dayz/serverfiles", mission) == []

def test_unknown_expansion_remains_visible(tmp_path):
    (tmp_path / "nasdara").mkdir()
    (tmp_path / "future_dlc").mkdir()
    assert inaccessible_dlc_paths(str(tmp_path), "hardcore.namalsk") == []

def test_invalid_install_roots_rejected():
    for root in ("relative/dayz", "/srv/dayz/../other"):
        with pytest.raises(ValueError):
            inaccessible_dlc_paths(root, "hardcore.namalsk")
