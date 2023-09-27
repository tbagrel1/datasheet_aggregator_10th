# datasheet_aggregator_10th

## Description

With this Python3 tool, you can build a PDF containing all the rules needed for each of your W40k lists.

This tool takes as input a plain text list such as the one exported by the official W40k app, and produces a PDF aggregating the army rules, detachment rules, weapon lists, and datasheets used by your list, with various options to obtain the desired output.

A very simple GUI is provided, as well as a more detailed CLI.

## Installation & use

### With Nix & direnv

```shell
# first time only
direnv allow
# in the resulting shell
python src
```

### With Nix, without direnv

```shell
# every time
nix develop
# in the resulting shell
python src
```

### With Nix, without direnv, in isolation

```shell
# every time
nix develop -i
# in the resulting shell
DISPLAY=:0.0 python src
```

### Without Nix

To setup the project the first time:

```shell
# Create a new sandbox
python3 -m venv .venv
# Activate the sandbox
source .venv/bin/activate
# Install system dependency
sudo apt install python3-tk
# Install dependencies
pip install .
```

Then the next times:
```shell
# Activate the sandbox
source .venv/bin/activate
# run the program
python3 src
```

## Author

Thomas BAGREL <tomsb07@gmail.com>
