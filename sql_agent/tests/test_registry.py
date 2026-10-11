"""Datasource registry: id resolution, collisions, defaults."""
import pytest

from app.db.registry import DatasourceRegistry


@pytest.fixture()
def tree(tmp_path):
    (tmp_path / "kaggle").mkdir()
    (tmp_path / "spider" / "nested").mkdir(parents=True)
    for rel in ["kaggle/Alpha.sqlite", "kaggle/Beta.sqlite", "spider/nested/Gamma.sqlite"]:
        (tmp_path / rel).write_bytes(b"")
    return tmp_path


def test_scans_recursively(tree):
    reg = DatasourceRegistry(roots=[str(tree)])
    assert [s.id for s in reg.list()] == ["Alpha", "Beta", "Gamma"]


def test_id_is_the_file_stem_so_profiles_match(tree):
    reg = DatasourceRegistry(roots=[str(tree)])
    assert reg.get("Gamma").path.endswith("nested/Gamma.sqlite")


def test_explicit_path_becomes_the_default(tree):
    reg = DatasourceRegistry(
        roots=[str(tree)], explicit_path=str(tree / "kaggle/Beta.sqlite"), explicit_id="Beta"
    )
    assert reg.default_id == "Beta"


def test_default_falls_back_to_first_when_none_configured(tree):
    assert DatasourceRegistry(roots=[str(tree)]).default_id == "Alpha"


def test_omitted_id_resolves_to_default(tree):
    reg = DatasourceRegistry(roots=[str(tree)])
    assert reg.get(None).id == "Alpha"
    assert reg.get("").id == "Alpha"


def test_unknown_id_raises(tree):
    with pytest.raises(KeyError, match="Nope"):
        DatasourceRegistry(roots=[str(tree)]).get("Nope")


def test_duplicate_ids_resolve_deterministically(tmp_path):
    for rel in ["a/Dup.sqlite", "b/Dup.sqlite"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"")
    reg = DatasourceRegistry(roots=[str(tmp_path / "a"), str(tmp_path / "b")])
    assert len(reg) == 1
    assert reg.get("Dup").path.endswith("a/Dup.sqlite")


def test_missing_root_is_skipped_not_fatal(tree):
    reg = DatasourceRegistry(roots=[str(tree), "/no/such/place"])
    assert len(reg) == 3


def test_empty_registry_reports_clearly():
    with pytest.raises(KeyError, match="нет ни одного"):
        DatasourceRegistry(roots=[]).get(None)


def test_tilde_in_explicit_path_is_expanded(tmp_path, monkeypatch):
    """Paths in .env are written with ~; the registry must resolve it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "Home.sqlite").write_bytes(b"")

    reg = DatasourceRegistry(roots=[], explicit_path="~/db/Home.sqlite")
    assert reg.get("Home").path == str(tmp_path / "db" / "Home.sqlite")


def test_tilde_in_roots_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "roots").mkdir()
    (tmp_path / "roots" / "Scanned.sqlite").write_bytes(b"")

    assert [s.id for s in DatasourceRegistry(roots=["~/roots"]).list()] == ["Scanned"]
