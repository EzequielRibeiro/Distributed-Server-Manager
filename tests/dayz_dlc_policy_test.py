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
