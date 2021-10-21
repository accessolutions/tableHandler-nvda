# -*- coding: UTF-8 -*-

# Build customizations
# Change this file instead of sconstruct or manifest files, whenever possible.

# Full getext (please don't change)
_ = lambda x: x

# Add-on information variables
addon_info = {
	# for previously unpublished addons, please follow the community guidelines at:
	# https://bitbucket.org/nvdaaddonteam/todo/raw/master/guidelines.txt
	# add-on Name, internal for nvda
	"addon_name": "tableHandler",
	# Add-on summary, usually the user visible name of the addon.
	# Translators: Summary for this add-on to be shown on installation and add-on information.
	"addon_summary": _("Table Handler"),
	# Add-on description
	# Translators: Long description to be shown for this add-on on add-on information from add-ons manager
	"addon_description": _("""Description for the add-on.
It can span multiple lines."""),
	# version
	"addon_version": "2021.10.20-dev",
	# Author(s)
	"addon_author": u"Accessolutions (https://accessolutions.fr)",
	# URL for the add-on documentation support
	"addon_url": None,
	# Documentation file name
	"addon_docFileName": "readme.html",
	# Minimum NVDA version supported (e.g. "2018.3.0", minor version is optional)
	"addon_minimumNVDAVersion": None,
	# Last NVDA version supported/tested (e.g. "2018.4.0", ideally more recent than minimum version)
	"addon_lastTestedNVDAVersion": "2021.2",
	# Add-on update channel (default is None, denoting stable releases, and for development releases, use "dev"; do not change unless you know what you are doing)
	"addon_updateChannel": None,
}

# Specify whether this add-on provides a single documentation or separate
# technical and user documentations.
# If set to `True`, the `readme.md` file at the root of this project is used
# as the source for the user documentation in the base language.
useRootDocAsUserDoc = True

import os.path

# Define the python files that are the sources of your add-on.
# You can use glob expressions here, they will be expanded.
pythonSources = [
	os.path.join(dirpath, filename)
	for dirpath, dirnames, filenames in os.walk("addon")
		for filename in filenames
		if os.path.splitext(filename)[1] == ".py"
	]

# Native language.
# This is the language of the root `readme.md` and the original string literals
# found in the source code. If the add-on is ever to be translated, the native
# language should be "en" for English.
i18nNative = "en"

# Files that contain strings for translation. Usually your python sources
i18nSources = pythonSources + ["buildVars.py"]

# Files that will be ignored when building the nvda-addon file
# Paths are relative to the addon directory, not to the root directory of your addon sources.
excludedFiles = []
