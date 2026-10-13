# nbody6ppgpu-expert: NBODY6++GPU Expert Skill

A source-and-manual lookup skill for NBODY6++GPU / NBODY6ppGPU / Nbody6PPGPU-beijing, for use with Claude Code and Codex. On every invocation it refreshes an independent copy of the official source tree and the latest manual (PDF plus a converted Markdown), then checks both the source and the manual together to give answers backed by file paths and line numbers or page numbers, instead of answering from memory.

## Install (recommended): skills CLI

The skill follows the [Agent Skills specification](https://agentskills.io/specification) and lives in `skills/nbody6ppgpu-expert/` of this repo; only that folder is installed. Install it with the [`skills` CLI](https://github.com/vercel-labs/skills) (requires Node.js for `npx`):

```sh
npx skills add kaiwu-astro/nbody6ppgpu-expert
```

This is interactive: you choose the agents and the scope (project or global). To install globally to Claude Code and Codex without prompts:

```sh
npx skills add kaiwu-astro/nbody6ppgpu-expert -g -a claude-code codex -y
```

By default the CLI keeps one canonical copy and symlinks it into each agent's skills directory; pass `--copy` to copy instead. Observed install locations for a global install:

- Canonical copy: `~/.agents/skills/nbody6ppgpu-expert`
- Claude Code: `~/.claude/skills/nbody6ppgpu-expert` (symlink)
- Codex: reads `~/.agents/skills/nbody6ppgpu-expert` directly

Update and remove:

```sh
npx skills update nbody6ppgpu-expert -g
npx skills remove nbody6ppgpu-expert -g
```

## Alternative install: shell script (fallback)

For machines without Node.js. Install to both Claude Code and Codex:

```sh
curl -fsSL https://raw.githubusercontent.com/kaiwu-astro/nbody6ppgpu-expert/main/install.sh | sh
```

Install to Claude Code only:

```sh
curl -fsSL https://raw.githubusercontent.com/kaiwu-astro/nbody6ppgpu-expert/main/install.sh | sh -s -- --claude
```

Install to Codex only:

```sh
curl -fsSL https://raw.githubusercontent.com/kaiwu-astro/nbody6ppgpu-expert/main/install.sh | sh -s -- --codex
```

`install.sh` is a POSIX sh script. It prefers `curl` for downloading, falls back to `wget` if `curl` is unavailable, and exits with an error if neither is present. Default install locations:

- Claude Code: `~/.claude/skills/nbody6ppgpu-expert`
- Codex: `${CODEX_HOME:-~/.codex}/skills/nbody6ppgpu-expert`

If the target directory already exists, it is removed entirely before the new content is placed, so no stale files are left behind.

To update, re-run the install command. To uninstall:

```sh
rm -rf ~/.claude/skills/nbody6ppgpu-expert
rm -rf "${CODEX_HOME:-$HOME/.codex}/skills/nbody6ppgpu-expert"
```

> **Warning:** do not mix both methods for the same agent. `install.sh` writes Codex to `~/.codex/skills/`, while the skills CLI uses `~/.agents/skills/`, so mixing leaves duplicate copies for Codex. When switching from the script to npx, first run:
>
> ```sh
> rm -rf ~/.claude/skills/nbody6ppgpu-expert "${CODEX_HOME:-$HOME/.codex}/skills/nbody6ppgpu-expert"
> ```

## Manual install (git clone)

```sh
git clone https://github.com/kaiwu-astro/nbody6ppgpu-expert.git /tmp/nbody6ppgpu-expert
mkdir -p ~/.claude/skills
rm -rf ~/.claude/skills/nbody6ppgpu-expert
cp -R /tmp/nbody6ppgpu-expert/skills/nbody6ppgpu-expert ~/.claude/skills/nbody6ppgpu-expert
# Same for Codex, but use ${CODEX_HOME:-~/.codex}/skills/nbody6ppgpu-expert as the target
```

## Usage notes

When the skill is invoked, it first runs `scripts/update_resources.py` (in `skills/nbody6ppgpu-expert/`), which refreshes the source tree and the manual once per local calendar day (skipped if the same day's content already validates). It needs network access to fetch:

- Official source: `https://github.com/nbody6ppgpu/Nbody6PPGPU-beijing` (`dev` branch)
- Official manual PDF: `https://nbody6ppgpu.github.io/nb6-manual-pdf/latest.pdf`

The independent source copy, the manual, the state file, and (when `pdftotext` is missing) a private Python environment built on demand are all written under `${TMPDIR}/nbody6ppgpu-expert-<uid>/`; none of this touches the user's existing checkouts or `~/.cache/`. See `skills/nbody6ppgpu-expert/SKILL.md` for details and the full workflow.

## Running the tests

```sh
python3 -m unittest discover -s tests
```

## License

MIT License, see [LICENSE](LICENSE).
