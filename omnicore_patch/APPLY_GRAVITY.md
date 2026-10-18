# GRAVITY — EXECUTE EXACTLY; DO NOT SIMULATE

Repo: `sagiarvil/ai`; target **new branch** based on `feature/gravity-p0-hardening`.

1. Copy `universal_installer.py` to repository root and `tests/test_universal_installer.py` to tests.
2. In `agentic_engine.py`, REPLACE ONLY the body of `AutonomousExecutionEngine.install_and_verify_repo` with:

```python
    def install_and_verify_repo(self, repo_url: str, test_command=None) -> dict:
        from universal_installer import install_repo
        if test_command is not None:
            return {'success': False, 'state': 'BLOCKED', 'error': 'Arbitrary test commands disallowed; use adapter acceptance policy'}
        return install_repo(repo_url)
```

3. In `omni_chat_panel.py`, change `tool_search_and_install_github_repo` success rendering. The installer returns `FUNCTIONAL_TESTED`, NOT an activated service. **Never say active or 100% PASS** before a service-specific activation adapter health-probes it.
4. Preserve Mistral-24B; do not install or switch models. Do not change API auth.
5. Fix the sandbox policy: the sandbox must explicitly permit writing the *staging tree* while refusing writes to protected project files; deny network by default, enable only for clone and dependency download. The host-side coordinator (not untrusted repo code) alone may promote an artifact outside the sandbox. **Never disable Seatbelt to make a test pass.** Validate macOS Seatbelt profiles with real denial tests on the target Mac. Linux CI must never claim Seatbelt worked.
6. Explicitly test the chosen Python unittest adapter on two real repos (one passing, one failing). Some projects use pytest instead: build project-specific adapters; never claim universal support based on this reference adapter.
7. The reference uses `npm test`, but project-specific runners and required lifecycle build steps differ; implement repository-specific adapters and verify them before accepting Node repos.
8. `npm ci --ignore-scripts` may mean native modules are incomplete. Detect that and return `UNVERIFIED`, not SUCCESS.
9. Add transactional registry concurrency test; restart/resume test; SIGKILL recovery; no-test repo test; platform-unsupported repo test; secret read denial test; network-denied test.
10. Run `python3 -m unittest discover -s tests -p 'test_universal_installer.py'` for static unit tests and run actual *macOS* integration tests. Record raw outputs, exit codes, task IDs, commit SHAs.
11. Do not merge until GitHub CI is green and local Mac acceptance passes. Provide commit and logs. No fake PASS.

**Safety:** The reference installer is a deliberately conservative baseline. It does not support arbitrary language ecosystems, all Python test layouts, remote branches or automatic live-service activation. It cannot guarantee arbitrary repositories will succeed. Do not describe `FUNCTIONAL_TESTED` as service `VERIFIED`.
