# globalPlugins/tableHandler/coreUtils.py
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

"""Core utilities
"""

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


import threading
import wx

from NVDAObjects import DynamicNVDAObjectType
import core
from logHandler import log
import queueHandler


class Break(Exception):
	"""Block-level break.
	"""


def catchAll(logger, *loggerArgs, **loggerKwargs):
	
	def decorator(func):
		
		def wrapper(*args, **kwargs):
			try:
				return func(*args, **kwargs)
			except Exception:
				logger.exception(
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


def queueCall(callable, *args, **kwargs):
	queueHandler.queueFunction(queueHandler.eventQueue, callable, *args, **kwargs)


def isMainThread():
	return threading.get_ident() == core.mainThreadId


def callInMainThread(callable, *args, **kwargs):
	if isMainThread():
		callable(*args, **kwargs)
		return
	queueCall(callable, *args, **kwargs)


def translate(text):
	"""
	Use translation from NVDA core.
	
	When this function is used instead of the usual `_` gettext function,
	SCons ignores it and does not create a new entry in the generated `.pot`
	file.
	
	Credits: Alberto Buffolino and Noelia Ruiz Martínez
	Reference: https://github.com/nvaccess/nvda/issues/4652
	"""
	return _(text)


def wx_CallAfter(func):
	
	def wrapper(*args, **kwargs):
		return wx.CallAfter(func, *args, **kwargs)
	
	return wrapper
