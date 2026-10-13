#!/usr/bin/env python3
"""Daily refresh of the source tree and NBODY6++GPU manual used by nbody6ppgpu-expert."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


REMOTE_URL = "https://github.com/nbody6ppgpu/Nbody6PPGPU-beijing"
BRANCH = "dev"
MANUAL_URL = "https://nbody6ppgpu.github.io/nb6-manual-pdf/latest.pdf"
SKILL_DIR = Path(__file__).resolve().parents[1]


class UpdateError(RuntimeError):
    """A recoverable resource refresh or configuration failure."""


def containing_git_root(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate.resolve()
    return None


def validate_cache_root(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise UpdateError(f"cache root must be an absolute path: {path}")

    candidate = expanded.resolve()
    git_root = containing_git_root(SKILL_DIR)
    unsafe_roots = [SKILL_DIR.resolve()]
    if git_root is not None:
        unsafe_roots.append(git_root)
    if any(candidate.is_relative_to(root) for root in unsafe_roots):
        raise UpdateError(
            f"cache root must not be inside the skill or its host Git working tree: {candidate}"
        )
    return candidate


def default_cache_root() -> Path:
    temporary_root = Path(os.environ.get("TMPDIR") or tempfile.gettempdir())
    return validate_cache_root(
        temporary_root / f"nbody6ppgpu-expert-{os.getuid()}"
    )


def configure_cache_root(path: Path) -> Path:
    """Validate the cache root and rebind all runtime resource paths in one shot."""
    global CACHE_ROOT, FALLBACK_REPO, MANUAL_DIR
    global MANUAL_PDF, MANUAL_MARKDOWN, STATE_FILE, PRIVATE_VENV

    CACHE_ROOT = validate_cache_root(path)
    FALLBACK_REPO = CACHE_ROOT / "repos" / "Nbody6PPGPU-beijing-dev"
    MANUAL_DIR = CACHE_ROOT / "manual"
    MANUAL_PDF = MANUAL_DIR / "Nb6manual.pdf"
    MANUAL_MARKDOWN = MANUAL_DIR / "Nb6manual.md"
    STATE_FILE = CACHE_ROOT / "update-state.json"
    PRIVATE_VENV = CACHE_ROOT / "manual-venv"
    return CACHE_ROOT


configure_cache_root(default_cache_root())


def run(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        raise UpdateError(f"{' '.join(command)} failed: {details}")
    return result.stdout.strip()


def load_state() -> dict[str, Any]:
    try:
        with STATE_FILE.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as error:
        print(f"ignoring corrupt update state {STATE_FILE}: {error}", file=sys.stderr)
        return {}
    return state if isinstance(state, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=STATE_FILE.parent, delete=False
    ) as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, STATE_FILE)


def update_metadata(*, date_string: str, **details: str) -> dict[str, str]:
    return {
        "date": date_string,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **details,
    }


def repository_commit(repository: Path) -> str:
    return run(["git", "rev-parse", "HEAD"], cwd=repository)


def normalize_remote(remote: str) -> str:
    normalized = remote.rstrip("/")
    return normalized[:-4] if normalized.endswith(".git") else normalized


def is_expected_remote(remote: str) -> bool:
    expected = {normalize_remote(REMOTE_URL)}
    if normalize_remote(REMOTE_URL) == normalize_remote(
        "https://github.com/nbody6ppgpu/Nbody6PPGPU-beijing"
    ):
        expected.update(
            {
                "git@github.com:nbody6ppgpu/Nbody6PPGPU-beijing",
                "ssh://git@github.com/nbody6ppgpu/Nbody6PPGPU-beijing",
            }
        )
    return normalize_remote(remote) in expected


def require_worktree_root(repository: Path) -> None:
    if not repository.is_dir():
        raise UpdateError(f"source path is not a directory: {repository}")
    if run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repository) != "true":
        raise UpdateError(f"source path is not a Git working tree: {repository}")
    top_level = Path(run(["git", "rev-parse", "--show-toplevel"], cwd=repository))
    if top_level.resolve() != repository.resolve():
        raise UpdateError(f"source path is not the root of a standalone Git working tree: {repository}")


def validate_repository(repository: Path, *, expected_tip: str | None = None) -> str:
    require_worktree_root(repository)
    remote = run(["git", "remote", "get-url", "origin"], cwd=repository)
    if not is_expected_remote(remote):
        raise UpdateError(f"source origin is not the expected repository: {remote}")
    if run(["git", "status", "--porcelain"], cwd=repository):
        raise UpdateError(f"source working tree has uncommitted changes, refusing to update: {repository}")
    branch = run(["git", "branch", "--show-current"], cwd=repository)
    if branch != BRANCH:
        raise UpdateError(
            f"source is currently on branch {branch or 'detached HEAD'}, expected {BRANCH}; refusing to switch branches"
        )
    head = repository_commit(repository)
    origin_tip = run(
        ["git", "rev-parse", "--verify", f"refs/remotes/origin/{BRANCH}"],
        cwd=repository,
    )
    if head != origin_tip:
        raise UpdateError(
            f"source HEAD ({head}) does not match origin/{BRANCH} ({origin_tip}): {repository}"
        )
    if expected_tip is not None and head != expected_tip:
        raise UpdateError(
            f"source HEAD ({head}) does not match the official {BRANCH} tip fetched this run ({expected_tip})"
        )
    return head


def fetch_remote_tip(repository: Path) -> str:
    run(
        [
            "git",
            "fetch",
            "--prune",
            "origin",
            f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}",
        ],
        cwd=repository,
    )
    return run(
        ["git", "rev-parse", "--verify", f"refs/remotes/origin/{BRANCH}"],
        cwd=repository,
    )


def is_ancestor(ancestor: str, descendant: str, repository: Path) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repository,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode not in (0, 1):
        raise UpdateError(f"unable to compare source commit ancestry: {repository}")
    return result.returncode == 0


def refresh_existing_repository(repository: Path) -> str:
    """Only fast-forward a clean dev; refuse to touch anything ahead or diverged locally."""
    # Validate the user-visible state that fetch cannot change first, to avoid touching a non-compliant checkout.
    require_worktree_root(repository)
    remote = run(["git", "remote", "get-url", "origin"], cwd=repository)
    if not is_expected_remote(remote):
        raise UpdateError(f"source origin is not the expected repository: {remote}")
    if run(["git", "status", "--porcelain"], cwd=repository):
        raise UpdateError(f"source working tree has uncommitted changes, refusing to update: {repository}")
    branch = run(["git", "branch", "--show-current"], cwd=repository)
    if branch != BRANCH:
        raise UpdateError(
            f"source is currently on branch {branch or 'detached HEAD'}, expected {BRANCH}; refusing to switch branches"
        )

    head = repository_commit(repository)
    official_tip = fetch_remote_tip(repository)
    if head != official_tip:
        if not is_ancestor(head, official_tip, repository):
            raise UpdateError(
                f"source {BRANCH} has local commits ahead or diverged, refusing to change it: {repository}"
            )
        run(["git", "merge", "--ff-only", official_tip], cwd=repository)
    return validate_repository(repository, expected_tip=official_tip)


def require_fallback_location() -> None:
    expected_parent = CACHE_ROOT.resolve() / "repos"
    if FALLBACK_REPO.parent.resolve() != expected_parent:
        raise UpdateError(f"fallback source cache parent escapes the runtime cache: {FALLBACK_REPO.parent}")


def clone_fallback_repository() -> str:
    require_fallback_location()
    FALLBACK_REPO.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=FALLBACK_REPO.parent, prefix=".Nbody6PPGPU-beijing-dev-clone-"
    ) as temporary_parent:
        clone = Path(temporary_parent) / FALLBACK_REPO.name
        run(
            [
                "git",
                "clone",
                "--branch",
                BRANCH,
                "--single-branch",
                REMOTE_URL,
                str(clone),
            ]
        )
        validate_repository(clone)
        clear_fallback_repository()
        os.replace(clone, FALLBACK_REPO)
    return validate_repository(FALLBACK_REPO)


def clear_fallback_repository() -> None:
    require_fallback_location()
    if FALLBACK_REPO.is_symlink() or FALLBACK_REPO.is_file():
        FALLBACK_REPO.unlink(missing_ok=True)
    elif FALLBACK_REPO.exists():
        shutil.rmtree(FALLBACK_REPO)


def ensure_fallback_repository() -> str:
    require_fallback_location()
    if FALLBACK_REPO.is_symlink():
        print("fallback source cache is a symlink, rebuilding it safely.", file=sys.stderr)
        return clone_fallback_repository()
    if not FALLBACK_REPO.exists():
        return clone_fallback_repository()
    try:
        return refresh_existing_repository(FALLBACK_REPO)
    except (OSError, UpdateError) as error:
        print(f"fallback source cache is unusable, rebuilding it safely: {error}", file=sys.stderr)
        return clone_fallback_repository()


def code_state_matches(
    state: dict[str, Any], today: str, repository: Path, *, force: bool
) -> bool:
    if force or not repository.is_dir():
        return False
    details = state.get("code")
    if not isinstance(details, dict):
        return False
    try:
        recorded_repository = Path(details["repository"])
        recorded_commit = details["commit"]
    except (KeyError, TypeError):
        return False
    if not (
        details.get("date") == today
        and details.get("branch") == BRANCH
        and recorded_repository.resolve() == repository.resolve()
    ):
        return False
    try:
        return recorded_commit == repository_commit(repository)
    except UpdateError:
        return False


def record_code_state(
    state: dict[str, Any], today: str, repository: Path, commit: str
) -> None:
    state["code"] = update_metadata(
        date_string=today,
        repository=str(repository.resolve()),
        branch=BRANCH,
        commit=commit,
    )
    save_state(state)


def refresh_code(state: dict[str, Any], today: str, force: bool) -> Path:
    if not FALLBACK_REPO.is_symlink() and code_state_matches(
        state, today, FALLBACK_REPO, force=force
    ):
        try:
            validate_repository(FALLBACK_REPO)
        except UpdateError:
            pass
        else:
            print(f"source already updated and validated today, skipping: {FALLBACK_REPO}", file=sys.stderr)
            return FALLBACK_REPO

    commit = ensure_fallback_repository()
    record_code_state(state, today, FALLBACK_REPO, commit)
    print(f"source updated and validated: {FALLBACK_REPO}", file=sys.stderr)
    return FALLBACK_REPO


def extract_with_pypdf(pdf_path: Path, output_path: Path) -> None:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise UpdateError(f"current interpreter does not have pypdf installed: {sys.executable}") from error

    try:
        reader = PdfReader(str(pdf_path))
        text = "\n\f\n".join(page.extract_text() or "" for page in reader.pages)
        output_path.write_text(text, encoding="utf-8")
    except Exception as error:
        raise UpdateError(f"pypdf failed to extract the manual: {error}") from error


def venv_python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def pypdf_importable(python: Path) -> bool:
    result = subprocess.run(
        [str(python), "-c", "import pypdf"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def ensure_pypdf_interpreter() -> Path:
    """Return a Python interpreter path that can `import pypdf`, with no sudo or system package manager required.

    Works on any machine: prefers reusing the current interpreter or an already-cached
    private venv; otherwise builds a user-level venv in the runtime cache with
    `python3 -m venv` and installs pypdf into it.
    """
    override = os.environ.get("NBODY6_MANUAL_PYTHON")
    if override:
        python = Path(override)
        if not python.is_file():
            raise UpdateError(f"NBODY6_MANUAL_PYTHON is not a file: {python}")
        if not pypdf_importable(python):
            raise UpdateError(f"the interpreter pointed to by NBODY6_MANUAL_PYTHON cannot import pypdf: {python}")
        return python

    current = Path(sys.executable)
    if pypdf_importable(current):
        return current

    cached = venv_python(PRIVATE_VENV)
    if cached.is_file() and pypdf_importable(cached):
        return cached

    candidates = [current]
    system_python3 = shutil.which("python3")
    if system_python3 and Path(system_python3) not in candidates:
        candidates.append(Path(system_python3))

    last_error: Exception | None = None
    for base_python in candidates:
        shutil.rmtree(PRIVATE_VENV, ignore_errors=True)
        try:
            run([str(base_python), "-m", "venv", str(PRIVATE_VENV)])
            run([str(cached), "-m", "pip", "install", "--quiet", "pypdf"])
            if pypdf_importable(cached):
                return cached
        except UpdateError as error:
            last_error = error
            continue
    shutil.rmtree(PRIVATE_VENV, ignore_errors=True)
    raise UpdateError(
        "pdftotext is not installed, and no candidate Python could build a user-level "
        "venv and install pypdf (all without sudo). "
        f"Last error: {last_error}. "
        "Make sure python3 ships with the venv module and can reach PyPI, "
        "or set NBODY6_MANUAL_PYTHON to point at an interpreter with pypdf already installed."
    )


def convert_manual(pdf_path: Path) -> Path:
    with tempfile.NamedTemporaryFile(dir=MANUAL_DIR, suffix=".md", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        if shutil.which("pdftotext"):
            run(["pdftotext", "-layout", str(pdf_path), str(temporary)])
        else:
            python = ensure_pypdf_interpreter()
            script = Path(__file__).resolve()
            run([str(python), str(script), "--extract-with-pypdf", str(pdf_path), str(temporary)])
        if not temporary.read_text(encoding="utf-8", errors="ignore").strip():
            raise UpdateError("extracted PDF text is empty")
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def replace_manual_pair(downloaded: Path, converted: Path) -> None:
    """Prepare both files together; restore the previous complete pair if the second replace fails."""
    backups: list[tuple[Path, Path]] = []
    replaced: list[Path] = []
    try:
        for target in (MANUAL_PDF, MANUAL_MARKDOWN):
            if target.exists():
                with tempfile.NamedTemporaryFile(
                    dir=MANUAL_DIR, prefix=f".{target.name}.", suffix=".bak", delete=False
                ) as handle:
                    backup = Path(handle.name)
                os.replace(target, backup)
                backups.append((target, backup))
        os.replace(downloaded, MANUAL_PDF)
        replaced.append(MANUAL_PDF)
        os.replace(converted, MANUAL_MARKDOWN)
        replaced.append(MANUAL_MARKDOWN)
    except OSError:
        for target in replaced:
            target.unlink(missing_ok=True)
        for target, backup in backups:
            os.replace(backup, target)
        raise
    else:
        for _, backup in backups:
            backup.unlink(missing_ok=True)


def manual_state_matches(state: dict[str, Any], today: str) -> bool:
    details = state.get("manual")
    if not isinstance(details, dict) or details.get("date") != today:
        return False
    try:
        if MANUAL_PDF.stat().st_size < 5:
            return False
        if MANUAL_PDF.read_bytes()[:5] != b"%PDF-":
            return False
        markdown = MANUAL_MARKDOWN.read_bytes()
        if not markdown.decode("utf-8", errors="ignore").strip():
            return False
        pdf_digest = hashlib.sha256(MANUAL_PDF.read_bytes()).hexdigest()
        markdown_digest = hashlib.sha256(markdown).hexdigest()
    except OSError:
        return False
    return (
        details.get("sha256") == pdf_digest
        and details.get("markdown_sha256") == markdown_digest
    )


def refresh_manual(state: dict[str, Any], today: str, force: bool) -> None:
    if not force and manual_state_matches(state, today):
        print("manual already updated and validated today, skipping.", file=sys.stderr)
        return

    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=MANUAL_DIR, suffix=".pdf", delete=False) as handle:
        downloaded = Path(handle.name)
    converted: Path | None = None
    try:
        request = urllib.request.Request(MANUAL_URL, headers={"User-Agent": "nbody6ppgpu-expert"})
        with urllib.request.urlopen(request, timeout=60) as response, downloaded.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if downloaded.stat().st_size < 5 or downloaded.read_bytes()[:5] != b"%PDF-":
            raise UpdateError(f"downloaded content is not a valid PDF: {MANUAL_URL}")
        converted = convert_manual(downloaded)
        replace_manual_pair(downloaded, converted)
    except Exception:
        downloaded.unlink(missing_ok=True)
        if converted is not None:
            converted.unlink(missing_ok=True)
        raise

    state["manual"] = update_metadata(
        date_string=today,
        url=MANUAL_URL,
        sha256=hashlib.sha256(MANUAL_PDF.read_bytes()).hexdigest(),
        markdown_sha256=hashlib.sha256(MANUAL_MARKDOWN.read_bytes()).hexdigest(),
    )
    save_state(state)
    print(f"manual updated and converted to Markdown: {MANUAL_PDF}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--code-only", action="store_true", help="only check/refresh the source")
    group.add_argument("--manual-only", action="store_true", help="only check/refresh the manual")
    parser.add_argument("--force", action="store_true", help="ignore today's state and refresh immediately")
    parser.add_argument(
        "--cache-root",
        type=Path,
        help=(
            "explicit absolute cache root; must not be inside the skill or its host Git "
            "working tree. Defaults to ${TMPDIR}/nbody6ppgpu-expert-<uid>"
        ),
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--print-resources",
        action="store_true",
        help="on success, print this run's validated source and manual paths as JSON",
    )
    output_group.add_argument(
        "--print-repo",
        action="store_true",
        help="on success, print only the source path actually used (compatibility interface)",
    )
    parser.add_argument("--extract-with-pypdf", nargs=2, type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.print_resources and (args.code_only or args.manual_only):
        parser.error("--print-resources requires refreshing both the source and the manual")
    return args


def main() -> int:
    args = parse_args()
    try:
        cache_root = getattr(args, "cache_root", None)
        if cache_root is not None:
            configure_cache_root(cache_root)
    except UpdateError as error:
        print(f"invalid cache root: {error}", file=sys.stderr)
        return 1

    if args.extract_with_pypdf:
        try:
            extract_with_pypdf(*args.extract_with_pypdf)
        except UpdateError as error:
            print(error, file=sys.stderr)
            return 1
        return 0

    state = load_state()
    today = datetime.now().astimezone().date().isoformat()
    errors: list[str] = []
    repository: Path | None = None

    if not args.manual_only:
        try:
            repository = refresh_code(state, today, args.force)
        except (OSError, UpdateError) as error:
            errors.append(f"source update failed: {error}")
    if not args.code_only:
        try:
            refresh_manual(state, today, args.force)
        except (OSError, UpdateError, urllib.error.URLError) as error:
            errors.append(f"manual update failed: {error}")

    for error in errors:
        print(error, file=sys.stderr)
    if not errors and repository is not None:
        try:
            if args.print_resources:
                manual_sha256 = hashlib.sha256(MANUAL_PDF.read_bytes()).hexdigest()
                manual_markdown_sha256 = hashlib.sha256(
                    MANUAL_MARKDOWN.read_bytes()
                ).hexdigest()
                print(
                    json.dumps(
                        {
                            "cache_root": str(CACHE_ROOT),
                            "code_commit": repository_commit(repository),
                            "manual_markdown": str(MANUAL_MARKDOWN),
                            "manual_markdown_sha256": manual_markdown_sha256,
                            "manual_pdf": str(MANUAL_PDF),
                            "manual_sha256": manual_sha256,
                            "repository": str(repository),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            elif args.print_repo:
                print(repository)
        except (OSError, UpdateError) as error:
            print(f"failed to generate resource manifest: {error}", file=sys.stderr)
            return 1
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
