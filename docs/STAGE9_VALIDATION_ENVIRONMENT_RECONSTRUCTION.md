# Stage 9: Validation environment reconstruction

v39 tightens QA and Reviewer validation for repositories that are not fully self-contained.

Some projects cannot be built from the plugin/module checkout alone. Their README, CI workflow, or build scripts may require an upstream source repository, sibling checkout layout, generated sources, Xvfb/GUI runtime, gRPC server, or other external runtime/service setup. In v39 these are treated as validation setup tasks, not excuses to downgrade to syntax-only validation.

## QA contract

QA must attempt to reconstruct the documented build/test environment when safe:

- install missing OS/package/project tools;
- clone or prepare upstream/source/sibling repositories when the docs or CI require them;
- prepare submodules/generated sources/documented layout;
- start or wrap required runtime services such as Xvfb/GUI/gRPC when practical;
- run at least one credible build command and one targeted test/smoke/integration command.

QA may return `ACTION: PASS` only with a validation object like:

```json
{
  "validation": {
    "build_ran": true,
    "build_passed": true,
    "tests_run": true,
    "tests_passed": true,
    "validation_level": "ci_like",
    "install_commands": [],
    "setup_commands": [],
    "build_commands": [],
    "test_commands": [],
    "validation_gaps": []
  }
}
```

Allowed `validation_level` values are:

- `ci_like`
- `targeted_runtime`
- `targeted_integration`
- `targeted_unit`
- `syntax_only`
- `not_validated`

`syntax_only` and `not_validated` cannot unlock Reviewer or Publisher for CI/build/runtime tasks.

## Reviewer contract

Reviewer must not accept a QA PASS that is backed only by syntax-level checks or by a statement such as “the core project is not present.” Reviewer must independently inspect QA evidence and return a `validation_review` object:

```json
{
  "validation_review": {
    "qa_build_evidence_ok": true,
    "qa_test_evidence_ok": true,
    "qa_validation_level_ok": true,
    "environment_reconstruction_reviewed": true,
    "syntax_only_rejected": true,
    "lint_commands": [],
    "setup_commands_reviewed": [],
    "validation_gaps": []
  }
}
```

Publisher is blocked unless QA has build/test/environment evidence and Reviewer has validation review evidence.
