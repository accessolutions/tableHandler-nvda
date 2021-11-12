# globalPlugins/tableHandler/scriptUtils.py
# -*- coding: utf-8 -*-

# This file is a utility module for NVDA.
# Copyright (C) 2020-2021 Accessolutions (https://accessolutions.fr)
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

"""Script utilities
"""

# Keep compatible with Python 2
from __future__ import absolute_import, division, print_function

__version__ = "2021.10.01"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

from functools import WRAPPER_ASSIGNMENTS, WRAPPER_UPDATES, update_wrapper
from itertools import chain
import time

import addonHandler
import inputCore
from keyboardHandler import KeyboardInputGesture
from logHandler import log
import scriptHandler

from .coreUtils import translate 


addonHandler.initTranslation()


class ScriptWrapper(object):
	"""
	Wrap a script to help controlling its metadata or its execution.
	"""
	
	def __init__(
		self,
		script,
		override=None,
		arg="script",
		**defaults
	):
		self.script = script
		self.override = override
		self.arg = arg
		self.defaults = defaults
		#update_wrapper(self, script)
	
	def __call__(self, *args, **kwargs):
		script = self.script
		override = self.override
		if override:
			# Throws `TypeError` on purpose if `arg` is already in `kwargs`
			return override(*args, **kwargs, **{self.arg: script})
		return script(*args, **kwargs)
	
	def __getattr__(self, name):
		# Pass existing wrapped script attributes such as __doc__, __name__,
		# category, ignoreTreeInterceptorPassThrough or resumeSayAllMode.
		# Note: scriptHandler.executeScript looks at script.__func__ to
		# prevent recursion.
		if name != "__name__":
			override = self.override
			if override:
				try:
					return getattr(override, name)
				except AttributeError:
					pass
		try:
			return getattr(self.script, name)
		except AttributeError:
			pass
		try:
			return self.defaults[name]
		except KeyError:
			pass
		raise AttributeError(name)
	
	def __repr__(self):
		override = self.override
		if override and getattr(override, "__self__", None) is not self:
			return "<{} script={!r}, override={!r}>".format("SW" or type(self), self.script, override)
		return "<{} script={!r}>".format("SW" or type(self), self.script)


def getScriptGestureHint(scriptCls, script, obj=None, ancestors=None, doc=None):
	map = inputCore.manager.getAllGestureMappings(obj=obj, ancestors=ancestors)
	category = inputCore._AllGestureMappingsRetriever.getScriptCategory(scriptCls, script)
	scripts = map.get(category, {})
	scriptInfo = scripts.get(script.__doc__, None)
	if not scriptInfo or not scriptInfo.gestures:
		return None
	gesture = next(iter(scriptInfo.gestures))
	source, main = inputCore.getDisplayTextForGestureIdentifier(gesture)
	if (
		source == translate("keyboard, all layouts")
		or source in [translate("%s keyboard") % layout for layout in KeyboardInputGesture.LAYOUTS]
	):
		# Translators: A script hint message for a keyboard gesture
		msg = _("Press {shortcut}").format(shortcut=main)
	else:
		# Translators: A script hint message for a non-keyboard gesture
		msg = _("Perform {main} ({source})").format(main=main, source=source)
	if doc is not False:
		doc = doc if doc else script.__doc__
		# Translators: A full script hint message
		msg = _("{gesture} to {command}").format(gesture=msg, command=doc)
	return msg
