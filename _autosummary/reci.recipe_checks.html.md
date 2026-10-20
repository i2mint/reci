# reci.recipe_checks

Whole-recipe checks that need the recipe text and the config, not the step graph.

Shared by the compiler (which refuses to emit a workflow with these problems)
and the validation rules (which report them), so both always agree.

### Module Attributes

| [`SETUP_JOB_ID`](#reci.recipe_checks.SETUP_JOB_ID)   | The generated job that exports config values; recipe jobs may not use the id when config is supplied.   |
|-----------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|

### Functions

| [`as_expression`](#reci.recipe_checks.as_expression)(text)                    | An `if:` value as a `${{ }}` expression: GitHub evaluates it either way.             |
|-----------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`bool_config_conditions`](#reci.recipe_checks.bool_config_conditions)(recipe, config) | `(location, key)` for each `if:` that is just a boolean config value.                |
| [`config_names`](#reci.recipe_checks.config_names)(text)                     | The config keys referenced in *text*'s <br/><br/>```<br/>``<br/>```<br/><br/>${{ .   |
| [`config_references`](#reci.recipe_checks.config_references)(recipe)              | `(location, key, needs_context_available)` for each `${{ config.key }}`.             |
| [`expression_texts`](#reci.recipe_checks.expression_texts)(text)                 | The body of each `${{ }}` in *text*, string literals blanked.                        |
| [`find_recipe_problems`](#reci.recipe_checks.find_recipe_problems)(recipe, config)   | Problems that would make the compiled workflow invalid.                              |
| [`outside_expressions`](#reci.recipe_checks.outside_expressions)(text)              | *text* with every `${{ }}` expression removed.                                       |
| [`serialize_config_value`](#reci.recipe_checks.serialize_config_value)(value)          | A config value as the text of a `$GITHUB_OUTPUT` entry.                              |
| [`sub_config_refs`](#reci.recipe_checks.sub_config_refs)(text, repl)            | Substitute every `config.<key>` inside a <br/><br/>```<br/>``<br/>```<br/><br/>${{ . |
| [`unsupported_config_refs`](#reci.recipe_checks.unsupported_config_refs)(text)          | The uses of the `config` context in *text* that reci cannot rewrite.                 |

### Classes

| [`RecipeProblem`](#reci.recipe_checks.RecipeProblem)(rule_id, message[, location])   | One problem found by [`find_recipe_problems()`](#reci.recipe_checks.find_recipe_problems).   |
|------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|

### *class* reci.recipe_checks.RecipeProblem(rule_id, message, location=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One problem found by [`find_recipe_problems()`](#reci.recipe_checks.find_recipe_problems).

### reci.recipe_checks.SETUP_JOB_ID *= 'setup'*

The generated job that exports config values; recipe jobs may not use the id
when config is supplied.

### reci.recipe_checks.as_expression(text)

An `if:` value as a `${{ }}` expression: GitHub evaluates it either way.

```pycon
>>> as_expression("config.flag"), as_expression("${{ config.flag }}")
('${{ config.flag }}', '${{ config.flag }}')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### reci.recipe_checks.bool_config_conditions(recipe, config)

`(location, key)` for each `if:` that is just a boolean config value.

Config values reach the workflow as *strings*, so `if: config.flag` is true for
`'false'` too; compare it: `config.flag == 'true'`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### reci.recipe_checks.config_names(text)

The config keys referenced in *text*’s `${{ ... }}` expressions, in order.

```pycon
>>> config_names("${{ config.a }} ${{ !config.b && 'config.c' }} config.d")
['a', 'b']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### reci.recipe_checks.config_references(recipe)

`(location, key, needs_context_available)` for each `${{ config.key }}`.

Duplicates within one location are reported once.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]]

### reci.recipe_checks.expression_texts(text)

The body of each `${{ }}` in *text*, string literals blanked.

A literal survives only as the index of a bracket access on the `steps` or
`needs` context (`steps['p']`), so a name inside a message or comparison
(`'steps.p.outputs.v'`), or indexing something else, is never taken for a reference.

```pycon
>>> list(expression_texts("${{ steps['p'].outputs.v == 'steps.q.outputs.w' }} x"))
[" steps['p'].outputs.v == '' "]
>>> list(expression_texts("${{ fromJSON(env.M)['steps.p.outputs.v'] }}"))
[" fromJSON(env.M)[''] "]
```

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### reci.recipe_checks.find_recipe_problems(recipe, config)

Problems that would make the compiled workflow invalid.

* `CONF004` — `${{ config.X }}` where `X` is not a config key (the
  rewritten `needs.setup.outputs.X` would be empty or the setup job absent),
  or that sits where the `needs` context is unavailable.
* `DAG006` — `needs:` naming a job that does not exist (`setup` exists
  only when config is supplied).
* `CONF005` — a config key that is not a valid output id, or a string value
  holding characters the setup job cannot export unchanged.
* `DAG007` — a recipe job named `setup` while config is supplied: it
  would replace the generated setup job.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`RecipeProblem`](#reci.recipe_checks.RecipeProblem)]

### reci.recipe_checks.outside_expressions(text)

*text* with every `${{ }}` expression removed.

```pycon
>>> outside_expressions("config.flag && ${{ x }}").strip()
'config.flag &&'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### reci.recipe_checks.serialize_config_value(value)

A config value as the text of a `$GITHUB_OUTPUT` entry.

Lists, mappings and tuples become JSON (dates inside them as ISO text); a
boolean `true` / `false`; a number as the author wrote it (a TOML or
YAML `3.10` stays `3.10`, not `3.1`).  `None`, bytes and other
objects have no faithful text and raise [`TypeError`](https://docs.python.org/3/builtins/exceptions.html#TypeError).

```pycon
>>> serialize_config_value({"d": datetime.date(2024, 1, 2), "t": (1, 2)})
'{"d": "2024-01-02", "t": [1, 2]}'
>>> serialize_config_value(datetime.datetime(2024, 1, 2, 3, 4, 5))
'2024-01-02T03:04:05'
>>> serialize_config_value(True), serialize_config_value(7)
('true', '7')
>>> serialize_config_value(None)
Traceback (most recent call last):
...
TypeError: None (null) has no text form; give the key a value or remove it
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### reci.recipe_checks.sub_config_refs(text, repl)

Substitute every `config.<key>` inside a `${{ ... }}` in *text*.

*repl* receives the match (`group(1)` is the key).  Only expression code is
touched, never string literals inside an expression (`'config.json'`) and
never text outside `${{ }}` (`cat config.json`).  An expression that
changes is re-emitted as `${{ <code> }}`; the others are left verbatim.

```pycon
>>> sub_config_refs("${{ fromJson(config.v) }} cat config.json",
...                 lambda m: "NEEDS." + m.group(1))
'${{ fromJson(NEEDS.v) }} cat config.json'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### reci.recipe_checks.unsupported_config_refs(text)

The uses of the `config` context in *text* that reci cannot rewrite.

Only `config.<key>` maps to a setup-job output.  Nested access
(`config.x.y`), bracket access (`config['x']`) and the whole context
(`toJSON(config)`, `config.*`) have no counterpart, and would reach
GitHub unrewritten, where `config` is no context.

```pycon
>>> unsupported_config_refs("${{ config.a }} ${{ config.b.c }} ${{ config['d'] }}")
['config.b.c', 'config[']
>>> unsupported_config_refs("${{ toJSON(config) }} ${{ 'config' }} ${{ config.a }}")
['config']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
