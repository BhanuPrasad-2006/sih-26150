"""
reset_user_password.py — recover from a forgotten examiner password, from the terminal.

There is no email or SMS on an offline forensic tool, so "forgot password" here means: whoever
has terminal access to the machine the case data lives on can reset it directly. This is the
same trust model most self-hosted server software uses for this (e.g. a "manage.py
resetpassword"-style command) — if someone has a shell on the machine, they already have access
to the evidence files on disk, so a CLI reset does not weaken the tool's actual security boundary.

Usage (run from the repository root, with the same environment the app itself would use — same
DATABASE_URL / FORENSIC_CASE_DIR, if you set those — so it edits the SAME account database):

    python tools/reset_user_password.py                  # lists accounts, then prompts
    python tools/reset_user_password.py --username alice  # skips the picker

The new password is typed twice (hidden input, via getpass) and checked against the same
strong-password rule as signup. The reset is written to the tool's own tamper-evident audit log
(action "password_reset_via_cli") so it is not a silent, invisible bypass of that guarantee.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# Make "import backend..." resolve regardless of the current working directory this is run
# from: this file lives in tools/, so its own directory is what ends up on sys.path[0] by
# default, not the repository root that actually contains the backend/ package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.auth import validate_password_strength  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", help="Skip the picker and reset this account directly.")
    args = parser.parse_args()

    # Imported here, not at module top: this is what actually opens the real database (Postgres
    # or SQLite, whichever the environment/local_config say), exactly as the running app would.
    from backend.main import auth, _global_audit_event

    usernames = auth.list_usernames()
    if not usernames:
        print("No examiner accounts exist yet — there is nothing to reset. Run the app and use "
              "first-run setup to create the first account.")
        sys.exit(1)

    username = args.username
    if username:
        if username not in usernames and auth.get_username_display(username) is None:
            print(f"No account named {username!r}. Existing accounts: {', '.join(usernames)}")
            sys.exit(1)
    else:
        print("Examiner accounts on this installation:")
        for i, u in enumerate(usernames, 1):
            print(f"  {i}. {u}")
        choice = input("Reset which account? (number or username): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(usernames):
            username = usernames[int(choice) - 1]
        elif choice in usernames or auth.get_username_display(choice) is not None:
            username = choice
        else:
            print("Not a valid choice.")
            sys.exit(1)

    display_name = auth.get_username_display(username) or username
    print(f"\nResetting the password for: {display_name}")

    while True:
        pw1 = getpass.getpass("New password (hidden as you type): ")
        try:
            validate_password_strength(pw1)
        except ValueError as exc:
            print(f"  {exc}")
            continue
        pw2 = getpass.getpass("Re-enter the new password: ")
        if pw1 != pw2:
            print("  Those did not match — try again.")
            continue
        break

    ok = auth.set_user_password(username, pw1)
    if not ok:
        print("Could not reset that account (it may have just been deleted). Nothing was changed.")
        sys.exit(1)

    disable_2fa = input("Also disable two-factor authentication for this account, in case the "
                         "authenticator device is unavailable too? [y/N]: ").strip().lower()
    disabled_2fa = False
    if disable_2fa == "y":
        disabled_2fa = auth.disable_totp_for(username)

    _global_audit_event("password_reset_via_cli", f"username={display_name} totp_also_disabled={disabled_2fa}")

    print(f"\nDone. {display_name}'s password has been reset" +
          (" and two-factor authentication has been disabled for this account." if disabled_2fa else "."))
    print("This was recorded in the tool's audit log, same as any other account change.")


if __name__ == "__main__":
    main()
