"""
test_reset_user_password.py — the forgotten-password CLI primitives and the CLI script itself.

The interactive script is exercised by calling its main() directly with mocked input()/
getpass.getpass(), not by spawning a real subprocess with piped stdin. That is a deliberate
choice, not a shortcut: on Windows, getpass.getpass() reads straight from the console via
msvcrt.getwch() whenever sys.stdin is still sys.__stdin__ (true even when stdin has been
redirected to a pipe) — so a subprocess fed input via a pipe hangs forever waiting on a console
that was never attached, even though the exact same script works correctly for a real person
typing at a real terminal. Mocking in-process sidesteps that platform quirk entirely while still
exercising the script's actual logic end to end.

One test (test_cli_with_no_accounts_exits_cleanly) does still spawn a real subprocess, because
that path never calls getpass at all (it prints and exits before any prompt) and is worth proving
works from an actual command line, not just importlib.
"""

import json
import os
import subprocess
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

from backend.auth import AuthManager, validate_password_strength


# ── AuthManager primitives ────────────────────────────────────────────────────

def test_set_user_password_changes_the_hash_and_clears_lockout():
    import backend.main as m
    a = AuthManager(m.db)
    username = "reset_primitive_user"
    if not a.get_username_display(username):
        a.create_user(username, "OriginalPass1!")
    a.record_failure(username)
    a.record_failure(username)

    ok = a.set_user_password(username, "BrandNewPass2!")
    assert ok is True
    assert a.verify_credentials(username, "BrandNewPass2!") is True
    assert a.verify_credentials(username, "OriginalPass1!") is False
    assert a.is_locked_out(username) == (False, 0)   # a reset also clears any lockout


def test_set_user_password_unknown_username_returns_false():
    import backend.main as m
    a = AuthManager(m.db)
    assert a.set_user_password("no_such_examiner_at_all", "SomeStrongPass1!") is False


def test_set_user_password_enforces_the_strong_password_rule():
    import backend.main as m
    a = AuthManager(m.db)
    username = "reset_weak_user"
    if not a.get_username_display(username):
        a.create_user(username, "OriginalPass1!")
    with pytest.raises(ValueError):
        a.set_user_password(username, "tooshort1A!")


def test_disable_totp_for_clears_a_lost_authenticator():
    import backend.main as m
    from backend import totp
    a = AuthManager(m.db)
    username = "reset_totp_user"
    if not a.get_username_display(username):
        a.create_user(username, "OriginalPass1!")
    if a.totp_enabled(username):
        a.disable_totp(username)
    secret = a.begin_totp_enrollment(username)
    a.confirm_totp(username, totp.code_at(secret, totp.counter_now()))
    assert a.totp_enabled(username) is True

    ok = a.disable_totp_for(username)
    assert ok is True
    assert a.totp_enabled(username) is False


def test_disable_totp_for_unknown_username_returns_false():
    import backend.main as m
    a = AuthManager(m.db)
    assert a.disable_totp_for("no_such_examiner_at_all") is False


# ── The CLI script's main(), called in-process with mocked input/getpass ─────

@pytest.fixture()
def cli_module(auth_client):
    """Import tools/reset_user_password.py as a module, against the same isolated database
    auth_client already set up (so it has one known account: conftest's _AUTH_TEST_USERNAME)."""
    import importlib.util
    repo_root = Path(__file__).resolve().parent.parent.parent
    spec = importlib.util.spec_from_file_location("reset_user_password_under_test", repo_root / "tools" / "reset_user_password.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_main(cli_module, argv, inputs, capsys):
    """Runs cli_module.main() with sys.argv patched and a scripted sequence of answers for every
    input()/getpass.getpass() call it makes, in order."""
    it = iter(inputs)
    with mock.patch.object(sys, "argv", ["reset_user_password.py", *argv]), \
         mock.patch("builtins.input", side_effect=it), \
         mock.patch("getpass.getpass", side_effect=it):
        try:
            cli_module.main()
        except SystemExit as exc:
            return exc.code, capsys.readouterr().out
    return 0, capsys.readouterr().out


def test_cli_lists_accounts_and_resets_the_chosen_one(cli_module, capsys):
    from backend.tests.conftest import _AUTH_TEST_USERNAME as user
    code, out = _run_main(cli_module, [], ["1", "BrandNewPass2!", "BrandNewPass2!", "n"], capsys)
    assert code in (0, None), out
    assert user in out
    assert "Done." in out

    import backend.main as m
    auth = AuthManager(m.db)
    assert auth.verify_credentials(user, "BrandNewPass2!") is True


def test_cli_accepts_username_flag_and_skips_the_picker(cli_module, capsys):
    from backend.tests.conftest import _AUTH_TEST_USERNAME as user
    code, out = _run_main(cli_module, ["--username", user], ["AnotherNewPass3!", "AnotherNewPass3!", "n"], capsys)
    assert code in (0, None), out
    import backend.main as m
    auth = AuthManager(m.db)
    assert auth.verify_credentials(user, "AnotherNewPass3!") is True


def test_cli_rejects_a_weak_new_password_and_reprompts(cli_module, capsys):
    from backend.tests.conftest import _AUTH_TEST_USERNAME as user
    # First attempt too short, second attempt is strong enough
    code, out = _run_main(cli_module, [], ["1", "short1A!", "GoodEnough4!", "GoodEnough4!", "n"], capsys)
    assert code in (0, None), out
    import backend.main as m
    auth = AuthManager(m.db)
    assert auth.verify_credentials(user, "GoodEnough4!") is True


def test_cli_rejects_mismatched_confirmation_and_reprompts(cli_module, capsys):
    from backend.tests.conftest import _AUTH_TEST_USERNAME as user
    code, out = _run_main(cli_module, [], ["1", "GoodEnough4!", "TyposHere5!", "GoodEnough4!", "GoodEnough4!", "n"], capsys)
    assert code in (0, None), out
    import backend.main as m
    auth = AuthManager(m.db)
    assert auth.verify_credentials(user, "GoodEnough4!") is True


def test_cli_records_an_audit_entry(cli_module, capsys):
    from backend.tests.conftest import _AUTH_TEST_USERNAME as user
    _run_main(cli_module, [], ["1", "BrandNewPass2!", "BrandNewPass2!", "n"], capsys)
    import backend.main as m
    entries = m.db.load_audit_entries(case_id=None)
    assert any(e.action == "password_reset_via_cli" and user in e.details for e in entries)


def test_cli_can_also_disable_two_factor(cli_module, capsys):
    from backend import totp
    from backend.tests.conftest import _AUTH_TEST_USERNAME as user
    import backend.main as m
    auth = AuthManager(m.db)
    secret = auth.begin_totp_enrollment(user)
    auth.confirm_totp(user, totp.code_at(secret, totp.counter_now()))
    assert auth.totp_enabled(user) is True

    code, out = _run_main(cli_module, [], ["1", "BrandNewPass2!", "BrandNewPass2!", "y"], capsys)
    assert code in (0, None), out
    assert auth.totp_enabled(user) is False


def test_cli_unknown_username_flag_exits_cleanly(cli_module, capsys):
    code, out = _run_main(cli_module, ["--username", "no_such_examiner"], [], capsys)
    assert code not in (0, None)
    assert "No account named" in out


# ── The one genuine subprocess test: the no-accounts path never touches getpass ──

def test_cli_with_no_accounts_exits_cleanly(tmp_path, monkeypatch):
    case_dir = tmp_path / "cases"
    monkeypatch.setenv("FORENSIC_CASE_DIR", str(case_dir))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SIH_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("SIH_KEY_DIR", str(tmp_path / "keys"))
    from backend.database import Database
    Database()   # creates the (empty) database file; no accounts created

    env = dict(os.environ)
    env["FORENSIC_CASE_DIR"] = str(case_dir)
    env["DATABASE_URL"] = ""
    env["SIH_CONFIG_DIR"] = str(tmp_path / "config")
    env["SIH_KEY_DIR"] = str(tmp_path / "keys")
    repo_root = Path(__file__).resolve().parent.parent.parent

    result = subprocess.run([sys.executable, "tools/reset_user_password.py"], cwd=repo_root,
                             env=env, input="", capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "No examiner accounts exist" in result.stdout
