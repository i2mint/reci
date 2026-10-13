# reci.recipe_checks

Whole-recipe checks that need the recipe text and the config, not the step graph.

Shared by the compiler (which refuses to emit a workflow with these problems)
and the validation rules (which report them), so both always agree.

### Module Attributes

| [`SETUP_JOB_ID`](#reci.recipe_checks.SETUP_JOB_ID)   | The generated job that exports config values; recipe jobs may not use the id when config is supplied.    |
|-----------------------------------------------------------------|----------------------------------------------------------------------------------------------------------|
| [`CONFIG_REF_RE`](#reci.recipe_checks.CONFIG_REF_RE)  | `${{ config.X }}` — the one form the compiler rewrites (see reci#19 for refs inside larger expressions). |

### Functions

| [`config_references`](#reci.recipe_checks.config_references)(recipe)            | `(location, key, needs_context_available)` for each `${{ config.key }}`.   |
|---------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`find_recipe_problems`](#reci.recipe_checks.find_recipe_problems)(recipe, config) | Problems that would make the compiled workflow invalid.                    |

### Classes

| [`RecipeProblem`](#reci.recipe_checks.RecipeProblem)(rule_id, message[, location])   | One problem found by [`find_recipe_problems()`](#reci.recipe_checks.find_recipe_problems).   |
|------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|

### reci.recipe_checks.CONFIG_REF_RE *= re.compile('\\\\$\\\\{\\\\{\\\\s\*config\\\\.(\\\\w+)\\\\s\*\\\\}\\\\}')*

`${{ config.X }}` — the one form the compiler rewrites (see reci#19 for refs
inside larger expressions).  Plain text such as `config.json` does not match.

### *class* reci.recipe_checks.RecipeProblem(rule_id, message, location=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One problem found by [`find_recipe_problems()`](#reci.recipe_checks.find_recipe_problems).

### reci.recipe_checks.SETUP_JOB_ID *= 'setup'*

The generated job that exports config values; recipe jobs may not use the id
when config is supplied.

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
* `DAG007` — a recipe job named `setup` while config is supplied: it
  would replace the generated setup job.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`RecipeProblem`](#reci.recipe_checks.RecipeProblem)]
