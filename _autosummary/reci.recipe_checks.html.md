# reci.recipe_checks

Whole-recipe checks that need the recipe text and the config, not the step graph.

Shared by the compiler (which refuses to emit a workflow with these problems)
and the validation rules (which report them), so both always agree.

### Module Attributes

| [`SETUP_JOB_ID`](#reci.recipe_checks.SETUP_JOB_ID)   | The generated job that exports config values; recipe jobs may not use the id when config is supplied.   |
|-----------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|

### Functions

| [`config_names`](#reci.recipe_checks.config_names)(text)                   | The config keys referenced in *text*'s <br/><br/>```<br/>``<br/>```<br/><br/>${{ .   |
|---------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`config_references`](#reci.recipe_checks.config_references)(recipe)            | `(location, key, needs_context_available)` for each `${{ config.key }}`.             |
| [`find_recipe_problems`](#reci.recipe_checks.find_recipe_problems)(recipe, config) | Problems that would make the compiled workflow invalid.                              |
| [`sub_config_refs`](#reci.recipe_checks.sub_config_refs)(text, repl)          | Substitute every `config.<key>` inside a <br/><br/>```<br/>``<br/>```<br/><br/>${{ . |

### Classes

| [`RecipeProblem`](#reci.recipe_checks.RecipeProblem)(rule_id, message[, location])   | One problem found by [`find_recipe_problems()`](#reci.recipe_checks.find_recipe_problems).   |
|------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|

### *class* reci.recipe_checks.RecipeProblem(rule_id, message, location=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One problem found by [`find_recipe_problems()`](#reci.recipe_checks.find_recipe_problems).

### reci.recipe_checks.SETUP_JOB_ID *= 'setup'*

The generated job that exports config values; recipe jobs may not use the id
when config is supplied.

### reci.recipe_checks.config_names(text)

The config keys referenced in *text*’s `${{ ... }}` expressions, in order.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> config_names("${{ config.a }} ${{ !config.b && 'config.c' }} config.d")
['a', 'b']
```

### reci.recipe_checks.config_references(recipe)

`(location, key, needs_context_available)` for each `${{ config.key }}`.

Duplicates within one location are reported once.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]]

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

### reci.recipe_checks.sub_config_refs(text, repl)

Substitute every `config.<key>` inside a `${{ ... }}` in *text*.

*repl* receives the match (`group(1)` is the key).  Only expression code is
touched, never string literals inside an expression (`'config.json'`) and
never text outside `${{ }}` (`cat config.json`).  An expression that
changes is re-emitted as `${{ <code> }}`; the others are left verbatim.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> sub_config_refs("${{ fromJson(config.v) }} cat config.json",
...                 lambda m: "NEEDS." + m.group(1))
'${{ fromJson(NEEDS.v) }} cat config.json'
```
