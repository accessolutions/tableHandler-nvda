# globalPlugins/lastScriptUntimedRepeatCount.py
# -*- coding: utf8 -*-

# This file is a utility module for NonVisual Desktop Access (NVDA)
# Copyright (C) 2021 Accessolutions (https://accessolutions.fr)
# This file may be used under the terms of the GNU General Public License, version 2 or later.
# For more details see: https://www.gnu.org/licenses/gpl-2.0.html

"""Untimed replacement for `scriptHandler.getLastScriptRepeatCount`
"""

# Keep compatible with Python 2
from __future__ import absolute_import, division, print_function


__version__ = "2021.09.16"
__author__ = u"Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


import inspect
from itertools import chain
from six import text_type
import sys
import threading
import traceback

import globalPluginHandler
from logHandler import log, stripBasePathFromTracebackText
import scriptHandler


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	
	def __init__(self):
		super(GlobalPlugin, self).__init__()
		_executeScript.super = scriptHandler.executeScript
		scriptHandler.executeScript = _executeScript
	
	def terminate(self):
		if (
			(sys.version_info[0] == 2 and scriptHandler.executeScript.__func__ is not _executeScript)
			or (sys.version_info[0] == 3 and scriptHandler.executeScript is not _executeScript)
		):
			log.error("Monkey-patch has been overridden: scriptHandler.executeScript")
		scriptHandler.executeScript = _executeScript.super


_lastScriptCount = None


def _executeScript(script, gesture):
	global _lastScriptCount
	lastScriptRef = scriptHandler._lastScriptRef
	lastScript = lastScriptRef() if lastScriptRef else None
	if (
		not scriptHandler._isScriptRunning
		and lastScript == getattr(script, "__func__", script)
	):
		_lastScriptCount += 1
	else:
		_lastScriptCount = 0
	_executeScript.super(script, gesture)
		
	
def getLastScriptUntimedRepeatCount():
	return _lastScriptCount
