# globalPlugins/tableHandler/config.py
# -*- coding: utf-8 -*-

# This file is part of Table Handler for NVDA.
# Copyright (C) 2020-2024 Accessolutions (http://accessolutions.fr)
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

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


import config
from logHandler import log


CONFIG_SPEC = {
	"brailleRoutingDoubleClickToActivate": "boolean(default=False)",
	"brailleColumnSeparator": "string(default='4568')",
	"brailleColumnSeparatorActivateToSetWidth": "boolean(default=True)",
	"brailleSetColumnWidthWithRouting": "boolean(default=True)",
}


_cache = None


def handleConfigChange():
	global _cache
	oldCfg = _cache["tableHandler"] if _cache else None
	newCfg = config.conf["tableHandler"]
	if not oldCfg or oldCfg["brailleColumnSeparator"] != newCfg["brailleColumnSeparator"]:
		from .behaviors import ColumnSeparatorRegion
		ColumnSeparatorRegion.handleConfigChange()
	_cache = {"tableHandler" : config.conf["tableHandler"].dict()}


def initialize():
	global _cache
	_cache = None
	key = "tableHandler"
	config.conf.spec[key] = CONFIG_SPEC
	# ConfigObj mutates this into a configobj.Section.
	spec = config.conf.spec[key]
	# Initialize cache for later comparison
	handleConfigChange()
	config.post_configReset.register(handleConfigChange)


def terminate():
	global _cache
	config.post_configReset.unregister(handleConfigChange)
	_cache = None
