"""game_tester.fixtures: a provisioned file is gone when the run ends."""
import pytest

from game_tester import tier1_tests
from game_tester.fixtures import FixtureFile, provisioned_file, release_all


def test_created_fixture_is_removed(tmp_path):
    with provisioned_file(tmp_path, "qa.txt", b"data") as fixture:
        assert (tmp_path / "qa.txt").read_bytes() == b"data"
        assert fixture.installed
    assert not (tmp_path / "qa.txt").exists()
    assert tmp_path.is_dir()


def test_preexisting_identical_file_survives(tmp_path):
    (tmp_path / "qa.txt").write_bytes(b"data")
    with provisioned_file(tmp_path, "qa.txt", b"data") as fixture:
        assert not fixture.installed
    assert (tmp_path / "qa.txt").read_bytes() == b"data"


def test_preexisting_different_file_is_restored(tmp_path):
    (tmp_path / "qa.txt").write_bytes(b"mine")
    with provisioned_file(tmp_path, "qa.txt", b"data"):
        assert (tmp_path / "qa.txt").read_bytes() == b"data"
    assert (tmp_path / "qa.txt").read_bytes() == b"mine"


def test_created_empty_directory_is_removed_but_not_a_preexisting_one(tmp_path):
    target = tmp_path / "a" / "b"
    with provisioned_file(target, "qa.txt", b"x"):
        assert target.is_dir()
    assert not (tmp_path / "a").exists()
    assert tmp_path.is_dir()


def test_created_directory_with_foreign_content_is_kept(tmp_path):
    target = tmp_path / "a"
    with provisioned_file(target, "qa.txt", b"x"):
        (target / "other.txt").write_text("not ours")
    assert (target / "other.txt").read_text() == "not ours"
    assert not (target / "qa.txt").exists()


def test_failure_inside_the_block_still_cleans_up(tmp_path):
    target = tmp_path / "levels"
    with pytest.raises(RuntimeError):
        with provisioned_file(target, "qa.txt", b"x"):
            raise RuntimeError("test failed")
    assert not target.exists()


def test_a_file_changed_by_someone_else_is_not_deleted(tmp_path):
    with provisioned_file(tmp_path, "qa.txt", b"data"):
        (tmp_path / "qa.txt").write_bytes(b"theirs")
    assert (tmp_path / "qa.txt").read_bytes() == b"theirs"


def test_record_round_trip_releases_in_another_process(tmp_path):
    fixture = FixtureFile(tmp_path / "new", "qa.txt", b"data")
    fixture.install()
    assert release_all([fixture.to_dict()]) == 1
    assert not (tmp_path / "new").exists()


def test_symlink_at_the_path_is_refused_not_written_through(tmp_path):
    target = tmp_path / "elsewhere.txt"
    target.write_bytes(b"theirs")
    (tmp_path / "qa.txt").symlink_to(target)
    (tmp_path / "dangling.txt").symlink_to(tmp_path / "missing.txt")
    for name in ("qa.txt", "dangling.txt"):
        fixture = FixtureFile(tmp_path, name, b"data")
        assert fixture.install() is False
        assert fixture.refused and not fixture.installed
        assert fixture.release() is False
        assert (tmp_path / name).is_symlink()
    assert target.read_bytes() == b"theirs"
    assert not (tmp_path / "missing.txt").exists()


def test_killed_run_leaves_the_original_recoverable(tmp_path):
    (tmp_path / "qa.txt").write_bytes(b"mine")
    crashed = FixtureFile(tmp_path, "qa.txt", b"data")
    crashed.install()
    crashed.adopt(2 ** 22 + 12345)      # the run was killed: its owner pid is gone
    assert (tmp_path / "qa.txt").read_bytes() == b"data"
    del crashed                          # dropped without release()
    fresh = FixtureFile(tmp_path, "qa.txt", b"data")
    assert fresh.install()               # restores `mine`, then installs again
    assert fresh.release()
    assert (tmp_path / "qa.txt").read_bytes() == b"mine"


def test_killed_run_leaving_a_created_file_is_cleaned_by_the_next_run(tmp_path):
    crashed = FixtureFile(tmp_path / "new", "qa.txt", b"data")
    crashed.install()
    crashed.adopt(2 ** 22 + 12345)
    fresh = FixtureFile(tmp_path / "new", "qa.txt", b"data")
    assert fresh.install()
    assert fresh.release()
    assert not (tmp_path / "new").exists()


def test_the_backup_exists_before_the_overwrite(tmp_path, monkeypatch):
    (tmp_path / "qa.txt").write_bytes(b"mine")
    seen = []
    real = FixtureFile._save

    def save(self, marker):
        real(self, marker)
        seen.append((tmp_path / "qa.txt").read_bytes())

    monkeypatch.setattr(FixtureFile, "_save", save)
    fixture = FixtureFile(tmp_path, "qa.txt", b"data")
    fixture.install()
    assert seen == [b"mine"]            # saved while the original was still in place
    fixture.release()


def test_two_runs_sharing_a_directory_remove_the_file_with_the_last_owner(tmp_path):
    first = FixtureFile(tmp_path, "qa.txt", b"data")
    second = FixtureFile(tmp_path, "qa.txt", b"data")
    assert first.install()
    assert second.install() is False and second.installed
    assert first.release() is False
    assert (tmp_path / "qa.txt").read_bytes() == b"data"
    assert second.release() is True
    assert not (tmp_path / "qa.txt").exists()


def test_two_owners_restore_the_original_only_at_the_end(tmp_path):
    (tmp_path / "qa.txt").write_bytes(b"mine")
    first = FixtureFile(tmp_path, "qa.txt", b"data")
    second = FixtureFile(tmp_path, "qa.txt", b"data")
    first.install()
    second.install()
    second.release()
    assert (tmp_path / "qa.txt").read_bytes() == b"data"
    first.release()
    assert (tmp_path / "qa.txt").read_bytes() == b"mine"


def test_releasing_twice_is_a_no_op_for_a_co_owned_file(tmp_path):
    first = FixtureFile(tmp_path, "qa.txt", b"data")
    first.install()
    record = first.to_dict()
    second = FixtureFile(tmp_path, "qa.txt", b"data")
    second.install()
    assert release_all([record]) == 0       # first leaves; second still owns it
    assert release_all([record]) == 0       # repeating changes nothing
    assert (tmp_path / "qa.txt").exists()
    assert second.release() is True


# --- the tier1 large-file fixture --------------------------------------------

@pytest.fixture
def worlds(tmp_path, monkeypatch):
    levels = tmp_path / "levels"
    levels.mkdir()
    monkeypatch.setenv("PYGSERVER_LEVELS_DIR", str(levels))
    monkeypatch.setattr(tier1_tests, "_PROVISIONED", [])
    monkeypatch.setattr(tier1_tests.atexit, "register", lambda fn: None)
    return levels


def test_bigfile_is_provisioned_then_removed(worlds):
    assert tier1_tests.ensure_bigfile_served("localhost") is None
    assert (worlds / tier1_tests.BIGFILE_NAME).read_bytes() == tier1_tests.bigfile_bytes()
    assert tier1_tests.cleanup_bigfile() == 1
    assert list(worlds.iterdir()) == []


def test_bigfile_already_served_is_left_alone(worlds):
    path = worlds / tier1_tests.BIGFILE_NAME
    path.write_bytes(tier1_tests.bigfile_bytes())
    assert tier1_tests.ensure_bigfile_served("localhost") is None
    assert tier1_tests.cleanup_bigfile() == 0
    assert path.read_bytes() == tier1_tests.bigfile_bytes()


def test_bigfile_not_provisioned_for_a_remote_host(worlds):
    assert "not local" in tier1_tests.ensure_bigfile_served("example.invalid")
    assert list(worlds.iterdir()) == []


def test_run_tier1_cleans_up_even_when_login_fails(worlds, monkeypatch):
    tier1_tests.ensure_bigfile_served("localhost")

    class Bot:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            raise RuntimeError("login exploded")

        def disconnect(self):
            pass

    monkeypatch.setattr(tier1_tests, "GameBot", Bot)
    with pytest.raises(RuntimeError):
        tier1_tests.run_tier1_tests()
    assert list(worlds.iterdir()) == []


# --- ownership marker: keying, torn writes, damaged state, pid reuse -----------

import json
import os

from game_tester import fixtures


def _markers():
    return sorted((fixtures.state_dir() / "fixture-owners").glob("*.json"))


def test_two_symlinked_routes_to_one_real_dir_share_one_marker(tmp_path):
    real = tmp_path / "world"
    real.mkdir()
    (tmp_path / "a").symlink_to(real)
    (tmp_path / "b").symlink_to(real)
    first = FixtureFile(tmp_path / "a", "qa.txt", b"data")
    second = FixtureFile(tmp_path / "b", "qa.txt", b"data")
    assert first.install()
    assert second.install() is False and second.installed
    assert len(_markers()) == 1
    assert first.release() is False             # b is still using the file
    assert (real / "qa.txt").read_bytes() == b"data"
    assert second.release() is True
    assert not (real / "qa.txt").exists()


def test_a_failed_atomic_write_leaves_the_original_whole(tmp_path, monkeypatch):
    (tmp_path / "qa.txt").write_bytes(b"mine")

    def killed(src, dst):
        raise KeyboardInterrupt

    monkeypatch.setattr(fixtures.os, "replace", killed)
    fixture = FixtureFile(tmp_path, "qa.txt", b"data")
    with pytest.raises(KeyboardInterrupt):
        fixture.install()
    assert (tmp_path / "qa.txt").read_bytes() == b"mine"
    assert [p.name for p in tmp_path.iterdir() if p.name != "qa-state"] == ["qa.txt"]   # no temp
    assert not fixture.installed


def test_the_fixture_is_never_written_in_place(tmp_path, monkeypatch):
    (tmp_path / "qa.txt").write_bytes(b"mine")
    inode = (tmp_path / "qa.txt").stat().st_ino
    fixture = FixtureFile(tmp_path, "qa.txt", b"data")
    fixture.install()
    assert (tmp_path / "qa.txt").stat().st_ino != inode     # replaced, not rewritten
    fixture.release()
    assert (tmp_path / "qa.txt").read_bytes() == b"mine"


def test_release_undoes_from_memory_when_the_state_dir_vanished(tmp_path):
    import shutil
    (tmp_path / "qa.txt").write_bytes(b"mine")
    fixture = FixtureFile(tmp_path, "qa.txt", b"data")
    fixture.install()
    shutil.rmtree(fixture.state)
    assert fixture.release() is True
    assert (tmp_path / "qa.txt").read_bytes() == b"mine"


def test_release_removes_a_created_file_when_the_marker_vanished(tmp_path):
    fixture = FixtureFile(tmp_path / "new", "qa.txt", b"data")
    fixture.install()
    for marker in _markers():
        marker.unlink()
    assert fixture.release() is True
    assert not (tmp_path / "new").exists()


def test_corrupt_marker_does_not_break_release_or_install(tmp_path, caplog):
    (tmp_path / "qa.txt").write_bytes(b"mine")
    fixture = FixtureFile(tmp_path, "qa.txt", b"data")
    fixture.install()
    _markers()[0].write_text("{not json")
    with caplog.at_level("WARNING"):
        assert fixture.release() is True         # undone from memory
    assert (tmp_path / "qa.txt").read_bytes() == b"mine"
    assert sum("unreadable" in r.message for r in caplog.records) == 1


def test_a_marker_that_is_not_an_object_does_not_break_install(tmp_path):
    (tmp_path / "qa.txt").write_bytes(b"mine")
    first = FixtureFile(tmp_path, "qa.txt", b"data")
    first.install()
    _markers()[0].write_text("[1, 2]")
    first.installed = False
    again = FixtureFile(tmp_path, "qa.txt", b"data")
    assert again.install() is False             # content already matches: not ours to undo
    assert again.release() is False


def test_owner_without_token_is_dropped_not_a_keyerror(tmp_path):
    (tmp_path / "qa.txt").write_bytes(b"mine")
    crashed = FixtureFile(tmp_path, "qa.txt", b"data")
    crashed.install()
    marker = _markers()[0]
    record = json.loads(marker.read_text())
    record["owners"] = [{"pid": os.getpid()}, "junk", {"token": 5, "pid": 1}]
    marker.write_text(json.dumps(record))
    fresh = FixtureFile(tmp_path, "qa.txt", b"data")
    assert fresh.install()                       # leftovers restored, then installed
    assert fresh.release()
    assert (tmp_path / "qa.txt").read_bytes() == b"mine"       # backup survived the damage


def test_malformed_marker_keeps_a_readable_backup(tmp_path):
    (tmp_path / "qa.txt").write_bytes(b"mine")
    crashed = FixtureFile(tmp_path, "qa.txt", b"data")
    crashed.install()
    marker = _markers()[0]
    record = json.loads(marker.read_text())
    del record["owners"]
    marker.write_text(json.dumps(record))
    crashed.installed = False
    fresh = FixtureFile(tmp_path, "qa.txt", b"data")
    assert fresh.install()
    assert fresh.release()
    assert (tmp_path / "qa.txt").read_bytes() == b"mine"


def test_a_user_edit_after_a_dead_run_is_still_not_clobbered(tmp_path):
    (tmp_path / "qa.txt").write_bytes(b"mine")
    crashed = FixtureFile(tmp_path, "qa.txt", b"data")
    crashed.install()
    crashed.adopt(2 ** 22 + 12345)
    (tmp_path / "qa.txt").write_bytes(b"edited later")
    fresh = FixtureFile(tmp_path, "qa.txt", b"data")
    fresh.install()
    fresh.release()
    assert (tmp_path / "qa.txt").read_bytes() == b"edited later"


def _fake_stat(start):
    # pid (comm) state ppid ... field 22 = starttime
    fields = ["S"] + ["0"] * 18 + [str(start)] + ["0"] * 10
    return "123 (we ird) " + " ".join(fields)


def test_start_time_is_field_22_of_stat(monkeypatch):
    monkeypatch.setattr(fixtures, "_read_stat", lambda pid: _fake_stat(777))
    assert fixtures._start_time(123) == 777


def test_a_reused_pid_is_not_alive(monkeypatch):
    monkeypatch.setattr(fixtures, "_read_stat", lambda pid: _fake_stat(900))
    assert fixtures._alive(123, 900) is True
    assert fixtures._alive(123, 777) is False       # same pid, different process
    assert fixtures._alive(123) is True             # no recorded start: pid-only


def test_a_dead_owner_with_a_reused_pid_lets_the_next_run_clean_up(tmp_path, monkeypatch):
    monkeypatch.setattr(fixtures, "_read_stat", lambda pid: _fake_stat(100))
    crashed = FixtureFile(tmp_path / "new", "qa.txt", b"data")
    crashed.install()
    crashed.adopt(os.getpid())                      # owner recorded with start 100
    monkeypatch.setattr(fixtures, "_read_stat", lambda pid: _fake_stat(555))
    fresh = FixtureFile(tmp_path / "new", "qa.txt", b"data")
    assert fresh.install()                          # pid is live, start time is not
    assert fresh.release()
    assert not (tmp_path / "new").exists()


def test_alive_falls_back_to_the_pid_where_proc_is_missing(monkeypatch):
    monkeypatch.setattr(fixtures, "_read_stat", lambda pid: None)
    assert fixtures._alive(os.getpid(), 5) is True
    assert fixtures._alive(2 ** 22 + 12345, 5) is False
    assert fixtures._start_time(os.getpid()) is None
