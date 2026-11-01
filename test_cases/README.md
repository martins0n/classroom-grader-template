# Test cases

Each assignment gets a directory named after its **sanitized Classroom title**:

```
test_cases/
├── homework-1-variables/
│   ├── expected_output.json
│   └── requirements.txt      (optional)
└── lab-2-functions/
    └── expected_output.json
```

The title is lowercased, every run of other characters becomes one hyphen, and the result is cut
to 50 characters: `Homework 1 - Variables` becomes `homework-1-variables`.

**Use Latin letters in Classroom titles.** Other characters are dropped, so `Домашка 1` and
`Лабораторная 1` would both become `1` and share a branch. A title with no Latin letters or digits
at all falls back to the numeric coursework id. The branch name also shows the result:
`student-<id>/assignment-<name>`.

## How a notebook is graded

The notebook runs from top to bottom in the sandbox. Every output that parses as JSON, a
`print(json.dumps(...))` for example, is collected in order and compared with `expected_output.json`
by position. Everything one cell prints counts as a single output, so print one JSON document per
cell. An exception in any cell means a score of 0, and the student is told the error type and
the cell number.

Notebooks run with the submitted attachments in the working directory. They have no access to this
directory. Network access is on, so they can download datasets.

## `expected_output.json`

### Points per test case

```json
{
  "test_cases": [
    {
      "name": "Basic arithmetic",
      "points": 10,
      "expected": { "sum": 15, "product": 50 }
    },
    {
      "name": "Model quality",
      "points": 20,
      "tolerance": 0.01,
      "expected": { "f1": 0.8, "mae": 12.5 },
      "compare_fields": { "f1": ">=", "mae": "<=" },
      "tolerance_fields": { "mae": 0.05 }
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `name` | Shown to the student. |
| `points` | Points for this case. With `compare` or `compare_fields`, a partly correct object earns partial credit. |
| `expected` | Expected value, object or list. |
| `tolerance` | Relative tolerance for numbers: `0.01` is 1%. |
| `compare` | Operator for a single value: `==`, `!=`, `<`, `<=`, `>`, `>=`. |
| `compare_fields` | Operator per field of an object. |
| `tolerance_fields` | Tolerance per field of an object. |

### Plain list

A list is compared item by item and the score is the percentage of matches:

```json
[{ "sum": 15, "product": 50 }, { "result": "Hello, World!", "length": 13 }]
```

## `requirements.txt`

**Pin every version**, such as `pyarrow==22.0.0`. An unpinned package installs whatever is newest on
the day the cache is rebuilt, and that can break later. A new `pyarrow` that needs NumPy 2 next to a
library that pins NumPy 1 fails every student with an `ImportError`, while pip reports no conflict.

Packages for this assignment, installed into the sandbox on top of `sandbox/requirements.txt`. They
are cached, and pushing a change to this file builds the new set ahead of time. Everything should be
listed here: `!pip install` in a notebook also works, but it costs time on every run.

The sandbox image is `python:3.11-bookworm`. If a package needs system libraries the image lacks,
point `sandbox/image.txt` at another image.

## After changing test cases

Grading always uses the test cases from `main`, so a change applies to new submissions straight
away. To apply it to work already submitted, run the **Regrade All** workflow.
