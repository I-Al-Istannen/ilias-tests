<div align="center">
  <h1>ilias-tests</h1>
</div>

Managing tests on ILIAS is a bit cumbersome as import/export does not work
reliably, and some actions need to be manually executed for every test file.
This does not scale extremely well to a course with many tests :)

This repositories offers a CLI tool that interfaces with ILIAS to automate
parts of this process. It is based on the ilias comprehension of
[PFERD](https://github.com/Garmelon/PFERD).

## Running ilias-tests
You can run it directly from GitHub with [uv](https://docs.astral.sh/uv/):
```
uv run --with git+https://github.com/I-Al-Istannen/ilias-tests@master ilias-tests --help
```

To install it as a command line tool, use
```
uv tool install git+https://github.com/I-Al-Istannen/ilias-tests@master
```

To install it into an existing environment or project, use
```
pip install git+https://github.com/I-Al-Istannen/ilias-tests@master
# or
uv add git+https://github.com/I-Al-Istannen/ilias-tests@master
```

Afterwards, execute `ilias-tests --help` to view the usage.
