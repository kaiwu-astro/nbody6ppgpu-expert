# nbody6ppgpu-expert: NBODY6++GPU Expert Skill

A source-and-manual lookup skill for NBODY6++GPU / NBODY6ppGPU / Nbody6PPGPU-beijing, for use with Claude Code and Codex. On every invocation it refreshes an independent copy of the official source tree and the latest manual (PDF plus a converted Markdown), then checks both the source and the manual together to give answers backed by file paths and line numbers or page numbers, instead of answering from memory.

## One-line install

Install to both Claude Code and Codex:

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

## Manual install (git clone)

```sh
git clone https://github.com/kaiwu-astro/nbody6ppgpu-expert.git /tmp/nbody6ppgpu-expert
mkdir -p ~/.claude/skills
rm -rf ~/.claude/skills/nbody6ppgpu-expert
cp -R /tmp/nbody6ppgpu-expert ~/.claude/skills/nbody6ppgpu-expert
# Same for Codex, but use ${CODEX_HOME:-~/.codex}/skills/nbody6ppgpu-expert as the target
```

## Updating

Just re-run the install command; the target directory is fully replaced with the latest version.

## Uninstalling

```sh
rm -rf ~/.claude/skills/nbody6ppgpu-expert
rm -rf "${CODEX_HOME:-$HOME/.codex}/skills/nbody6ppgpu-expert"
```

## Usage notes

When the skill is invoked, it first runs `scripts/update_resources.py`, which refreshes the source tree and the manual once per local calendar day (skipped if the same day's content already validates). It needs network access to fetch:

- Official source: `https://github.com/nbody6ppgpu/Nbody6PPGPU-beijing` (`dev` branch)
- Official manual PDF: `https://nbody6ppgpu.github.io/nb6-manual-pdf/latest.pdf`

The independent source copy, the manual, the state file, and (when `pdftotext` is missing) a private Python environment built on demand are all written under `${TMPDIR}/nbody6ppgpu-expert-<uid>/`; none of this touches the user's existing checkouts or `~/.cache/`. See `SKILL.md` for details and the full workflow.

## Running the tests

```sh
python3 -m unittest discover -s tests
```

## License

MIT License.
