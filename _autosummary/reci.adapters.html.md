# reci.adapters

Config adapter registry.

### Functions

| [`detect_adapter`](#reci.adapters.detect_adapter)(project_root)   | Auto-detect the config adapter from project files.   |
|---------------------------------------------------------------------------------|------------------------------------------------------|
| [`get_adapter`](#reci.adapters.get_adapter)(name)              | Get a config adapter by name.                        |

### reci.adapters.detect_adapter(project_root)

Auto-detect the config adapter from project files.

* **Return type:**
  [`ConfigAdapter`](reci.adapters.base.html.md#reci.adapters.base.ConfigAdapter) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### reci.adapters.get_adapter(name)

Get a config adapter by name.

* **Return type:**
  [`ConfigAdapter`](reci.adapters.base.html.md#reci.adapters.base.ConfigAdapter)

### Modules

| [`base`](reci.adapters.base.html.md#module-reci.adapters.base)                 | ConfigAdapter protocol — interface for reading/writing CI config.            |
|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`package_json`](reci.adapters.package_json.html.md#module-reci.adapters.package_json) | PackageJsonAdapter — reads `"ci"` key from package.json.                     |
| [`pyproject`](reci.adapters.pyproject.html.md#module-reci.adapters.pyproject)       | PyprojectTomlAdapter — reads `[tool.ci]` via tomlkit, round-trip preserving. |
| [`wads`](reci.adapters.wads.html.md#module-reci.adapters.wads)                 | WadsAdapter — reads `[tool.wads.ci]` for backward compatibility.             |
| [`yaml_adapter`](reci.adapters.yaml_adapter.html.md#module-reci.adapters.yaml_adapter) | YamlAdapter — reads `.ci.yml` via ruamel.yaml.                               |
