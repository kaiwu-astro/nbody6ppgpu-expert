---
name: nbody6ppgpu-expert
description: Source-and-manual lookup workflow for NBODY6++GPU / NBODY6ppGPU / Nbody6PPGPU-beijing. Use when the user asks about internal mechanisms, documented behavior, output formats, control parameters, data fields, common blocks, or Fortran routines, or when an analysis script needs source code and manual evidence.
---

# NBODY6++GPU Expert Lookup

Answer questions that need precise evidence by checking both the NBODY6++GPU source tree and the accompanying manual at the same time, while keeping the main conversation context lean.

## Daily resource refresh

When invoked, the agent must run the unified update script; do not check paths, update times, branches, or download links yourself. If you are working inside Codex, make sure to bypass the sandbox when running it, otherwise it will fail with a DNS error.

```bash
python3 scripts/update_resources.py --print-resources
```

The script refreshes the source tree and the manual separately once per local calendar day (skipped once the same day's content has already validated), and can convert the manual PDF to Markdown on any machine, including environments without sudo that only allow user-level installs: when `pdftotext` is missing it automatically prepares a user-level Python environment, with no sudo or system package manager required. The independent source copy, the manual, the state file, and the private Python environment are all written under `${TMPDIR}/nbody6ppgpu-expert-<uid>/`. Codex's `workspace-write` sandbox can write to that directory directly; do not request `--add-dir`, Full Access, or any other write permission outside the workspace.

If you need the cache to persist outside Codex, run explicitly with `--cache-root <absolute-path>`. The script rejects relative paths and any path inside the skill or its host Git working tree. The old `~/.cache/nbody6ppgpu-expert/` is never read, migrated, or deleted.

The source path is only written into the resource manifest when it points at the official `origin`, the `dev` branch, a clean working tree, and `HEAD == origin/dev`. The script always uses the independent copy in the runtime cache and never reads, switches, resets, or updates the user's own checkout.

When network access is restricted, only the script's built-in official source URL `https://github.com/nbody6ppgpu/Nbody6PPGPU-beijing` and official manual URL `https://nbody6ppgpu.github.io/nb6-manual-pdf/latest.pdf` may be auto-approved for requests; do not use this to broaden filesystem permissions.

Only parse the script's stdout JSON and use the resources pointed to by `cache_root`, `repository`, `manual_markdown`, and `manual_pdf` when this run's exit code is 0. If the script fails, stop; do not fall back to an old manifest, a default path, a stale cached path, old assets bundled in the skill, or another checkout. The error message will state the specific reason.

## Manual resources

- `manual_markdown` and `manual_pdf` in the resource manifest are the NBODY6++GPU manual validated in this run. Prefer the Markdown for quick searches, and cite the actual path and line number from the manifest.
- The `pypdf` fallback extraction generally preserves layout worse than `pdftotext -layout`. Text conversion can scramble tables, equations, columns, indentation, or page breaks; when such formatting or semantic ambiguity arises, you must check the PDF and treat it as authoritative, citing the path and page number.
- Every request must check both the source tree and the relevant manual content.
- The source code reflects runtime behavior; the manual documents the intended interface and behavior. When they disagree, state this explicitly rather than picking one side on your own.

## Repository source

- Only use the `repository` path printed by this run's successful daily update script as the actual source path; never save or guess a repository path.
- Treat the repository as read-only during analysis; do not edit source files unless the user explicitly asks you to modify that codebase.

## Workflow

1. Break the user's request into one or more explicit source-and-manual questions.
2. Run the update script once in the main context and parse the resource manifest; use only the three paths from this run's manifest afterward.
3. Delegate investigation to a subagent whenever one is available. When the question splits naturally, assign source and manual checks to separate subagents.
4. Give each subagent only its precise question, the relevant absolute paths from this run's manifest, and a requirement to return evidence-backed conclusions; do not let multiple subagents re-run the update script.
5. Look for corresponding evidence in the manifest's repository and Markdown manual; if the converted text has formatting or semantic ambiguity, check the PDF from the manifest and treat it as authoritative. All follow-up checks are read-only.
6. Require the subagent to return:
   - A direct answer up front;
   - Paths and line numbers (Markdown) or page numbers (PDF) for the source or manual assets used;
   - Relevant symbols, parameter flags, field names, output files, or routines;
   - Any uncertainty or version assumptions.
7. Synthesize the results for the user; the main answer must be grounded in the cited source files and manual line numbers.

If no subagent tool is available, carry out the same investigation in the main context with narrowly scoped searches, and note that the subagent path was unavailable.

## Search guidance

- Start with precise `rg` searches for symbols, filenames, output labels, namelist/control parameter names, and common block names.
- First search the manifest's `manual_markdown` path for the same terms and nearby headings; when the text has formatting or semantic ambiguity, check the `manual_pdf` path and treat it as authoritative. Cite manual evidence separately from source evidence.
- If a broad search produces too much output, use `rg` only to locate candidate files, then inspect shorter line ranges.
- Prefer answers backed by source evidence over memory or general knowledge.
- When asked about output formats, locate both where the quantity is stored in memory and where it is written to disk.
- When both diagnostic output and structured output exist, distinguish them clearly.

## Subagent prompt template

Use a prompt like the following:

```text
Answer the following NBODY6++GPU question:

<question>

Inspect only the following resources, already validated in this run, in read-only mode; do not run the update script and do not use any other path:
- Source: <repository>
- Markdown manual: <manual_markdown>
- PDF manual: <manual_pdf>

The Markdown is for quick searches. If the converted text has formatting or semantic ambiguity, check the PDF and treat it as authoritative. Return a direct answer, list source and manual file/line-number or page-number evidence separately, note any relevant symbols or parameter flags, and state any uncertainty.
```
