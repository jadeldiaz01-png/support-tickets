# Branch governance contract

This file is a desired-state contract only. It does not apply repository settings.

Target branch: main.

Required controls before production promotion:

- pull request required;
- at least one required human review;
- required status checks:
  - runtime-container-ci / runtime-container
  - runtime-container-ci / foundation
  - runtime-container-ci / api-container
- conversation resolution required;
- force pushes denied;
- branch deletion denied;
- CODEOWNERS reflects the repository owner;
- merge must target an exact reviewed head SHA.

Current observed main protection at the start of this increment: disabled.

Applying a GitHub ruleset is an administrative external side effect and therefore
requires a separate human gate after this contract and its CI are reviewed.
