# reci.config

Config resolution — flat dict with scoped overrides.

Resolution order for input `root_dir` of action `run-tests`:

```default
1. ``run_tests__root_dir`` in config → scoped override wins
2. ``root_dir`` in config → shared default
3. ``default`` from action.yml → action default
4. If required and none found → validation error (FLOW001)
```

### Functions

| [`collect_required_config_keys`](#reci.config.collect_required_config_keys)(recipe, ...)         | Scan a recipe and return config keys needed by its actions.   |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------------|
| [`flatten_config`](#reci.config.flatten_config)(nested, \*[, prefix])              | Convert a nested dict to a flat dict with `__` separators.    |
| [`resolve_config_for_input`](#reci.config.resolve_config_for_input)(input_name, ref, config) | Find a config value for an action input.                      |

### reci.config.collect_required_config_keys(recipe, action_specs)

Scan a recipe and return config keys needed by its actions.

Returns `{key: required}` where *required* is True when the input
has `required=True` and no default.  Inputs given by an explicit
`with:` or fed by an upstream step output (`bind:` honoured) need no
config key.  Keys the recipe references as `${{ config.X }}` are required.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]

### reci.config.flatten_config(nested, , prefix='')

Convert a nested dict to a flat dict with `__` separators.

```pycon
>>> flatten_config({'testing': {'python_versions': ['3.10']}})
{'testing__python_versions': ['3.10']}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### reci.config.resolve_config_for_input(input_name, ref, config)

Find a config value for an action input.

Returns `(config_key, value)` or `None`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)
