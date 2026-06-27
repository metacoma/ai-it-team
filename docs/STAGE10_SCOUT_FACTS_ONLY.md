# Stage 10: Scout facts-only context discovery

The Scout role is intentionally not a diagnostic role.

Scout must collect and organize context without proposing root-cause hypotheses. This prevents a weak early guess from being treated as a proven diagnosis by Team Lead, Architect, Coder, QA, or Reviewer.

Scout may report:

- exact CI/log evidence
- failing job, step, command, test name, and error text
- relevant files and why they are relevant
- repository/workspace facts
- documented build/test/validation commands for later roles
- research domains for the Research role
- risks, unknowns, missing information, and validation questions

Scout must not report:

- `root cause`
- `likely root cause`
- `candidate root cause`
- `hypothesis`
- ranked causes
- diagnostic conclusions not directly proven by logs/source/config/docs

Root-cause reasoning belongs to later roles after Scout supplies factual context:

```text
Scout      = facts/context/evidence/unknowns
Research   = external constraints and best practices
Senior     = execution contract and assumption ledger
Architect  = plan and diagnostic strategy
Coder      = implementation and local validation
QA         = CI-like/runtime validation
Reviewer   = independent review and evidence gate
```

Team Lead must therefore assign Scout with instructions such as:

```text
Collect factual CI/log/repository context only. Do not propose root-cause hypotheses.
Report exact failure evidence, relevant files, documented validation commands, research domains, unknowns, and validation questions.
```
