# Security policy

Report vulnerabilities privately using [GitHub private vulnerability reporting](https://github.com/astgln/codex-workspace/security/advisories/new).
Do not open a public issue with exploit details, keys, session cookies, recovery
material, private conversations or logs containing user data. Include the affected
commit, branch, impact and a minimal reproduction using synthetic data.

If the private report form is unavailable, do not post the vulnerability publicly.
Open an issue asking the maintainer to enable a private reporting channel, without
technical details. Private reporting must be enabled when this repository is made public.

Fixes target current `main`. Experimental branches have no stability guarantee.
There is no guaranteed response time or paid security support. This project has
not received an independent security audit. See [the threat model](docs/security.md)
and [E2EE limitations](docs/e2ee.md), especially the trust placed in delivered
JavaScript and the local execution endpoint.
