"""scripts/export_summary.py: layout and counts only, never an email or ID."""

import importlib.util
import io
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_summary.py"
_spec = importlib.util.spec_from_file_location("export_summary", SCRIPT)
export_summary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export_summary)

EMAIL = "first_last@example.com"
UUID = "145b3ece-a75a-42bd-a402-f3f640a80ec2"


def make_export(path: Path) -> Path:
    fits = io.BytesIO()
    with zipfile.ZipFile(fits, "w") as z:
        for upload_id in (123456789, 123456790, 123456791):
            z.writestr(f"{EMAIL}_{upload_id}.fit", b"\x0e")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_0-_Part1.zip", fits.getvalue()
        )
        z.writestr("DI_CONNECT/DI-Connect-Aggregator/UDSFile_2021-05-10_2021-08-18.json", "[]")
        z.writestr("DI_CONNECT/DI-Connect-Aggregator/UDSFile_2026-07-23_2026-10-31.json", "[]")
        z.writestr(
            "DI_CONNECT/DI-Connect-Wellness/2021-05-10_2021-08-18_98765432_sleepData.json", "[]"
        )
        z.writestr(f"DI_CONNECT/DI-Connect-Fitness/{EMAIL}_0_summarizedActivities.json", "[]")
        z.writestr("customer_data/customer.json", "{}")
    return path


def test_folders_extensions_patterns_and_date_ranges(tmp_path):
    out = export_summary.summary(make_export(tmp_path / f"{UUID}_1.zip"))

    assert out.splitlines()[0].startswith("<uuid>_1.zip (")
    assert "DI_CONNECT/DI-Connect-Aggregator: .json 2" in out
    assert "  names: UDSFile_<date>_<date>.json x2" in out
    assert "  dates in names: 2021-05-10 .. 2026-10-31" in out
    assert "  names: <date>_<date>_<n>_sleepData.json x1" in out
    assert "customer_data: .json 1" in out
    assert "total: .json 5, .zip 1" in out


def test_nested_fit_zips_are_listed_without_extracting(tmp_path):
    out = export_summary.summary(make_export(tmp_path / "export.zip"))

    assert "nested DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_0-_Part1.zip:" in out
    assert "  .: .fit 3" in out
    assert "    names: <email>_<n>.fit x3" in out
    assert not list(tmp_path.glob("*.fit"))


def test_no_email_id_or_uuid_reaches_the_output(tmp_path):
    out = export_summary.summary(make_export(tmp_path / f"{UUID}_1.zip"))

    for private in (EMAIL, "first_last", "example.com", "123456789", "98765432", UUID):
        assert private not in out


def test_without_arguments_it_reads_the_zips_under_raw_export(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "raw" / "export" / "2026-10-30"
    folder.mkdir(parents=True)
    make_export(folder / "export.zip")
    monkeypatch.setenv("RUNNING_DATA_DIR", str(tmp_path))

    assert export_summary.main([]) == 0
    assert "total: .json 5, .zip 1" in capsys.readouterr().out


def test_no_export_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNING_DATA_DIR", str(tmp_path))

    assert export_summary.main([]) == 1
