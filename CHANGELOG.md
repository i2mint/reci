# Changelog

All notable changes to this project are documented in this file.

The format is inspired by [Keep a Changelog](https://keepachangelog.com/);
each section corresponds to a git version tag (which is also the release
published to PyPI). Entries are commit subjects and PR titles, verbatim.

## [Unreleased]

### Added

- Behavioural test suite for the compiler (golden workflows, five-level input wiring), recipe parsing, graph, config, action specs, every validation rule, formatters and config adapters ([#4](https://github.com/i2mint/reci/issues/4))

## [0.0.8] - 2026-10-13

- Move agent skills to reci/data/skills (canonical location) ([#3](https://github.com/i2mint/reci/pull/3))

## [0.0.7] - 2026-09-04

- Replace argh (LGPL) with cw in the CLI dispatch ([#6](https://github.com/i2mint/reci/pull/6))

## [0.0.6] - 2026-07-30

- chore(config): point pytest testpaths at the package, add .editorconfig
- chore(meta): use SPDX license expression, add classifiers and keywords

## [0.0.5] - 2026-05-15

- fix(build): exclude .claude and .github from sdist/wheel (absolute symlink broke uv build)
- chore(ci): bump action pins to checkout@v6, setup-uv@v7

## [0.0.4] - 2026-04-01

- Add agent skills and update README

## [0.0.3] - 2026-03-31

- add dev docs

## [0.0.2] - 2026-03-28

- Initial implementation of reci — CI recipe compiler for GitHub Actions
