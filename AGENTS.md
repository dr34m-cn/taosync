# Project Context

Before exploring or changing this workspace, read `~/memory/projects/taosync.md` when it exists. It contains the stable architecture, synchronization flow, data model, frontend structure, and important safety semantics for TaoSync.

After a material architecture, persistence, API, or synchronization change, update that memory entry and the projects index. Do not store credentials, local runtime data, or temporary task state in project memory.

# Synchronization Principles

- **Speed-first comparison**: Compare file hashes only when hashes are already directly available without extra hashing or download/network overhead. Because computing or fetching file hashes on demand can take enormous time, falling back to simple file-size comparison (including when cached/patched entries do not carry hashes) is an intentional design choice, not a bug.
- **Target directory caching is an explicit user choice**: Target directories are typically unchanged outside sync, or any external edits (such as manually deleting files on the target) are deliberate; forcing a live target scan in those cases can undesirably re-sync files the user intentionally removed. When target directory caching is enabled, relying on that cache is an intentional user choice and must not be treated as a bug.

# Markdown Documentation

Before creating, modifying, or deleting a README file (including README.md and README_EN.md), obtain the user's explicit request or confirmation for that specific change in the current request. If a task appears to require a README change, list the proposed change and wait for confirmation first. Other Markdown files may be created, modified, or deleted as needed for the authorized task without additional confirmation.

README policy: the online README documents only features already present in the released version (see `version.txt` and the latest git tag). Features committed after the last release must not be described in the README until they ship.

README.md and README_EN.md are written for end users. Keep them concise and focused on useful product information. Screenshot sections should simply present the interface with short labels. Omit screenshot capture dates, demo-data provenance, viewport/image dimensions, pixel density, and redundant explanations of the image layout or how to click images.

Do not remove content merely because it is technical. Preserve technology-stack and build/release-process information, password-storage details, and comparable explanations users need to understand, configure, deploy, or safely use the product.

Always review and update README.md and README_EN.md together. Keep their user-facing content, examples, screenshots, and meaning synchronized in the same change.

# Release Changelogs

Write `doc/changelog/` entries from the perspective of a user upgrading from the previous released version. When extending an existing entry, review commits since its last edit and merge related changes into the existing items. Use the previous release, not the individual commit messages, to classify the result: describe a feature introduced in this release once in its final form under 特性, including any refinements made before release. Use 优化 for improvements to previously released behavior and 修复 only for defects present in the previous release.

Before finalizing a release changelog, perform a full check of `https://github.com/dr34m-cn/taosync/issues` (including open and closed issues, plus related PRs) to identify every issue associated with the release's changes.

Within each category, present every item as a collapsible `<details>` block: put a short summary of a few words inside `<summary><strong>...</strong></summary>`, and place any related issue/PR links directly after the summary text inside `<summary>` using HTML anchor tags (`<a href="https://github.com/dr34m-cn/taosync/issues/<id>">#<id></a>` / `<a href="https://github.com/dr34m-cn/taosync/pull/<id>">#<id></a>`, because Markdown links inside raw HTML `<summary>` lines are not parsed in GFM). Leave a blank line after `</summary>`, and place the detailed behavior and upgrade notes in normal paragraph text inside the collapsed body.

Include an uncollapsed download section (`## 📦 下载` / `## 📦 Downloads`) grouped concisely as one bullet line per platform with short, plain-language link labels separated by ` · ` (e.g. `- **Windows**：[64位（常见电脑）](https://github.com/dr34m-cn/taosync/releases/download/<version>/...) · [ARM64](...)`), rather than a verbose table. Cover every release asset published by `.github/workflows/build.yml` via direct GitHub Release hyperlinks (`https://github.com/dr34m-cn/taosync/releases/download/<version>/<filename>`), along with Docker image tags and the checksum file.

Write the complete Simplified Chinese changelog first, then append the complete English translation. Separate them with a single Markdown horizontal rule (`---`) and omit language headings. Keep the categories, item order, upgrade notes, issue links, and download links aligned across both languages. Exclude build-related changes, including CI, packaging workflows, and build matrices.

# Frontend Preferences

When adding or updating an engine with a directory selector, allow users to create and select a child directory in place, as in the job editor. Preserve read-only mount settings and never create directories at a synthetic engine root.

Prefer Element Plus components and theme styles for new or updated controls. For file uploads, use the Element Plus drag-and-drop picker with click-to-select support instead of a visible native file input.

Every new or changed feature must support all project locales (currently Simplified Chinese and English). Localize user-facing UI, accessibility labels, validation, notifications and backend messages in the same change. Keep locale keys and placeholders in sync. Store stable codes for new built-in log messages and translate them for the viewer; preserve user content and external diagnostics verbatim.

Numeric inputs must not show increment/decrement arrow controls. Use `:controls="false"` for Element Plus `el-input-number` components and hide native number input spinners when applicable.

# Backend Test Isolation

The source-mode CI failure occurred because per-file snapshot persistence added a new `jobMapper.checkpointSourceFile` call, but existing unit tests mocked only snapshot reads and final snapshot replacement. The unmocked call reached real configuration/database initialization in CI's empty working directory, failed on missing `data/secret.key`, recorded a failed operation, and prevented final snapshot replacement. The resulting snapshot-call assertion failures were secondary symptoms. Local verification had also covered only `test/`, omitting the separate `tests/` suite used by CI.

- When adding persistence, configuration, filesystem, network, or other external calls, review every affected unit-test fixture and mock each external entry point where the code under test looks it up. Mocking an older read or batch-write method does not isolate newly added calls. Scope patches to the test and restore them with cleanup.
- Unit tests must run without local runtime data, secrets, initialized databases, or state left by other tests. Do not create real `data/secret.key` or initialize production configuration to conceal a missing mock. Integration tests should explicitly provide temporary configuration and databases and clean them up.
- Assert the new behavior as well as mocking it: successful completion saves progress, incomplete multi-target delivery does not advance the file snapshot, and persistence failures are reported and prevent a successful full-snapshot commit. Keep real-database recovery coverage in integration tests.
- Verify both backend test directories using the CI runner, which runs in an empty temporary working directory and rejects leaked files. Run all three commands below after changes affecting shared backend behavior; running only one directory is insufficient. Check `.github/workflows/test.yml` for changes to the required commands.

```sh
python scripts/run-backend-tests.py test
python scripts/run-backend-tests.py tests
python scripts/run-backend-tests.py --shuffle-seed 42
```

# Code Summary Preferences

- When the user asks for a coding-work summary (including `总结`, `按code记忆格式要求总结`, `按code记忆要求的格式总结`, or asking how to summarize), follow the protocol below directly; do not read `~/code/memory.md`.
- Both lines must summarize only completed code changes since the most recent valid summary checkpoint in this conversation. If no valid checkpoint exists, summarize completed code changes from the beginning of the conversation. Do not repeat changes covered by an earlier checkpoint.
- Describe user-visible features and behavioral changes: what users can now do or what behavior changed. Omit file paths, function/class names, variables, code snippets, CSS properties, SQL, API parameters, and other implementation details unless the implementation detail itself is the point of the change.
- Return only one Markdown fenced code block with exactly two content lines, no blank line between them, and no text outside the code block.
- Line 1 is one short Chinese sentence summarizing the changes, without a category prefix.
- Line 2 lists the categorized changes using only these prefixes: `add 增加了`, `update 更新了`, `fix 修复了`, and `remove 移除了`. Join every item with ` && ` and do not insert line breaks within Line 2.
- Exclude acknowledgements, explanations, verification, tests, runtime status, memory or preference updates, environment details, and other non-code-change work.
- Each valid two-line summary becomes the new checkpoint for subsequent summaries; earlier valid checkpoints (including those created before format changes) remain valid.

