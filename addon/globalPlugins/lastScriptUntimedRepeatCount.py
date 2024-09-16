# globalPlugins/lastScriptUntimedRepeatCount.py
# -*- coding: utf8 -*-

# This file is a utility module for NonVisual Desktop Access (NVDA)
# Copyright (C) 2021-2024 Accessolutions (https://accessolutions.fr)
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

"""Untimed replacement for `scriptHandler.getLastScriptRepeatCount`
"""

__version__ = "2024.09.19"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


import globalPluginHandler
from logHandler import log
import scriptHandler


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	
	def __init__(self):
		super().__init__()
		_executeScript.super = scriptHandler.executeScript
		scriptHandler.executeScript = _executeScript
	
	def terminate(self):
		setter = lambda value: setattr(scriptHandler, "executeScript", value)
		obj = scriptHandler.executeScript
		while True:
			if obj is not _executeScript:
				if hasattr(obj, "super"):
					setter = lambda value, obj=obj: setattr(obj, "super", value)
					obj = obj.super
					continue
				else:
					log.error("Monkey-patch has been overridden: scriptHandler.executeScript")
					scriptHandler.executeScript = obj
					break
			setter(obj.super)
			break


_lastScriptCount = None


def _executeScript(script, gesture):
	global _lastScriptCount
	lastScriptRef = scriptHandler._lastScriptRef
	lastScript = lastScriptRef() if lastScriptRef else None
	if (
		not scriptHandler._isScriptRunning
		and lastScript == getattr(script, "__func__", script)
	):
		if _lastScriptCount is None:
			# Happens only with the reloadPlugins global command
			_lastScriptCount = 0
		_lastScriptCount += 1
	else:
		_lastScriptCount = 0
	_executeScript.super(script, gesture)
		
	
def getLastScriptUntimedRepeatCount():
	return _lastScriptCount
