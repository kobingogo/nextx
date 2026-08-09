# Security policy

Do not include exploitable details, credentials, cookies, or private Vault material in a public issue. Use a private GitHub security advisory for [kobingogo/nextx](https://github.com/kobingogo/nextx/security/advisories/new). If private advisories are unavailable, open a minimal public issue requesting a secure contact channel without reproducer details.

Report vulnerabilities in the NextX CLI, installer, canonical Skill, schemas, or repository-controlled launchd example. Especially relevant are arbitrary file writes outside the selected Vault, unsafe execution of Collector content, publication without the confirmation gate, and secrets accidentally written to project files.

`twitter-cli`, X, Grok Build, Codex, Claude Code, local operating-system configuration, and user-provided Skill content are external dependencies. Report their upstream vulnerabilities upstream as well; include the integration impact here only when NextX contributes a reproducible vulnerability.

This volunteer project has no response-time guarantee. Maintainers will validate reports, coordinate a fix when warranted, and credit reporters who wish to be credited. Never send real X session cookies, OAuth tokens, or an entire personal Obsidian Vault.
