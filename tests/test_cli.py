import json
import shutil
import subprocess
from pathlib import Path

import pytest

import ridge_counter as rc

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_loop.png"


def test_manual_points_json_report(capsys):
    assert rc.main(["count", str(SAMPLE), "--core", "165,150", "--delta", "95,265", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["core"] == [165, 150] and report["delta"] == [95, 265]
    assert report["core_source"] == report["delta_source"] == "manual"
    expected = rc.count_between(rc.analyze(rc.read_image(SAMPLE)), (165, 150), (95, 265)).count
    assert report["ridge_count"] == expected == len(report["counted_ridges_at"])


def test_auto_detected_points(capsys):
    assert rc.main(["count", str(SAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "Ridge count:" in out and "(auto)" in out


def test_output_dir_writes_files_and_appends_to_the_log(tmp_path, capsys):
    for _ in range(2):
        assert rc.main(["count", str(SAMPLE), "--output-dir", str(tmp_path)]) == 0
    assert (tmp_path / "sample_loop_ridgecount.png").stat().st_size > 0
    report = json.loads((tmp_path / "sample_loop_ridgecount.json").read_text(encoding="utf-8"))
    rows = (tmp_path / "ridge_counts.csv").read_text(encoding="utf-8").strip().splitlines()
    assert rows[0].startswith("analyzed_at,image,ridge_count")
    assert len(rows) == 3
    assert rows[-1].split(",")[2] == str(report["ridge_count"])


def test_paths_with_spaces_and_accents(tmp_path, capsys):
    target = tmp_path / "bébé scan é.png"
    shutil.copy(SAMPLE, target)
    assert rc.main(["count", str(target), "--json"]) == 0


def test_missing_file_is_a_clean_error(capsys):
    assert rc.main(["count", "does-not-exist.png"]) == 1
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--core", "12"], ["--delta", "a,b"], ["--ridge-period", "2"]])
def test_bad_arguments(args):
    with pytest.raises(SystemExit) as exc:
        rc.main(["count", str(SAMPLE), *args])
    assert exc.value.code == 2


def test_usage(capsys):
    assert rc.main(["--help"]) == 0
    assert rc.main(["one.png", "two.png"]) == 2


def test_installer_falls_back_to_ensurepip_and_reports_failure(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        stderr = "No module named pip" if len(calls) == 1 else "network down"
        return subprocess.CompletedProcess(cmd, 1, "", stderr)

    monkeypatch.setattr(rc.subprocess, "run", fake_run)
    ok, output = rc.install_dependencies()
    assert not ok and "network down" in output
    assert calls[1][1:3] == ["-m", "ensurepip"]
