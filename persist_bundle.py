"""Save an immutable task-7 bundle without overwriting its canonical delivery ledger."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from monitor import EXCURSIONS

ALLOWED = {"prices.json", "sent_notifications.json", "data/watchdog/status.json", "data/watchdog/completed.json"}


def validate(directory):
    names = []
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("bundle_symlink")
        if not path.is_file():
            continue
        name = path.relative_to(directory).as_posix()
        if name not in ALLOWED or not isinstance(json.loads(path.read_text()), dict):
            raise ValueError("unexpected_bundle_file")
        names.append(name)
    if "data/watchdog/status.json" not in names:
        raise ValueError("bundle_status_missing")
    if "data/watchdog/completed.json" in names:
        receipt = json.loads((directory / "data/watchdog/completed.json").read_text())
        if receipt.get("ok") is not True or receipt.get("recovery_safe") is not True or set(receipt.get("checked_ids", [])) != {e["id"] for e in EXCURSIONS}:
            raise ValueError("bundle_completion_invalid")
    return names


def git(*args):
    return subprocess.run(["git", *args], check=True)


def main(directory):
    directory = Path(directory).resolve()
    names = validate(directory)
    git("config", "user.name", "GitHub Action")
    git("config", "user.email", "action@github.com")
    for attempt in range(4):
        git("fetch", "origin", "main")
        git("reset", "--hard", "origin/main")
        for name in names:
            target = Path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(directory / name, target)
        git("add", "--", *names)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            return
        git("commit", "-m", "Persist task 7 prices and completion evidence")
        try:
            git("push", "origin", "HEAD:main")
            return
        except subprocess.CalledProcessError:
            if attempt == 3:
                raise


if __name__ == "__main__":
    main(sys.argv[1])
