#!/bin/sh
# Install script for nbody6ppgpu-expert (POSIX sh, compatible with macOS / Ubuntu / Rocky Linux
# and other environments without bash-only features).
#
# One-line install:
#   curl -fsSL https://raw.githubusercontent.com/kaiwu-astro/nbody6ppgpu-expert/main/install.sh | sh
#
# Install to Claude Code only:
#   curl -fsSL https://raw.githubusercontent.com/kaiwu-astro/nbody6ppgpu-expert/main/install.sh | sh -s -- --claude
#
# Install to Codex only:
#   curl -fsSL https://raw.githubusercontent.com/kaiwu-astro/nbody6ppgpu-expert/main/install.sh | sh -s -- --codex
#
# Environment variables:
#   NBODY6PPGPU_EXPERT_SOURCE   Testing only: skip the download and use this local directory
#                               directly as the skill source directory (the directory itself
#                               is the skill root, i.e. it contains SKILL.md).
#   NBODY6PPGPU_EXPERT_TARBALL_URL   Testing only: override the tarball URL to download.
#
# Behavior: by default this installs to both Claude Code's ~/.claude/skills/nbody6ppgpu-expert
# and Codex's ${CODEX_HOME:-~/.codex}/skills/nbody6ppgpu-expert; if the target already exists it
# is removed first and then replaced with fresh content, leaving no leftovers. The installed
# content does not include install.sh, README.md, .gitignore, tests/, .git, or other files not
# needed to run the skill.

set -e

REPO_OWNER_SLASH_NAME="kaiwu-astro/nbody6ppgpu-expert"
SKILL_NAME="nbody6ppgpu-expert"
DEFAULT_TARBALL_URL="https://github.com/${REPO_OWNER_SLASH_NAME}/archive/refs/heads/main.tar.gz"

install_claude=0
install_codex=0

for arg in "$@"; do
    case "$arg" in
        --claude)
            install_claude=1
            ;;
        --codex)
            install_codex=1
            ;;
        --help|-h)
            echo "Usage: sh install.sh [--claude] [--codex]"
            echo "With no arguments, installs to both Claude Code and Codex by default."
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg (available: --claude, --codex)" >&2
            exit 1
            ;;
    esac
done

if [ "$install_claude" -eq 0 ] && [ "$install_codex" -eq 0 ]; then
    install_claude=1
    install_codex=1
fi

if [ "$install_claude" -eq 0 ] && [ "$install_codex" -eq 0 ]; then
    echo "Nothing to install, exiting." >&2
    exit 1
fi

# Prepare a temporary directory that cleans up after itself.
work_dir=$(mktemp -d 2>/dev/null || mktemp -d -t nbody6ppgpu-expert)
if [ -z "$work_dir" ] || [ ! -d "$work_dir" ]; then
    echo "Failed to create a temporary directory, aborting install." >&2
    exit 1
fi
cleanup() {
    rm -rf "$work_dir"
}
trap cleanup EXIT INT TERM

source_dir=""

if [ -n "${NBODY6PPGPU_EXPERT_SOURCE:-}" ]; then
    # Testing only: skip the download and use the local directory directly.
    if [ ! -f "${NBODY6PPGPU_EXPERT_SOURCE}/SKILL.md" ]; then
        echo "SKILL.md not found in the directory pointed to by NBODY6PPGPU_EXPERT_SOURCE: ${NBODY6PPGPU_EXPERT_SOURCE}" >&2
        exit 1
    fi
    source_dir="$NBODY6PPGPU_EXPERT_SOURCE"
else
    tarball_url="${NBODY6PPGPU_EXPERT_TARBALL_URL:-$DEFAULT_TARBALL_URL}"
    archive_path="${work_dir}/source.tar.gz"

    echo "Downloading nbody6ppgpu-expert source: ${tarball_url}"
    if command -v curl >/dev/null 2>&1; then
        if ! curl -fsSL "$tarball_url" -o "$archive_path"; then
            echo "Download failed (curl): ${tarball_url}" >&2
            exit 1
        fi
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -q -O "$archive_path" "$tarball_url"; then
            echo "Download failed (wget): ${tarball_url}" >&2
            exit 1
        fi
    else
        echo "Neither curl nor wget found, cannot download, aborting install. Install one of them and retry, or use the manual install instructions (see README)." >&2
        exit 1
    fi

    echo "Extracting..."
    extract_dir="${work_dir}/extracted"
    mkdir -p "$extract_dir"
    if ! tar -xzf "$archive_path" -C "$extract_dir"; then
        echo "Extraction failed: ${archive_path}" >&2
        exit 1
    fi

    # A GitHub archive extracts to a single top-level directory named <repo>-<branch>.
    top_level_dir=$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)
    if [ -z "$top_level_dir" ] || [ ! -f "${top_level_dir}/SKILL.md" ]; then
        echo "The extracted archive does not have the expected structure (SKILL.md not found)." >&2
        exit 1
    fi
    source_dir="$top_level_dir"
fi

# Install the skill into the target directory: clear out the old directory first, then copy
# only the files needed to run it.
# Excludes install.sh, README.md, .gitignore, tests/, .git, implementation-notes.html, and other
# non-essential files, but keeps SKILL.md, agents/, scripts/.
install_to() {
    target_dir="$1"
    label="$2"

    parent_dir=$(dirname "$target_dir")
    if ! mkdir -p "$parent_dir"; then
        echo "Failed to create target parent directory: ${parent_dir}, skipping ${label} install." >&2
        return 1
    fi

    rm -rf "$target_dir"
    mkdir -p "$target_dir"

    cp "${source_dir}/SKILL.md" "$target_dir/"
    if [ -d "${source_dir}/agents" ]; then
        cp -R "${source_dir}/agents" "$target_dir/"
    fi
    if [ -d "${source_dir}/scripts" ]; then
        cp -R "${source_dir}/scripts" "$target_dir/"
        # Clean up any Python bytecode cache that may have come along with the source
        # directory; it is not needed to run the skill.
        find "$target_dir" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
        find "$target_dir" -type f -name '*.pyc' -delete 2>/dev/null || true
    fi

    echo "Installed to ${label}: ${target_dir}"
    return 0
}

exit_code=0

if [ "$install_claude" -eq 1 ]; then
    claude_target="${HOME}/.claude/skills/${SKILL_NAME}"
    if ! install_to "$claude_target" "Claude Code"; then
        exit_code=1
    fi
fi

if [ "$install_codex" -eq 1 ]; then
    codex_home="${CODEX_HOME:-${HOME}/.codex}"
    codex_target="${codex_home}/skills/${SKILL_NAME}"
    if ! install_to "$codex_target" "Codex"; then
        exit_code=1
    fi
fi

if [ "$exit_code" -eq 0 ]; then
    echo "Install complete."
else
    echo "Errors occurred during install, check the output above." >&2
fi

exit "$exit_code"
