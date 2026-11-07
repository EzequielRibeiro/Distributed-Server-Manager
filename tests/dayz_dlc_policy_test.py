from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents/linux/runtime"))
from dayz_dlc_policy import inaccessible_dlc_paths

def test_known_dlc_masked_for_other_maps():
    root="/srv/dayz/serverfiles"
    assert inaccessible_dlc_paths(root,"hardcore.namalsk")==[root+"/nasdara"]
    assert inaccessible_dlc_paths(root,"dayzOffline.nasdara")==[]

def test_future_unknown_folders_not_automatically_masked():
    assert inaccessible_dlc_paths("/srv/dayz/serverfiles","dayzOffline.chernarusplus")==["/srv/dayz/serverfiles/nasdara"]

def test_future_reviewed_dlc_scoped_to_its_mission(monkeypatch):
    import dayz_dlc_policy as policy
    monkeypatch.setattr(policy, "DLC_MISSIONS", {
        "nasdara": frozenset({"nasdara"}),
        "future_dlc": frozenset({"futuremap"}),
    })
    root = "/srv/dayz/serverfiles"
    assert policy.inaccessible_dlc_paths(root, "hardcore.namalsk") == [
        root + "/future_dlc", root + "/nasdara"
    ]
    assert policy.inaccessible_dlc_paths(root, "dayzOffline.futuremap") == [
        root + "/nasdara"
    ]
    assert policy.inaccessible_dlc_paths(root, "dayzOffline.nasdara") == [
        root + "/future_dlc"
    ]


def test_unknown_dlc_never_added_by_filesystem_contents(tmp_path):
    from dayz_dlc_policy import inaccessible_dlc_paths
    (tmp_path / "unknown_future_expansion").mkdir()
    (tmp_path / "nasdara").mkdir()
    result = inaccessible_dlc_paths(str(tmp_path), "hardcore.namalsk")
    assert result == [str(tmp_path / "nasdara")]
    assert str(tmp_path / "unknown_future_expansion") not in result


def test_invalid_install_roots_fail_closed():
    import pytest
    from dayz_dlc_policy import inaccessible_dlc_paths
    for root in ("relative/dayz", "/srv/dayz/../other"):
        with pytest.raises(ValueError):
            inaccessible_dlc_paths(root, "hardcore.namalsk")
