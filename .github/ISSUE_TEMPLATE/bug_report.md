name: Bug Report
description: Report something that is not working as expected
title: "[Bug] "
labels: ["bug"]
assignees: []
body:
  - type: markdown
    attributes:
      value: |
        ## Bug Description
        A clear and concise description of what the bug is.

  - type: textarea
    id: steps
    attributes:
      label: Steps to Reproduce
      description: How can we reproduce the issue? Be as specific as possible.
      placeholder: |
        1. Go to '...'
        2. Send a message '...'
        3. See error '...'
    validations:
      required: true

  - type: textarea
    id: expected
    attributes:
      label: Expected Behavior
      description: What did you expect to happen?
    validations:
      required: true

  - type: textarea
    id: actual
    attributes:
      label: Actual Behavior
      description: What actually happens instead?
    validations:
      required: true

  - type: dropdown
    id: version
    attributes:
      label: Version
      description: Which version of Susu Cloud are you using?
      options:
        - latest (main branch)
        - v2.1.0
        - v2.0.0
        - v1.0.0
        - older
    validations:
      required: true

  - type: textarea
    id: logs
    attributes:
      label: Relevant Log Output
      description: |
        Paste any relevant log output or error messages here.
        **Remove any sensitive information (API keys, phone numbers, personal data) before pasting.**
      placeholder: |
        [paste logs here]

  - type: textarea
    id: context
    attributes:
      label: Additional Context
      description: Any other context about the problem (screenshots, environment info, etc.)
