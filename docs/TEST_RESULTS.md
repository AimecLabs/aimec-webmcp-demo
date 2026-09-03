# Public export validation — September 3, 2026

Executed against this export before packaging:

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -s framework/tests -p 'test_*.py' -v` | 3 passed; model responses mocked |
| `python3 -m unittest discover -s tests -p 'test_*.py' -v` | 7 passed |
| `node --check framework/services/operator_ui/public/demo.js` | Passed |
| `node --check framework/services/operator_ui/public/webmcp.js` | Passed |
| `node --check docs/webmcp-check.js` | Passed |
| `bash -n scripts/demo.sh` | Passed |

Packaging tests cover the runtime allowlist, Docker COPY inputs, JSON inputs,
license presence, removal of the obsolete SEO verifier, hostname validation,
exact-commit HTTPS preparation, dirty-tree rejection and exclusion of untracked files.
Release tests use a disposable local Git repository and do not start Docker.

The archive excludes Git history, caches, runtime databases, model weights,
credentials and server-specific deployment scripts. No production deployment
was changed to prepare it.

Docker is unavailable in the packaging environment. A fresh container build and
real-model inference run of this export were **not** performed here. Prior
owner-performed live checks are described separately in `../PROVENANCE.md`.
