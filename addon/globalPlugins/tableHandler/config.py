# globalPlugins/webAccess/config.py
# -*- coding: utf-8 -*-

# This file is part of Table Handler for NVDA.
# Copyright (C) 2020-2021 Accessolutions (http://accessolutions.fr)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# See the file COPYING.txt at the root of this distribution for more details.

# Stay compatible with Python 2
from __future__ import absolute_import, division, print_function

__version__ = "2021.11.10"
__author__ = u"Julien Cochuyt <j.cochuyt@accessolutions.fr>"


import config
from logHandler import log

from .nvdaVersion import nvdaVersion


CONFIG_SPEC = {
	"brailleRoutingDoubleClickToActivate": "boolean(default=False)",
	"brailleColumnSeparator": "string(default='4568')",
}


_cache = None


def handleConfigChange():
	global _cache
	oldCfg = _cache["tableHandler"] if _cache else None
	newCfg = config.conf["tableHandler"]
	if not oldCfg or oldCfg["brailleColumnSeparator"] != newCfg["brailleColumnSeparator"]:
		from .behaviors import ColumnSeparatorRegion
		ColumnSeparatorRegion.handleConfigChange()
	if nvdaVersion >= (2018, 4):
		_cache = {"tableHandler" : config.conf["tableHandler"].dict()}
	else:
		_cache = {"tableHandler": dict(config.conf["tableHandler"].iteritems())}


def initialize():
	global _cache
	_cache = None
	key = "tableHandler"
	config.conf.spec[key] = CONFIG_SPEC
	# ConfigObj mutates this into a configobj.Section.
	spec = config.conf.spec[key]
	# Initialize cache for later comparison
	handleConfigChange()
	if nvdaVersion >= (2018, 3):
		config.post_configReset.register(handleConfigChange)


def terminate():
	global _cache
	if nvdaVersion >= (2018, 3):
		config.post_configReset.unregister(handleConfigChange)
	_cache = None
