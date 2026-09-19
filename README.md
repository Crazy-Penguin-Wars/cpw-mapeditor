
# Crazy Penguin Wars: Map Editor

A simple Python program that allows users to design maps for Crazy Penguin Wars.

## How to use
Head to the release page and download the latest version (only for Windows)

For other operating systems: you will only be able to run the map editor, not the test launcher. Use the guide in [For developers](#for-developers), but skip the first step.

## For developers
- Download the maptester version of the demo launcher from [its releases page](https://github.com/Crazy-Penguin-Wars/cpw-launcher/releases/download/1.0.0/FOR-MAPTESTERS-Crazy.Penguin.Wars.1_0_0.zip) or build it yourself from [the maptester branch](https://github.com/Crazy-Penguin-Wars/cpw-launcher/tree/maptester) in the cpw-launcher repository. Rename its root folder to `testlauncher` and place it under `assets/`.
- Run `MapEditor.exe` (this uses the embedded Python environment) or `map_editor.py` (this uses your local Python environment, be sure to install all dependencies from `requirements.txt` first).

## AI Contribution
The code in this repository is almost entirely made using AI tools, which may lead to certain bugs or performance issues. Our excuse is that it's only a map editor and no crucial part of the game, and that it wouldn't make sense spending a ton of time on it. This is not how we usually code this project, so our apologies.