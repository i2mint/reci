# reci.adapters.base

ConfigAdapter protocol — interface for reading/writing CI config.

### Classes

| [`ConfigAdapter`](#reci.adapters.base.ConfigAdapter)(\*args, \*\*kwargs)   | Protocol for pluggable CI config I/O.   |
|--------------------------------------------------------------------------------------|-----------------------------------------|

### *class* reci.adapters.base.ConfigAdapter(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Protocol for pluggable CI config I/O.

#### default_path()

Return the default filename for this adapter.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### read(path)

Read config from a file and return a flat dict.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### write(path, config)

Write config to a file, preserving existing content.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
