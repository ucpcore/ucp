# UCP GitHub Action (P1)

Copy [`ucp-digest.yml`](ucp-digest.yml) into `.github/workflows/` in your repository.

## Usage

Comment on any issue:

```text
/ucp digest
```

The workflow generates a UCP package with `ucp-gen`, renders a token-budgeted
markdown digest, and posts it as a comment with a link to [ucpcore.org/try](https://ucpcore.org/try).

## Requirements

- Public repository, or `GITHUB_TOKEN` with `issues: write`
- Python packages installed in the workflow: `ucp-gen`, `pyucp`

## Roadmap

- Auto-trigger when comment count exceeds N (opt-in label)
- Collapsible comment sections for `must_know` / `conflicts`
- Conformance badge in comment footer
