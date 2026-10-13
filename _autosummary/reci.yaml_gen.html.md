# reci.yaml_gen

YAML I/O wrapper using ruamel.yaml (YAML 1.2).

Handles the critical `on:` key (PyYAML treats it as boolean True),
wraps `${{ }}` expressions in SingleQuotedScalarString, and uses
LiteralScalarString for multiline `run:` blocks.

### Functions

| [`dump_workflow`](#reci.yaml_gen.dump_workflow)(workflow, \*[, stream])   | Serialize a workflow dict to GitHub Actions YAML.   |
|------------------------------------------------------------------------------------------|-----------------------------------------------------|
| [`load_yaml`](#reci.yaml_gen.load_yaml)(path)                         | Load a YAML file and return a plain dict.           |
| [`load_yaml_string`](#reci.yaml_gen.load_yaml_string)(text)                  | Load YAML from a string and return a plain dict.    |

### reci.yaml_gen.dump_workflow(workflow, , stream=None)

Serialize a workflow dict to GitHub Actions YAML.

If *stream* is `None`, returns the YAML string.  Otherwise writes to
*stream* and returns `None`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### reci.yaml_gen.load_yaml(path)

Load a YAML file and return a plain dict.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### reci.yaml_gen.load_yaml_string(text)

Load YAML from a string and return a plain dict.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
