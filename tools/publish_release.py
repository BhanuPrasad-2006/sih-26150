import os
import sys
import json
import subprocess
import urllib.request
import ctypes
from ctypes import wintypes
from pathlib import Path

class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD),
        ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR),
        ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME),
        ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_char)),
        ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD),
        ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR),
        ('UserName', wintypes.LPWSTR),
    ]

def get_github_token() -> str:
    pcred = ctypes.POINTER(CREDENTIAL)()
    advapi32 = ctypes.windll.advapi32
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CREDENTIAL))
    ]
    ok = advapi32.CredReadW('git:https://github.com', 1, 0, ctypes.byref(pcred))
    if not ok:
        raise RuntimeError("Failed to read git:https://github.com from Credential Manager")
    blob = ctypes.string_at(pcred.contents.CredentialBlob, pcred.contents.CredentialBlobSize)
    token = blob.decode('utf-16' if b'\x00' in blob else 'utf-8')
    return token.strip()

def main():
    token = get_github_token()
    repo = "BhanuPrasad-2006/sih-26150"
    version = Path("VERSION").read_text(encoding="utf-8").strip() if Path("VERSION").is_file() else "1.0.1"
    tag = f"v{version}"
    headers = {
        "Authorization": f"token {token}",
        "User-Agent": f"SIH-Forensic-Tool-Release/{version}"
    }

    print(f"Fetching release {tag} for {repo}...")
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", headers=headers)
        with urllib.request.urlopen(req) as resp:
            release = json.loads(resp.read())
    except urllib.error.HTTPError as err:
        if err.code == 404:
            print(f"Release {tag} does not exist yet. Creating release {tag}...")
            create_payload = json.dumps({
                "tag_name": tag,
                "name": f"SIH26150 Forensic Tool {tag}",
                "body": f"Release {tag}: Local-first, air-gapped forensic desktop tool with local user authentication isolation.",
                "draft": False,
                "prerelease": False
            }).encode("utf-8")
            create_req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/releases",
                data=create_payload,
                headers={**headers, "Content-Type": "application/json"}
            )
            with urllib.request.urlopen(create_req) as resp:
                release = json.loads(resp.read())
        else:
            raise

    release_id = release["id"]
    print(f"Found release ID: {release_id}")

    # Installer path
    installer_path = Path(rf"c:\Users\Bhanu Prasad\OneDrive\Desktop\sih-2\SIH-Forensic-Tool-Setup-{version}.exe")
    if not installer_path.is_file():
        installer_path = Path(rf"packaging\Output\SIH-Forensic-Tool-Setup-{version}.exe")
    if not installer_path.is_file():
        print(f"Installer not found at {installer_path}!")
        sys.exit(1)

    size_mb = installer_path.stat().st_size / (1024 * 1024)
    print(f"Uploading installer: {installer_path} ({size_mb:.1f} MB)...")

    # Check and delete existing asset if needed
    for a in release.get("assets", []):
        if a["name"] in (f"SIH-Forensic-Tool-Setup-{version}.exe", "SIH-Forensic-Tool-Setup.exe", "SIH-Forensic-Tool-Setup-1.0.0.exe"):
            print(f"Deleting older asset {a['name']} (id {a['id']})...")
            del_req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/assets/{a['id']}", headers=headers, method="DELETE")
            try:
                urllib.request.urlopen(del_req)
            except Exception as e:
                print(f"Warning on delete: {e}")

    targets = [
        f"SIH-Forensic-Tool-Setup-{version}.exe",
        "SIH-Forensic-Tool-Setup.exe"
    ]

    for target_name in targets:
        upload_url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={target_name}"
        print(f"\n--> Uploading {target_name} via curl...")
        cmd = [
            "curl.exe",
            "-X", "POST",
            "-H", f"Authorization: token {token}",
            "-H", "Content-Type: application/octet-stream",
            "--data-binary", f"@{str(installer_path)}",
            upload_url,
            "--fail",
            "-sS"
        ]
        ret = subprocess.run(cmd, capture_output=True, text=True)
        if ret.returncode == 0:
            print(f"SUCCESS: Uploaded {target_name}!")
        else:
            print(f"FAILED to upload {target_name}: {ret.stderr}\n{ret.stdout}")

    print("\n=== UPLOAD FINISHED ===")
    for target_name in targets:
        print(f"Download URL: https://github.com/{repo}/releases/download/{tag}/{target_name}")

if __name__ == "__main__":
    main()
