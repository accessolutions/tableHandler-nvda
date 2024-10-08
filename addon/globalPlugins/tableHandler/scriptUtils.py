# globalPlugins/tableHandler/scriptUtils.py
# -*- coding: utf-8 -*-

# This file is part of Table Handler for NVDA.
# Copyright (C) 2020-2024 Accessolutions (https://accessolutions.fr)
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

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


from itertools import groupby

import addonHandler
import inputCore
from keyboardHandler import KeyboardInputGesture
from logHandler import log
import gui

from .coreUtils import translate 


addonHandler.initTranslation()


class ScriptWrapper:
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


def getScriptInfo(scriptCls, script, obj=None, ancestors=None):
	if obj is None:
		obj = gui.mainFrame.prevFocus
	if ancestors is None:
		ancestors = gui.mainFrame.prevFocusAncestors
	map = inputCore.manager.getAllGestureMappings(obj=obj, ancestors=ancestors)
	category = inputCore._AllGestureMappingsRetriever.getScriptCategory(scriptCls, script)
	scripts = map.get(category, {})
	return scripts.get(script.__doc__, None)


def getScriptInfoMainGestureDetails(scriptInfo):
	# Default bindings
	cls = scriptInfo.cls
	clsGestureMap = getattr(cls, "_{}__gestures".format(cls.__name__))
	defaultList = [
		inputCore.getDisplayTextForGestureIdentifier(gesture)
		for gesture, scriptName in clsGestureMap.items()
		if scriptName == scriptInfo.scriptName
	]
	# Effective bindings
	effectiveList = [
		inputCore.getDisplayTextForGestureIdentifier(gesture)
		for gesture in scriptInfo.gestures
	]
	# If there are default bindings in effect, consider only these
	gesturesList = [item for item in defaultList if item in effectiveList]
	if not gesturesList:
		gesturesList = effectiveList
	del effectiveList
	del defaultList
	
	key = lambda item: item[0]
	mainBySource = {
		source: next(items)[1]  # Keep only the first gesture for each source
		for source, items in groupby(sorted(gesturesList, key=key), key=key)
	}
	source = translate("keyboard, all layouts")
	main = mainBySource.get(source)
	isKeyboardGesture = True
	if not main:
		for layout in KeyboardInputGesture.LAYOUTS:  # Only 1 will match effective bindings
			source = translate("%s keyboard") % layout
			main = mainBySource.get(source)
			if main:
				break
	if not main:
		source, main = next(mainBySource.items())
		isKeyboardGesture = False
	return isKeyboardGesture, source, main


def getScriptGestureMenuHint(scriptCls, script, obj=None, ancestors=None):
	scriptInfo = getScriptInfo(scriptCls, script, obj=obj, ancestors=ancestors)
	if not scriptInfo:
		return None
	isKeyboardGesture, source, main = getScriptInfoMainGestureDetails(scriptInfo)
	if isKeyboardGesture:
		hint = main
	else:
		hint = translate("{main} ({source})").format(main=main, source=source)
	return "\t{}".format(hint)


def getScriptGestureTutorMessage(scriptCls, script, obj=None, ancestors=None, doc=None):
	scriptInfo = getScriptInfo(scriptCls, script, obj=obj, ancestors=ancestors)
	if not scriptInfo:
		return None
	isKeyboardGesture, source, main = getScriptInfoMainGestureDetails(scriptInfo)
	if isKeyboardGesture:
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


def overrides(script):
	
	def decorator(func):
		if not func.__doc__:
			func.__doc__ = script.__doc__
			for key, value in script.__dict__.items():
				if key not in func.__dict__:
					func.__dict__[key] = value
		return func
	
	return decorator
