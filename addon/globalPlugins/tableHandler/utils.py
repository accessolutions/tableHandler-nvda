# globalPlugins/tableHandler/utils.py
# -*- coding: utf-8 -*-

# This file is part of Table Handler for NVDA.
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

"""Table Handler Global Plugin
"""

# Get ready for Python 3
from __future__ import absolute_import, division, print_function

__version__ = "2021.09.09"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

import six
import weakref

from NVDAObjects import DynamicNVDAObjectType
import addonHandler
import api
import inputCore
from keyboardHandler import KeyboardInputGesture
from logHandler import log
import scriptHandler


addonHandler.initTranslation()


def getObjLogInfo(obj):
	from pprint import pformat
	import globalVars
	info = {
		"obj": repr(obj),
		"isFocus": globalVars.focusObject is obj,
		"(windowHandle, objectID, childID)": (
			getattr(obj, "event_windowHandle", None),
			getattr(obj, "event_objectID", None),
			getattr(obj, "event_childID", None)
		)
	}
	ti = obj.treeInterceptor
	info["treeInterceptor"] = repr(ti)
	if obj.treeInterceptor:
		info["passThrough"] = ti.passThrough
		info["isReady"] = ti.isReady
		info["_hadFirstGainFocus"] = ti._hadFirstGainFocus
	return pformat(info, indent=4)


def catchAll(logger, *loggerArgs, **loggerKwargs):
	def decorator(func):
		def wrapper(*args, **kwargs):
			try:
				return func(*args, **kwargs)
			except:
				log.exception(
					"args={}, kwargs={}".format(repr(args), repr(kwargs)),
					*loggerArgs,
					**loggerKwargs
				)
		return wrapper
	return decorator
			

def getDynamicClass(bases):
	"""Create a new class given its bases.
	
	Based upon `DynamicNVDAObjectType.__call__`.
	"""
	if not isinstance(bases, tuple):
		bases = tuple(bases)
	cache = DynamicNVDAObjectType._dynamicClassCache
	dynCls = cache.get(bases)
	if not dynCls:
		name = "Dynamic_%s" % "".join([x.__name__ for x in bases])
		dynCls = type(name, bases, {})
		cache[bases] = dynCls
	return dynCls


class ScriptWrapper(object):
	"""
	Wrap a script to help controlling its metadata or its execution.
	"""
	def __init__(self, script, override=None, arg="script", **defaults):
		self.script = script
		self.override = override
		self.arg = arg
		self.defaults = defaults
	
	def __getattribute__(self, name):
		# Pass existing wrapped script attributes such as __doc__, __name__,
		# category, ignoreTreeInterceptorPassThrough or resumeSayAllMode.
		# Note: scriptHandler.executeScript looks at script.__func__ to
		# prevent recursion.
		if name not in ("__class__", "script", "override", "arg", "defaults"):
			if self.override:
				try:
					return getattr(self.override, name)
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
		return object.__getattribute__(self, name)
	
	def __call__(self, gesture, **kwargs):
		if self.override:
			# Throws `TypeError` on purpose if `arg` is already in `kwargs`
			return self.override(gesture, **kwargs, **{self.arg: self.script})
		return self.script(gesture, **kwargs)


def getScriptGestureDisplayText(scriptCls, script, obj=None, ancestors=None):
	map = inputCore.manager.getAllGestureMappings(obj=obj, ancestors=ancestors)
	category = inputCore._AllGestureMappingsRetriever.getScriptCategory(scriptCls, script)
	scripts = map.get(category, {})
	scriptInfo = scripts.get(script.__doc__, None)
	if not scriptInfo or not scriptInfo.gestures:
		return None
	gesture = next(iter(scriptInfo.gestures))
	source, main = inputCore.getDisplayTextForGestureIdentifier(gesture)
	if (
		source == _("keyboard, all layouts")
		or source in [_("%s keyboard") % layout for layout in KeyboardInputGesture.LAYOUTS]
	):
		return main
	return _("{main} ({source})").format(main=main, source=source)


def getColumnSpanSafe(cell):
	try:
		span = cell.columnSpan
		if span is None:
			span = 1
		elif span < 1:
			log.error("cell={}, role={}, columnSpan={}".format(repr(cell), cell.role, span))
			span = 1
	except NotImplementedError:
		span = 1
	except Exception:
		log.exception("cell={}".format(repr(cell)))
		span = 1
	return span


def getRowSpanSafe(cell):
	try:
		span = cell.rowSpan
		if span < 1:
			log.error("cell={}, role={}, rowSpan={}".format(repr(cell), cell.role, span))
			span = 1
	except NotImplementedError:
		span = 1
	except Exception:
		log.exception("cell={}".format(repr(cell)))
		span = 1
	return span
