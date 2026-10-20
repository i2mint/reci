# reci.yaml_gen

YAML I/O wrapper using ruamel.yaml (YAML 1.2).

Handles the critical `on:` key (PyYAML treats it as boolean True),
wraps `${{ }}` expressions in SingleQuotedScalarString, and uses
LiteralScalarString for multiline `run:` blocks.

### Functions

| [`dump_workflow`](#reci.yaml_gen.dump_workflow)(workflow, \*[, stream])   | Serialize a workflow dict to GitHub Actions YAML.                 |
|------------------------------------------------------------------------------------------|-------------------------------------------------------------------|
| [`load_yaml`](#reci.yaml_gen.load_yaml)(path)                         | Load a YAML file and return a plain dict.                         |
| [`load_yaml_string`](#reci.yaml_gen.load_yaml_string)(text)                  | Load YAML from a string and return a plain dict.                  |
| [`scalar_source_text`](#reci.yaml_gen.scalar_source_text)(value)               | A YAML number as written in the source, not as Python renders it. |

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

### reci.yaml_gen.scalar_source_text(value)

A YAML number as written in the source, not as Python renders it.

ruamel keeps the spelling of what it loads, so `3.10` stays `3.10`
(`str()` gives `3.1`), `0x1F` stays `0x1F` and `1e3` stays `1e3`.
Anchors and tags are not part of the spelling.  When ruamel’s text would be
a different number (negative hex, underscored floats), `str()` is used.

```pycon
>>> scalar_source_text(load_yaml_string("v: 3.10")["v"])
'3.10'
>>> scalar_source_text(load_yaml_string("v: &a 0x1F")["v"])
'0x1F'
>>> scalar_source_text(7)
'7'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
