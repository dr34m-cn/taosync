# Project Context

Before exploring or changing this workspace, read `~/memory/projects/taosync.md` when it exists. It contains the stable architecture, synchronization flow, data model, frontend structure, and important safety semantics for TaoSync.

After a material architecture, persistence, API, or synchronization change, update that memory entry and the projects index. Do not store credentials, local runtime data, or temporary task state in project memory.

# Markdown Documentation

Before creating, modifying, or deleting a README file (including README.md and README_EN.md), obtain the user's explicit request or confirmation for that specific change in the current request. If a task appears to require a README change, list the proposed change and wait for confirmation first. Other Markdown files may be created, modified, or deleted as needed for the authorized task without additional confirmation.

README policy: the online README documents only features already present in the released version (see `version.txt` and the latest git tag). Features committed after the last release must not be described in the README until they ship.

README.md and README_EN.md are written for end users. Keep them concise and focused on useful product information. Screenshot sections should simply present the interface with short labels. Omit screenshot capture dates, demo-data provenance, viewport/image dimensions, pixel density, and redundant explanations of the image layout or how to click images.

Do not remove content merely because it is technical. Preserve technology-stack and build/release-process information, password-storage details, and comparable explanations users need to understand, configure, deploy, or safely use the product.

Always review and update README.md and README_EN.md together. Keep their user-facing content, examples, screenshots, and meaning synchronized in the same change.

# Frontend Preferences

Numeric inputs must not show increment/decrement arrow controls. Use `:controls="false"` for Element Plus `el-input-number` components and hide native number input spinners when applicable.

# Code Summary Preferences

- When the user asks for a coding-work summary, including `总结`, `按code记忆格式要求总结`, `按code记忆要求的格式总结`, or asks how to summarize, first read `~/code/memory.md` again and follow its current summary protocol. Do not rely on an earlier reading or recollection.
- Summarize only completed code changes since the most recent valid summary checkpoint in this conversation. If no valid checkpoint exists, summarize completed code changes from the beginning of the conversation. Do not repeat changes covered by an earlier checkpoint.
- Describe implemented features and behavioral changes: what users can now do or what behavior changed. Omit file paths, function/class names, variables, code snippets, CSS properties, SQL, API parameters, and other implementation details unless they are the point of the change.
- Use exactly these category prefixes: `add 增加了`, `update 更新了`, `fix 修复了`, and `remove 移除了`.
- Return only a Markdown fenced code block containing one changelog line. Join every item with ` && `; do not insert line breaks within the changelog.
- Exclude acknowledgements, explanations, verification, tests, runtime status, memory or preference updates, environment details, and other non-code-change work. Do not include any text outside the code block.
- Treat each valid single-line changelog response as the new summary checkpoint for subsequent summaries.

