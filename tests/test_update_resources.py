from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_resources.py"


def load_updater():
    spec = importlib.util.spec_from_file_location("nbody6ppgpu_update_resources", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepositoryUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.old_environment = os.environ.copy()
        os.environ.update(
            {
                "HOME": str(self.home),
                "GIT_AUTHOR_NAME": "NBODY6 test",
                "GIT_AUTHOR_EMAIL": "nbody6-test@example.invalid",
                "GIT_COMMITTER_NAME": "NBODY6 test",
                "GIT_COMMITTER_EMAIL": "nbody6-test@example.invalid",
                "GIT_CONFIG_NOSYSTEM": "1",
            }
        )
        self.seed = self.root / "seed"
        self.remote = self.root / "official.git"
        self.git("init", str(self.seed))
        self.git("checkout", "-b", "dev", cwd=self.seed)
        self.commit_seed("initial")
        self.commit_seed("second")
        self.git("init", "--bare", str(self.remote))
        self.git("remote", "add", "origin", str(self.remote), cwd=self.seed)
        self.git("push", "-u", "origin", "dev", cwd=self.seed)
        self.git("symbolic-ref", "HEAD", "refs/heads/dev", cwd=self.remote)

        self.updater = load_updater()
        self.skill_dir = self.root / "skill"
        self.cache_root = self.root / "runtime-cache"
        self.updater.configure_cache_root(self.cache_root)
        self.updater.REMOTE_URL = str(self.remote)
        self.today = "2026-07-19"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.old_environment)
        self.temporary.cleanup()

    def git(
        self, *arguments: str, cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check and result.returncode:
            self.fail(
                f"git {' '.join(arguments)} failed ({result.returncode}): "
                f"{result.stderr or result.stdout}"
            )
        return result

    def commit_seed(self, label: str) -> None:
        tracked = self.seed / "history.txt"
        previous = tracked.read_text(encoding="utf-8") if tracked.exists() else ""
        tracked.write_text(f"{previous}{label}\n", encoding="utf-8")
        self.git("add", "history.txt", cwd=self.seed)
        self.git("commit", "-m", label, cwd=self.seed)

    def clone(self, name: str) -> Path:
        repository = self.root / name
        self.git(
            "clone",
            "--branch",
            "dev",
            "--single-branch",
            str(self.remote),
            str(repository),
        )
        return repository

    def snapshot(self, repository: Path) -> tuple[str, str, str, str]:
        branch_result = self.git(
            "symbolic-ref", "-q", "--short", "HEAD", cwd=repository, check=False
        )
        return (
            branch_result.stdout.strip() if branch_result.returncode == 0 else "DETACHED",
            self.git("rev-parse", "HEAD", cwd=repository).stdout.strip(),
            self.git("status", "--porcelain", cwd=repository).stdout,
            self.git("remote", "get-url", "origin", cwd=repository).stdout.strip(),
        )

    def assert_official_dev(self, repository: Path) -> None:
        self.assertEqual(
            self.git("branch", "--show-current", cwd=repository).stdout.strip(), "dev"
        )
        self.assertEqual(
            Path(self.git("remote", "get-url", "origin", cwd=repository).stdout.strip()),
            self.remote,
        )
        self.assertEqual(
            self.git("status", "--porcelain", cwd=repository).stdout.strip(), ""
        )
        self.assertEqual(
            self.git("rev-parse", "HEAD", cwd=repository).stdout.strip(),
            self.git("rev-parse", "origin/dev", cwd=repository).stdout.strip(),
        )

    def test_user_checkouts_are_never_selected_or_modified(self) -> None:
        def non_dev(repository: Path) -> None:
            self.git("checkout", "-b", "feature", cwd=repository)

        def dirty(repository: Path) -> None:
            (repository / "dirty.txt").write_text("dirty\n", encoding="utf-8")

        def wrong_origin(repository: Path) -> None:
            self.git("remote", "set-url", "origin", str(self.root / "wrong.git"), cwd=repository)

        def detached(repository: Path) -> None:
            self.git("checkout", "--detach", cwd=repository)

        mutations = {
            "compliant": lambda repository: None,
            "non-dev": non_dev,
            "dirty": dirty,
            "wrong-origin": wrong_origin,
            "detached": detached,
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                repository = self.clone(f"user-{name}")
                mutate(repository)
                before = self.snapshot(repository)
                self.updater.configure_cache_root(self.cache_root / name)
                state: dict[str, object] = {}

                selected = self.updater.refresh_code(state, self.today, False)

                self.assertEqual(selected, self.updater.FALLBACK_REPO)
                self.assert_official_dev(selected)
                self.assertEqual(self.snapshot(repository), before)

    def test_same_day_cached_branch_and_head_are_revalidated(self) -> None:
        state: dict[str, object] = {}
        first = self.updater.refresh_code(state, self.today, False)
        self.assertEqual(first, self.updater.FALLBACK_REPO)
        self.assert_official_dev(first)

        self.git("checkout", "-b", "feature", cwd=first)
        selected = self.updater.refresh_code(state, self.today, False)
        self.assertEqual(selected, self.updater.FALLBACK_REPO)
        self.assert_official_dev(selected)

        previous = self.git("rev-parse", "HEAD^", cwd=selected).stdout.strip()
        self.git("reset", "--hard", previous, cwd=selected)
        selected = self.updater.refresh_code(state, self.today, False)
        self.assertEqual(selected, self.updater.FALLBACK_REPO)
        self.assert_official_dev(selected)
        self.assertEqual(state["code"]["commit"], self.snapshot(selected)[1])

    def test_ahead_or_diverged_cached_repository_is_safely_rebuilt(self) -> None:
        ahead = self.updater.refresh_code({}, self.today, False)
        (ahead / "local.txt").write_text("ahead\n", encoding="utf-8")
        self.git("add", "local.txt", cwd=ahead)
        self.git("commit", "-m", "local ahead", cwd=ahead)
        selected = self.updater.refresh_code({}, self.today, False)
        self.assertEqual(selected, self.updater.FALLBACK_REPO)
        self.assert_official_dev(selected)

        diverged = selected
        (diverged / "local.txt").write_text("diverged\n", encoding="utf-8")
        self.git("add", "local.txt", cwd=diverged)
        self.git("commit", "-m", "local diverged", cwd=diverged)
        self.commit_seed("remote diverged")
        self.git("push", "origin", "dev", cwd=self.seed)
        selected = self.updater.refresh_code({}, self.today, False)
        self.assertEqual(selected, self.updater.FALLBACK_REPO)
        self.assert_official_dev(selected)

    def test_cached_clone_fetches_only_dev(self) -> None:
        selected = self.updater.refresh_code({}, self.today, False)
        self.assertEqual(selected, self.updater.FALLBACK_REPO)
        self.assert_official_dev(selected)
        self.assertEqual(
            self.git("config", "--get-all", "remote.origin.fetch", cwd=selected).stdout.strip(),
            "+refs/heads/dev:refs/remotes/origin/dev",
        )

    def test_corrupt_cache_is_rebuilt(self) -> None:
        state: dict[str, object] = {}
        selected = self.updater.refresh_code(state, self.today, False)
        self.assert_official_dev(selected)

        shutil.rmtree(selected)
        selected.mkdir(parents=True)
        (selected / "garbage").write_text("not a repository\n", encoding="utf-8")
        self.updater.REMOTE_URL = str(self.root / "temporarily-missing.git")
        with self.assertRaises(self.updater.UpdateError):
            self.updater.refresh_code(state, self.today, False)
        self.assertTrue((selected / "garbage").exists())

        self.updater.REMOTE_URL = str(self.remote)
        selected = self.updater.refresh_code(state, self.today, False)

        self.assertEqual(selected, self.updater.FALLBACK_REPO)
        self.assert_official_dev(selected)
        self.assertFalse((selected / "garbage").exists())

    def test_fallback_symlink_is_replaced_without_touching_external_repo(self) -> None:
        external = self.clone("external-behind")
        self.commit_seed("remote newer")
        self.git("push", "origin", "dev", cwd=self.seed)
        before = self.snapshot(external)

        self.updater.FALLBACK_REPO.parent.mkdir(parents=True)
        self.updater.FALLBACK_REPO.symlink_to(external, target_is_directory=True)
        selected = self.updater.refresh_code({}, self.today, False)

        self.assertEqual(selected, self.updater.FALLBACK_REPO)
        self.assertFalse(selected.is_symlink())
        self.assert_official_dev(selected)
        self.assertEqual(self.snapshot(external), before)

    def test_fallback_parent_escape_is_rejected(self) -> None:
        external_cache = self.root / "external-cache"
        external_cache.mkdir()
        self.updater.FALLBACK_REPO = external_cache / "escaped-repository"

        with self.assertRaisesRegex(self.updater.UpdateError, "runtime cache"):
            self.updater.refresh_code({}, self.today, False)

        self.assertEqual(list(external_cache.iterdir()), [])

    def test_failed_run_never_prints_repository_path(self) -> None:
        arguments = argparse.Namespace(
            cache_root=None,
            extract_with_pypdf=None,
            manual_only=False,
            code_only=True,
            force=False,
            print_resources=False,
            print_repo=True,
        )
        self.updater.REMOTE_URL = str(self.root / "missing-remote.git")
        output = io.StringIO()
        with mock.patch.object(self.updater, "parse_args", return_value=arguments):
            with contextlib.redirect_stdout(output):
                result = self.updater.main()
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "")

    def test_successful_main_prints_only_validated_repository(self) -> None:
        arguments = argparse.Namespace(
            cache_root=None,
            extract_with_pypdf=None,
            manual_only=False,
            code_only=True,
            force=False,
            print_resources=False,
            print_repo=True,
        )
        output = io.StringIO()
        with mock.patch.object(self.updater, "parse_args", return_value=arguments):
            with contextlib.redirect_stdout(output):
                result = self.updater.main()
        self.assertEqual(result, 0)
        printed = Path(output.getvalue().strip())
        self.assertEqual(printed, self.updater.FALLBACK_REPO)
        self.assert_official_dev(printed)

    def test_manual_failure_suppresses_successful_code_path(self) -> None:
        arguments = argparse.Namespace(
            cache_root=None,
            extract_with_pypdf=None,
            manual_only=False,
            code_only=False,
            force=False,
            print_resources=True,
            print_repo=False,
        )
        repository = self.clone("valid-code")
        output = io.StringIO()
        with (
            mock.patch.object(self.updater, "parse_args", return_value=arguments),
            mock.patch.object(self.updater, "load_state", return_value={}),
            mock.patch.object(self.updater, "refresh_code", return_value=repository),
            mock.patch.object(
                self.updater,
                "refresh_manual",
                side_effect=self.updater.UpdateError("manual failed"),
            ),
            contextlib.redirect_stdout(output),
        ):
            result = self.updater.main()
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "")

    def test_manual_refresh_writes_only_to_runtime_cache(self) -> None:
        host = self.root / "host-repository"
        assets = host / "skills" / "nbody6ppgpu-expert" / "assets"
        assets.mkdir(parents=True)
        bundled_pdf = assets / "Nb6manual.pdf"
        bundled_markdown = assets / "Nb6manual.md"
        bundled_pdf.write_bytes(b"%PDF-bundled")
        bundled_markdown.write_text("bundled manual\n", encoding="utf-8")
        self.git("init", str(host))
        self.git("add", ".", cwd=host)
        self.git("commit", "-m", "bundled snapshot", cwd=host)

        def convert(downloaded: Path) -> Path:
            converted = self.updater.MANUAL_DIR / "converted.md"
            converted.write_text("updated manual\n", encoding="utf-8")
            return converted

        state: dict[str, object] = {}
        with (
            mock.patch.object(
                self.updater.urllib.request,
                "urlopen",
                return_value=io.BytesIO(b"%PDF-updated"),
            ),
            mock.patch.object(self.updater, "convert_manual", side_effect=convert),
        ):
            self.updater.refresh_manual(state, self.today, True)

        self.assertEqual(self.updater.MANUAL_PDF.read_bytes(), b"%PDF-updated")
        self.assertEqual(
            self.updater.MANUAL_MARKDOWN.read_text(encoding="utf-8"),
            "updated manual\n",
        )
        self.assertEqual(bundled_pdf.read_bytes(), b"%PDF-bundled")
        self.assertEqual(
            bundled_markdown.read_text(encoding="utf-8"), "bundled manual\n"
        )
        self.assertEqual(self.git("status", "--porcelain", cwd=host).stdout, "")
        self.assertTrue(self.updater.manual_state_matches(state, self.today))

    def test_same_day_manual_is_revalidated_before_skip(self) -> None:
        self.updater.MANUAL_DIR.mkdir(parents=True)
        self.updater.MANUAL_PDF.write_bytes(b"%PDF-current")
        self.updater.MANUAL_MARKDOWN.write_text("current manual\n", encoding="utf-8")
        state = {
            "manual": {
                "date": self.today,
                "sha256": "wrong-digest",
                "markdown_sha256": self.updater.hashlib.sha256(
                    self.updater.MANUAL_MARKDOWN.read_bytes()
                ).hexdigest(),
            }
        }

        with mock.patch.object(
            self.updater.urllib.request,
            "urlopen",
            side_effect=self.updater.urllib.error.URLError("must refresh"),
        ):
            with self.assertRaises(self.updater.urllib.error.URLError):
                self.updater.refresh_manual(state, self.today, False)

        state["manual"]["sha256"] = self.updater.hashlib.sha256(
            self.updater.MANUAL_PDF.read_bytes()
        ).hexdigest()
        with mock.patch.object(self.updater.urllib.request, "urlopen") as urlopen:
            self.updater.refresh_manual(state, self.today, False)
        urlopen.assert_not_called()

        self.updater.MANUAL_MARKDOWN.write_text("stale manual\n", encoding="utf-8")
        with mock.patch.object(
            self.updater.urllib.request,
            "urlopen",
            side_effect=self.updater.urllib.error.URLError("must refresh"),
        ):
            with self.assertRaises(self.updater.urllib.error.URLError):
                self.updater.refresh_manual(state, self.today, False)

    def test_default_cache_root_uses_tmpdir_and_uid(self) -> None:
        temporary_root = self.root / "codex-tmp"
        with (
            mock.patch.dict(os.environ, {"TMPDIR": str(temporary_root)}),
            mock.patch.object(self.updater.os, "getuid", return_value=1234),
        ):
            first = self.updater.default_cache_root()
        with (
            mock.patch.dict(os.environ, {"TMPDIR": str(temporary_root)}),
            mock.patch.object(self.updater.os, "getuid", return_value=5678),
        ):
            second = self.updater.default_cache_root()

        self.assertEqual(
            first, (temporary_root / "nbody6ppgpu-expert-1234").resolve()
        )
        self.assertEqual(
            second, (temporary_root / "nbody6ppgpu-expert-5678").resolve()
        )
        self.assertNotEqual(first, second)

    def test_explicit_cache_root_rejects_relative_and_host_git_paths(self) -> None:
        self.skill_dir.mkdir()
        (self.skill_dir / ".git").mkdir()

        with self.assertRaisesRegex(self.updater.UpdateError, "absolute path"):
            self.updater.validate_cache_root(Path("relative-cache"))

        with mock.patch.object(self.updater, "SKILL_DIR", self.skill_dir):
            with self.assertRaisesRegex(self.updater.UpdateError, "Git working tree"):
                self.updater.validate_cache_root(self.skill_dir / "runtime")
        self.assertFalse((self.skill_dir / "runtime").exists())

    def test_invalid_cli_cache_root_fails_without_stdout_or_writes(self) -> None:
        target = Path("relative-cache")
        arguments = argparse.Namespace(
            cache_root=target,
            extract_with_pypdf=None,
            manual_only=False,
            code_only=False,
            force=False,
            print_resources=True,
            print_repo=False,
        )
        output = io.StringIO()
        with mock.patch.object(self.updater, "parse_args", return_value=arguments):
            with contextlib.redirect_stdout(output):
                result = self.updater.main()
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertFalse((self.root / target).exists())

    def test_cli_cache_root_rebinds_every_runtime_path(self) -> None:
        explicit = self.root / "persistent-cache"
        with mock.patch.object(
            self.updater.sys,
            "argv",
            ["update_resources.py", "--cache-root", str(explicit), "--code-only"],
        ):
            arguments = self.updater.parse_args()
        self.updater.configure_cache_root(arguments.cache_root)

        for runtime_path in (
            self.updater.FALLBACK_REPO,
            self.updater.MANUAL_DIR,
            self.updater.MANUAL_PDF,
            self.updater.MANUAL_MARKDOWN,
            self.updater.STATE_FILE,
            self.updater.PRIVATE_VENV,
        ):
            self.assertTrue(runtime_path.is_relative_to(explicit.resolve()))

    def test_same_day_second_invocation_preserves_manifest_without_network(self) -> None:
        arguments = argparse.Namespace(
            cache_root=None,
            extract_with_pypdf=None,
            manual_only=False,
            code_only=False,
            force=False,
            print_resources=True,
            print_repo=False,
        )

        def convert(downloaded: Path) -> Path:
            converted = self.updater.MANUAL_DIR / "converted.md"
            converted.write_text("KSTART manual\n", encoding="utf-8")
            return converted

        first_output = io.StringIO()
        with (
            mock.patch.object(self.updater, "parse_args", return_value=arguments),
            mock.patch.object(
                self.updater.urllib.request,
                "urlopen",
                return_value=io.BytesIO(b"%PDF-current"),
            ),
            mock.patch.object(self.updater, "convert_manual", side_effect=convert),
            contextlib.redirect_stdout(first_output),
        ):
            self.assertEqual(self.updater.main(), 0)

        second_output = io.StringIO()
        with (
            mock.patch.object(self.updater, "parse_args", return_value=arguments),
            mock.patch.object(self.updater, "fetch_remote_tip") as fetch_remote_tip,
            mock.patch.object(self.updater.urllib.request, "urlopen") as urlopen,
            contextlib.redirect_stdout(second_output),
        ):
            self.assertEqual(self.updater.main(), 0)

        fetch_remote_tip.assert_not_called()
        urlopen.assert_not_called()
        self.assertEqual(json.loads(first_output.getvalue()), json.loads(second_output.getvalue()))

    def test_resource_manifest_reports_only_runtime_paths(self) -> None:
        self.updater.FALLBACK_REPO.parent.mkdir(parents=True)
        self.git(
            "clone",
            "--branch",
            "dev",
            "--single-branch",
            str(self.remote),
            str(self.updater.FALLBACK_REPO),
        )
        repository = self.updater.FALLBACK_REPO
        self.updater.MANUAL_DIR.mkdir(parents=True)
        self.updater.MANUAL_PDF.write_bytes(b"%PDF-manifest")
        self.updater.MANUAL_MARKDOWN.write_text("manifest manual\n", encoding="utf-8")
        arguments = argparse.Namespace(
            cache_root=None,
            extract_with_pypdf=None,
            manual_only=False,
            code_only=False,
            force=False,
            print_resources=True,
            print_repo=False,
        )
        output = io.StringIO()
        with (
            mock.patch.object(self.updater, "parse_args", return_value=arguments),
            mock.patch.object(self.updater, "load_state", return_value={}),
            mock.patch.object(
                self.updater, "refresh_code", return_value=repository
            ),
            mock.patch.object(self.updater, "refresh_manual"),
            contextlib.redirect_stdout(output),
        ):
            result = self.updater.main()

        self.assertEqual(result, 0)
        manifest = json.loads(output.getvalue())
        self.assertEqual(Path(manifest["cache_root"]), self.cache_root.resolve())
        self.assertEqual(Path(manifest["repository"]), repository)
        self.assertEqual(
            Path(manifest["manual_markdown"]), self.updater.MANUAL_MARKDOWN
        )
        self.assertEqual(Path(manifest["manual_pdf"]), self.updater.MANUAL_PDF)
        self.assertEqual(
            manifest["code_commit"], self.updater.repository_commit(repository)
        )
        self.assertEqual(
            manifest["manual_sha256"],
            self.updater.hashlib.sha256(
                self.updater.MANUAL_PDF.read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(
            manifest["manual_markdown_sha256"],
            self.updater.hashlib.sha256(
                self.updater.MANUAL_MARKDOWN.read_bytes()
            ).hexdigest(),
        )
        for runtime_path in (
            repository,
            self.updater.MANUAL_PDF,
            self.updater.MANUAL_MARKDOWN,
            self.updater.STATE_FILE,
            self.updater.PRIVATE_VENV,
        ):
            self.assertTrue(
                runtime_path.resolve().is_relative_to(self.cache_root.resolve())
            )


if __name__ == "__main__":
    unittest.main()
