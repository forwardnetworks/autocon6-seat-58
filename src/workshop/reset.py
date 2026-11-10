"""``workshop reset --to N``: start exercise N again from a known point, whatever state things are in.

What it does, in order (each printed as it happens):
  1. Git: anything you changed is kept with ``git stash`` (``git stash list`` shows it, ``git stash pop`` brings it back),
     then you are on ``main`` with the latest from GitHub. Nothing is deleted.
  2. Routers: all four get their baseline configuration again over NAPALM, and r4 loses any extra advertisement.
     ``--rebuild`` first removes the lab and builds it from scratch (for a router that is broken beyond its config).
  3. The starting point of exercise N: a fresh baseline from exercise 2 on, and the candidate the exercise starts from.
Pull requests on GitHub are left alone: close any you no longer want there.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

from workshop import baseline, candidate, lab, restore, show
from workshop.config import Settings

R4_PREFIXES = ("10.20.20.0/24", "10.20.30.0/24", "10.20.40.0/24")
STARTS: dict[int, dict] = {
    1: {"what": "exercise 1: the lab at its baseline config, no baseline in Forward yet", "baseline": False, "retire": None},
    2: {"what": "exercise 2: a fresh baseline, an empty change", "baseline": True, "retire": None},
    3: {"what": "exercise 3: a fresh baseline, an empty change", "baseline": True, "retire": None},
    4: {"what": "exercise 4: a fresh baseline, and the change that breaks the service (retire all three) to fix",
        "baseline": True, "retire": list(R4_PREFIXES)},
    5: {"what": "exercise 5: a fresh baseline, and the fixed change (retire the two stale ones). Deploy still needs it merged in a PR",
        "baseline": True, "retire": ["10.20.30.0/24", "10.20.40.0/24"]},
}


class ResetError(RuntimeError):
    pass


def _git(settings: Settings, log, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    show.shell(log, ["git", *args])
    out = subprocess.run(["git", *args], cwd=settings.repo_root, capture_output=True, text=True, check=False)
    if check and out.returncode != 0:
        raise ResetError(f"git {' '.join(args)} failed: {(out.stderr or out.stdout).strip()[:300]}")
    return out


def write_candidate(settings: Settings, retire: list[str] | None) -> None:
    """candidate/r4-bgp.eos as main has it, plus ``no network`` for each prefix in ``retire``."""
    path = settings.repo_root / "candidate" / "r4-bgp.eos"
    if not retire:
        return
    head = [line for line in path.read_text().splitlines() if line.startswith("!")]
    lines = [*head, candidate.HEADER[0], f"   {candidate.HEADER[1]}", *[f"      no network {p}" for p in R4_PREFIXES if p in retire]]
    path.write_text("\n".join(lines) + "\n")


def run(settings: Settings, to: int, log, *, rebuild: bool = False) -> None:
    start = STARTS[to]
    log(f"resetting to the start of {start['what']}")
    log("")
    log("1. Git: keep your work, then back to main")
    if _git(settings, log, "status", "--porcelain").stdout.strip():
        stamp = datetime.now(UTC).strftime("%H%M%S")
        _git(settings, log, "stash", "push", "--include-untracked", "-m", f"workshop reset {stamp}")
        log(f"  your changes are kept: `git stash list` shows 'workshop reset {stamp}', `git stash pop` brings them back")
    _git(settings, log, "switch", "main")
    pulled = _git(settings, log, "pull", "--ff-only", check=False)
    if pulled.returncode != 0:
        log("  (could not pull from GitHub just now; carrying on with the main you have)")
    log("")
    log("2. Routers: back to their baseline configuration")
    if rebuild:
        log("  --rebuild: removing the lab and building it again (3 to 10 minutes)")
        lab._run(["netlab", "down", "--cleanup"], lab.lab_dir(settings), log=log)
    lab.up(settings, log)
    restore.run(settings, log)
    log("")
    log("3. The starting point of the exercise")
    if start["retire"]:
        write_candidate(settings, start["retire"])
        log(f"  candidate/r4-bgp.eos now retires: {', '.join(start['retire'])}   (not committed: that's your next step)")
    else:
        log("  candidate/r4-bgp.eos is main's: no change yet")
    if start["baseline"]:
        snap, _fp, report = baseline.run(settings, log)
        status = report.status.value if report else "?"
        log(f"  fresh baseline: snapshot {snap}, requirements {status}")
        if status != "PASS":
            raise ResetError(f"the fresh baseline is {status}, not PASS: run `workshop reset --to {to} --rebuild`, or ask a proctor")
    log("")
    log(f"Ready: you are at the start of exercise {to}. Open docs/exercises/ for it, or the Your lab page.")
