# CPackages
*CPackages* is a package manager written in **__Python__** that supports many features.
The short form for `cpackages` is `cpkg`.

> Runtime will be slow due to using python, however slowly optimizations will start making its way in `cpkgs`.

---

## Installation

To install _cpackages_, you have to do `NOTHING` (well almost).

Since _cpackages_ has almost everything implementated using the python standard library, you dont need to install a gigabyte worth of packages.

First, install this tiny library `arghandle` (written by me):
```bash
pip install arghandle==3.0.0
```

> This is a very tiny library that wraps `sys.argv` for click-based and argparse-based argument parsing.

Next you have to run:
`git clone https://github.com/alanbutidk/cpackages/ cpkg`

or just download the source-releases, it has the exact structure you need.

OR if you have `ppm` installed, GREAT. as you just have to run `ppm clone alanbutidk/cpackages` and it will auto-install the dependencies.

---

### Recommended

Its recommended that you create a `alias/doskey` to cpkg like this:

For bat/cmd:

```bat
doskey cpkg=pushd [PATH TO CPKG OUTERDIR] ^& [PATH TO YOUR PYTHON EXECUTABLE/IN-PATH NAME] -m cpkg $* ^& popd
```

For zsh/bash:

```zsh
cpkg() {
  pushd [PATH TO CPKG OUTERDIR] > /dev/null && [PATH TO YOUR PYTHON EXECUTABLE/IN-PATH NAME] -m cpkg "$@" && popd > /dev/null
}
```

Note: replace [PATH TO CPKG OUTERDIR] with the dir where cpkg resides like:

Example tree:
```
[PATH TO CPKG OUTERDIR]/
|--> cpkg/
|-->--> ...
|-->--> utils/
|-->-->--> [...]
------------------

```

---


## Create a registry
It is very easy to create a `cpkg` _registry_, and for now there is NO official registry.

To create a registry run:
`cpkg create-server [CI/CD ARGUMENTS IF ON NON-EOL SERVER]`

It will walk you through 3 types of servers/registries:

- Local (Normal server at localhost)
- Professional (Professional servers/made for official or secure 3rd party servers)
- Ghost (Use-N-Throw servers)

---

# License

`CPackages` is licensed under GPLv3+, meaning if you modify `cpackages`, you will have to *open-source* it.
However `CPackages` registry servers and packages are free to use any SPDX-list license.


