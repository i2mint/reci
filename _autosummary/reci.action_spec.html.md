# reci.action_spec

Action contract model — parsed from `action.yml` metadata.

An [`ActionSpec`](#reci.action_spec.ActionSpec) captures the typed input/output contract of a GitHub
Action so that downstream modules (graph, compiler, validation) can reason
about data flow without fetching YAML at every step.

### Functions

| [`action_local_name`](#reci.action_spec.action_local_name)(ref)                       | Extract the last path segment of an action ref, normalized.                                                        |
|-----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------|
| [`action_spec_from_declaration`](#reci.action_spec.action_spec_from_declaration)(ref, \*[, ...]) | Build an [`ActionSpec`](#reci.action_spec.ActionSpec) from inline recipe declarations.              |
| [`action_spec_from_ref`](#reci.action_spec.action_spec_from_ref)(ref)                    | Fetch action.yml from GitHub and return an [`ActionSpec`](#reci.action_spec.ActionSpec).            |
| [`fetch_action_yml`](#reci.action_spec.fetch_action_yml)(ref)                        | Fetch and parse an `action.yml` from GitHub.                                                                       |
| [`normalize_name`](#reci.action_spec.normalize_name)(name)                         | Canonical form: lowercase, hyphens/spaces → underscores.                                                           |
| [`parse_action_spec`](#reci.action_spec.parse_action_spec)(ref, \*, action_yml_data)  | Build an [`ActionSpec`](#reci.action_spec.ActionSpec) from a ref string and parsed action.yml data. |

### Classes

| [`ActionSpec`](#reci.action_spec.ActionSpec)(ref[, inputs, outputs])             | The typed contract of a single GitHub Action.                                                            |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------|
| [`InputSpec`](#reci.action_spec.InputSpec)(name[, required, default, ...])      | One declared input of a GitHub Action.                                                                   |
| [`OutputSpec`](#reci.action_spec.OutputSpec)(name[, description, original_name]) | One declared output of a GitHub Action (see [`InputSpec`](#reci.action_spec.InputSpec)). |

### Exceptions

| [`ActionFetchError`](#reci.action_spec.ActionFetchError)   | Raised when an action.yml cannot be retrieved.   |
|---------------------------------------------------------------------|--------------------------------------------------|

### *exception* reci.action_spec.ActionFetchError

Bases: [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception)

Raised when an action.yml cannot be retrieved.

### *class* reci.action_spec.ActionSpec(ref, inputs=<factory>, outputs=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The typed contract of a single GitHub Action.

*inputs* and *outputs* are keyed by **normalized** name.

### *class* reci.action_spec.InputSpec(name, required=False, default=None, description='', original_name='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One declared input of a GitHub Action.

*name* is normalized (used for matching); *original_name* is the spelling
in `action.yml` (used when emitting, since GitHub does not map `_` to
`-`).

#### *property* emitted_name *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The spelling to write into a workflow.

### *class* reci.action_spec.OutputSpec(name, description='', original_name='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One declared output of a GitHub Action (see [`InputSpec`](#reci.action_spec.InputSpec)).

#### *property* emitted_name *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The spelling to write into a workflow.

### reci.action_spec.action_local_name(ref)

Extract the last path segment of an action ref, normalized.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> action_local_name('i2mint/wads/actions/run-tests@master')
'run_tests'
>>> action_local_name('actions/checkout@v4')
'checkout'
```

### reci.action_spec.action_spec_from_declaration(ref, , inputs=None, outputs=None)

Build an [`ActionSpec`](#reci.action_spec.ActionSpec) from inline recipe declarations.

Used when the recipe manually annotates inputs/outputs for a `run:`
step or overrides the fetched metadata.

* **Return type:**
  [`ActionSpec`](#reci.action_spec.ActionSpec)

### reci.action_spec.action_spec_from_ref(ref)

Fetch action.yml from GitHub and return an [`ActionSpec`](#reci.action_spec.ActionSpec).

* **Return type:**
  [`ActionSpec`](#reci.action_spec.ActionSpec)

### reci.action_spec.fetch_action_yml(ref)

Fetch and parse an `action.yml` from GitHub.

Tries the raw URL first, then a fallback with `action.yaml`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### reci.action_spec.normalize_name(name)

Canonical form: lowercase, hyphens/spaces → underscores.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> normalize_name('python-version')
'python_version'
>>> normalize_name('Root Dir')
'root_dir'
```

### reci.action_spec.parse_action_spec(ref, , action_yml_data)

Build an [`ActionSpec`](#reci.action_spec.ActionSpec) from a ref string and parsed action.yml data.

* **Return type:**
  [`ActionSpec`](#reci.action_spec.ActionSpec)
