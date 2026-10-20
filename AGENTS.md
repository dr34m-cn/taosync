# Project Context

Before exploring or changing this workspace, read `~/memory/projects/taosync.md` when it exists. It contains the stable architecture, synchronization flow, data model, frontend structure, and important safety semantics for TaoSync.

After a material architecture, persistence, API, or synchronization change, update that memory entry and the projects index. Do not store credentials, local runtime data, or temporary task state in project memory.

# Markdown Documentation

Never create, modify, or delete Markdown files (README, `docs/`, or any other `*.md`) unless the user explicitly asks for or confirms that specific Markdown change in the current request. If a task appears to require editing a Markdown file, list the proposed change and wait for the user's confirmation first.

README policy: the online README documents only features already present in the released version (see `version.txt` and the latest git tag). Features committed after the last release must not be described in the README until they ship.

