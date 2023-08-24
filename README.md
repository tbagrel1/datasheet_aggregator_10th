# datasheet_aggregator_10th

## Description

With this Python3 tool, you can build a PDF containing all the rules needed for each of your W40k list.

This tool takes as input a plain text list such as the one exported by the official W40k app, and produces a PDF aggregating the army rules, detachment rules, weapon lists, and datasheets used by your list, with various options to obtain the desired output.

A GUI will be implemented soon, with an associated release as a Windows `.exe` binary.

## Installation

To setup the project the first time:

```shell
# Create a new sandbox
python3 -m venv .venv
# Activate the sandbox
source .venv/bin/activate
# Install dependencies
pip install -r requirements.txt

# Install system dependency
sudo apt install python3-tk
```

Then the next times:

```shell
# Activate the sandbox
source .venv/bin/activate
```

## Author

Thomas BAGREL <tomsb07@gmail.com>
