# reci.recipe

Recipe model — declarative CI pipeline description.

A recipe is a YAML file that looks like a GitHub Actions workflow but with
reci extensions: `${{ config.* }}` references, `bind:` mappings for
input renaming, and `outputs:` annotations on `run:` steps.

### Functions

| [`parse_recipe`](#reci.recipe.parse_recipe)(path)        | Load a recipe YAML and return a [`Recipe`](#reci.recipe.Recipe).   |
|----------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| [`parse_recipe_string`](#reci.recipe.parse_recipe_string)(text) | Parse a recipe from a YAML string (useful for testing).                                    |

### Classes

| [`JobSpec`](#reci.recipe.JobSpec)(id[, steps, needs, if_, runs_on, ...])   | One job inside a recipe.   |
|---------------------------------------------------------------------------------------------------|----------------------------|
| [`Recipe`](#reci.recipe.Recipe)(name, on[, jobs, env, defaults, extra])   | A complete reci recipe.    |
| [`StepSpec`](#reci.recipe.StepSpec)(id[, uses, run, with_, if_, name, ...]) | One step inside a job.     |

### Exceptions

| [`RecipeParseError`](#reci.recipe.RecipeParseError)   | Raised when a recipe YAML is structurally invalid.   |
|---------------------------------------------------------------------|------------------------------------------------------|

### *class* reci.recipe.JobSpec(id, steps=list(), needs=list(), if_=None, runs_on='ubuntu-latest', strategy=None, permissions=None, continue_on_error=False, env=dict(), extra=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One job inside a recipe.

### *class* reci.recipe.Recipe(name, on, jobs=dict(), env=dict(), defaults=None, extra=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A complete reci recipe.

### *exception* reci.recipe.RecipeParseError

Bases: [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception)

Raised when a recipe YAML is structurally invalid.

### *class* reci.recipe.StepSpec(id, uses=None, run=None, with_=dict(), if_=None, name=None, outputs=list(), bind=dict(), env=dict(), continue_on_error=False, extra=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One step inside a job.

### reci.recipe.parse_recipe(path)

Load a recipe YAML and return a [`Recipe`](#reci.recipe.Recipe).

* **Return type:**
  [`Recipe`](#reci.recipe.Recipe)

### reci.recipe.parse_recipe_string(text)

Parse a recipe from a YAML string (useful for testing).

* **Return type:**
  [`Recipe`](#reci.recipe.Recipe)
