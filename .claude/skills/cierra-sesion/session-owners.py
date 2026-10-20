#!/usr/bin/env python3
"""Read-only census used by /cierra-sesion: what is pending in this repository, and who owns it.

Prints one block per place where unfinished work can live and says, for everything that is not
this session's, whether a live Claude session owns it or it is an orphan.

Ownership is decided from facts, not guessed:
  * a worktree belongs to a live session whose registered working directory is that worktree
    (or inside it);
  * a session that was opened somewhere else and works in a worktree by absolute path (its
    registered directory is not the worktree) is found by activity instead: a process whose
    working directory is inside the worktree, traced up its parents to a live session, or a file
    edited in the last 30 minutes. Both mean the worktree is in use, never an orphan;
  * running containers whose compose working directory is a worktree are reported next to it,
    and a stack whose folder no longer exists is listed on its own: nobody can stop it by
    accident from inside the repository, but nobody owns it either;
  * the shared main checkout belongs, as a place, to the live sessions working in it, but git
    cannot say which of them wrote a given file, so its dirty files are reported with the sessions
    that could own them and the age of the newest edit;
  * a stash entry records no session, so it never has a provable owner.
A "live" session is a ~/.claude/sessions/<pid>.json whose pid still exists and whose start time
still matches (a recycled pid is not the same session).

Usage: python3 session-owners.py [--limit N]     (run it from inside the repository)
Exit 0 always; it only reads.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

LIMIT = 12
if "--limit" in sys.argv:
    LIMIT = int(sys.argv[sys.argv.index("--limit") + 1])

SESSIONS_DIR = Path.home() / ".claude" / "sessions"
NOW = time.time()


def git(path, *args):
    result = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def proc_start(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        # Field 22, counted after the "(comm)" field, which may itself contain spaces.
        return stat.rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def live_sessions():
    sessions = []
    for file in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(file.read_text())
        except (OSError, ValueError):
            continue
        pid = data.get("pid")
        if not isinstance(pid, int):
            continue
        started = proc_start(pid)
        if started is None:
            continue
        recorded = str(data.get("procStart", ""))
        if recorded and recorded != started:
            continue
        sessions.append(
            {
                "pid": pid,
                "name": data.get("name") or data.get("sessionId", "")[:8],
                "cwd": os.path.realpath(data.get("cwd") or "/"),
                "status": data.get("status", "?"),
                "kind": data.get("kind", ""),
            }
        )
    return sessions


def ancestors():
    chain, pid = set(), os.getpid()
    while pid > 1:
        chain.add(pid)
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            pid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return chain


def inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def age(seconds):
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 5400:
        return f"{int(seconds / 60)} min"
    if seconds < 172800:
        return f"{int(seconds / 3600)} h"
    return f"{int(seconds / 86400)} d"


def describe(owners):
    return "; ".join(f"«{s['name']}» (pid {s['pid']}, {s['status']})" for s in owners)


FRESH_EDIT_SECONDS = 30 * 60
RECENT_WORKTREE_SECONDS = 3 * 3600
STALE_SECONDS = 24 * 3600


def parent_of(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return int(stat.rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def processes_inside(root, skip):
    """Pids whose working directory is inside `root`, excluding this census's own ancestors."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in skip:
            continue
        try:
            cwd = os.path.realpath(os.readlink(entry / "cwd"))
        except OSError:
            continue
        if inside(cwd, root):
            found.append(pid)
    return found


def session_of(pid, by_pid):
    """The live session that `pid` descends from, if any."""
    seen = 0
    while pid > 1 and seen < 64:
        if pid in by_pid:
            return by_pid[pid]
        pid = parent_of(pid)
        seen += 1
    return None


def compose_stacks():
    """{compose working directory: container count} for running containers, or None if docker is unreachable."""
    try:
        result = subprocess.run(
            ["timeout", "20", "docker", "ps", "--format",
             '{{.Label "com.docker.compose.project.working_dir"}}'],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    counts = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            counts[os.path.realpath(line)] = counts.get(os.path.realpath(line), 0) + 1
    return counts


def newest_edit(path, dirty_lines):
    newest = 0.0
    for line in dirty_lines[:LIMIT]:
        rel = line[3:].split(" -> ")[-1].strip('"')
        try:
            newest = max(newest, (Path(path) / rel).stat().st_mtime)
        except OSError:
            continue
    return newest


top = git(".", "rev-parse", "--show-toplevel")
if not top:
    print("No es un repositorio git: nada que censar.")
    sys.exit(0)
top = os.path.realpath(top)
common = git(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
main_checkout = os.path.realpath(str(Path(common).parent)) if common else top
base_branch = git(main_checkout, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"

me = ancestors()
everyone = live_sessions()
others = [s for s in everyone if s["pid"] not in me]

worktrees = []
current = {}
for line in git(main_checkout, "worktree", "list", "--porcelain").splitlines() + [""]:
    if not line:
        if current:
            worktrees.append(current)
        current = {}
    elif line.startswith("worktree "):
        current["path"] = os.path.realpath(line[9:])
    elif line.startswith("branch "):
        current["branch"] = line[7:].replace("refs/heads/", "")
    elif line == "detached":
        current["branch"] = "(detached)"
    elif line.startswith("prunable"):
        current["prunable"] = True

project_sessions = [
    s for s in others if any(inside(s["cwd"], w["path"]) for w in worktrees)
]

print(f"REPO {main_checkout}  base={base_branch}")
print(f"THIS_WORKTREE {top}")
print(f"LIVE_SESSIONS_IN_PROJECT {len(project_sessions)} (other than this one)")

by_pid = {s["pid"]: s for s in others}
stacks = compose_stacks()
worktree_paths = {w["path"] for w in worktrees}

print("\n== WORKTREES OF OTHER SESSIONS ==")
shown = 0
for tree in worktrees:
    path = tree["path"]
    if path in (top, main_checkout) or tree.get("prunable"):
        continue
    branch = tree.get("branch", "?")
    dirty = [l for l in git(path, "status", "--porcelain").splitlines() if l.strip()]
    ahead = git(path, "rev-list", "--count", f"{base_branch}..HEAD") or "0"
    if not dirty and ahead == "0":
        state = "limpio y sin nada que fusionar"
    else:
        state = f"{len(dirty)} ficheros sin commitear, {ahead} commits sin fusionar en {base_branch}"
    owners = [s for s in others if inside(s["cwd"], path)]
    worker_pids = processes_inside(path, me)
    active_owners = []
    for pid in worker_pids:
        session = session_of(pid, by_pid)
        if session and session not in active_owners and session not in owners:
            active_owners.append(session)
    unattributed = [pid for pid in worker_pids if not session_of(pid, by_pid)]
    last_edit = newest_edit(path, dirty)
    fresh = last_edit and NOW - last_edit < FRESH_EDIT_SECONDS
    containers = (stacks or {}).get(path, 0)
    born = git(path, "reflog", "--format=%ct").splitlines()
    created_age = NOW - int(born[-1]) if born and born[-1].isdigit() else None
    if owners:
        owner = f"PROPIETARIA {describe(owners)}"
    elif active_owners:
        owner = (
            f"PROPIETARIA POR ACTIVIDAD {describe(active_owners)}: un proceso suyo trabaja ahí "
            "aunque su directorio registrado es otro (no es huérfano)"
        )
    elif unattributed:
        owner = (
            f"CON ACTIVIDAD sin sesión identificada (pids {', '.join(map(str, unattributed[:4]))}): "
            "algo se ejecuta ahí ahora mismo (no es huérfano)"
        )
    elif fresh:
        owner = f"EDITADO HACE {age(NOW - last_edit)}: probablemente en uso (no es huérfano)"
    elif containers and created_age is not None and created_age < RECENT_WORKTREE_SECONDS:
        owner = (
            f"CREADO HACE {age(created_age)} y con {containers} contenedores encendidos: "
            "probablemente en uso, aunque no se ve ningún proceso ahora (no se da por huérfano)"
        )
    else:
        owner = "HUÉRFANO (ninguna sesión viva trabaja ahí)"
        if containers:
            owner += f"; tiene {containers} contenedores encendidos: no los pares sin preguntar"
    if containers and not owner.startswith("HUÉRFANO"):
        owner += f"; stack encendido ({containers} contenedores)"
    print(f"WORKTREE {path}\n  rama={branch}  estado: {state}\n  {owner}")
    shown += 1
if not shown:
    print("(ninguno)")

print("\n== STACKS SIN CARPETA ==")
if stacks is None:
    print("(no se ha podido consultar docker)")
else:
    # A stack counts as this project's only if it lives where this project's worktrees live.
    parents = {os.path.dirname(p) for p in worktree_paths if p != main_checkout}
    parents.add(os.path.join(main_checkout, ".claude", "worktrees"))
    lost = [
        (wd, n) for wd, n in stacks.items()
        if wd not in worktree_paths and wd != main_checkout and os.path.dirname(wd) in parents
    ]
    if not lost:
        print("(ninguno)")
    for wd, n in lost:
        gone = "la carpeta ya no existe" if not os.path.exists(wd) else "la carpeta existe pero no es un worktree registrado"
        print(f"STACK {wd}\n  {n} contenedores encendidos; {gone}\n  HUÉRFANO (nadie lo posee; pararlo lo decide su dueño o el desarrollador)")

print("\n== CHECKOUT PRINCIPAL ==")
if top == main_checkout:
    print("Es el árbol de esta sesión; sus cambios se separan por el hilo, no por esta lista.")
else:
    dirty = [l for l in git(main_checkout, "status", "--porcelain").splitlines() if l.strip()]
    here = [s for s in others if s["cwd"] == main_checkout]
    if not dirty:
        print("limpio")
    else:
        newest = 0.0
        for line in dirty[:LIMIT]:
            rel = line[3:].split(" -> ")[-1].strip('"')
            try:
                mtime = (Path(main_checkout) / rel).stat().st_mtime
            except OSError:
                mtime = 0.0
            newest = max(newest, mtime)
            print(f"DIRTY {line[:2].strip() or '?'} {rel}" + (f"  (editado hace {age(NOW - mtime)})" if mtime else ""))
        if len(dirty) > LIMIT:
            print(f"… y {len(dirty) - LIMIT} más")
        print(f"{len(dirty)} entradas sin commitear; la más reciente hace {age(NOW - newest) if newest else '?'}.")
        if newest and NOW - newest > STALE_SECONDS:
            print(
                f"SIN TOCAR desde hace {age(NOW - newest)}: nadie los ha editado en ese tiempo, así que lo más "
                "probable es que sean restos de una sesión que ya no está en ello (tratar como huérfanos, "
                "sin afirmar de quién eran)."
            )
        elif here:
            print(f"POSIBLES PROPIETARIAS (sesiones vivas en este checkout): {describe(here)}")
            print("  Git no dice quién escribió cada fichero: atribuirlo por el hilo o preguntarle a la sesión.")
        else:
            print("HUÉRFANO (ninguna sesión viva trabaja en este checkout)")

print("\n== STASHES ==")
stashes = git(main_checkout, "stash", "list").splitlines()
if not stashes:
    print("(ninguno)")
for entry in stashes[:LIMIT]:
    print(f"STASH {entry[:150]}\n  HUÉRFANO (un stash no registra la sesión que lo creó)")
