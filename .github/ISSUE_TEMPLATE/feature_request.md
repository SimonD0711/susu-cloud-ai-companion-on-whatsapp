name: Feature Request
description: Suggest a new feature or improvement
title: "[Feature] "
labels: ["enhancement"]
assignees: []
body:
  - type: markdown
    attributes:
      value: |
        ## Feature Description
        A clear and concise description of the feature or improvement you'd like to see.

  - type: textarea
    id: problem
    attributes:
      label: Problem or Use Case
      description: |
        Describe the problem you're trying to solve, or the use case this feature would enable.
        Why is this important to you?
    validations:
      required: true

  - type: textarea
    id: solution
    attributes:
      label: Proposed Solution
      description: Describe how you'd like this to work. Include any mockups, examples, or technical suggestions.
    validations:
      required: true

  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives Considered
      description: Have you considered any alternative approaches? What are the trade-offs?

  - type: textarea
    id: context
    attributes:
      label: Additional Context
      description: Any other context, screenshots, or references that might help.

  - type: checkboxes
    id: checklist
    attributes:
      label: Checklist
      options:
        - label: This is something I would use personally
        - label: This would benefit other users
        - label: I am willing to help implement this
