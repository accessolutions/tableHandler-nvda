# globalPlugins/withSpeechMuted.py
# -*- coding: utf8 -*-

# This file is a utility module for NonVisual Desktop Access (NVDA)
# Copyright (C) 2021 Accessolutions (https://accessolutions.fr)
# This file may be used under the terms of the GNU General Public License, version 2 or later.
# For more details see: https://www.gnu.org/licenses/gpl-2.0.html

"""Untimed replacement for `scriptHandler.getLastScriptRepeatCount`
"""

# Keep compatible with Python 2
from __future__ import absolute_import, division, print_function


__version__ = "2021.11.22"
__author__ = u"Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


from functools import wraps

import globalPluginHandler
from logHandler import log, stripBasePathFromTracebackText
import queueHandler
import speech

try:
	from six.moves._thread import get_ident
except ImportError:
	# NVDA version < 2018.3
	import threading
	get_ident = lambda: threading.current_thread.ident


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	
	def __init__(self):
		super(GlobalPlugin, self).__init__()
		_queueFunction.super = queueHandler.queueFunction
		queueHandler.queueFunction = _queueFunction
		_speak.super = speech.speak
		speech.speak = _speak
		if not hasattr(speech, "speech"):
			# NVDA < 2020.1
			return
		speech.speech.speak = _speak
	
	def terminate(self):
		setter = lambda value: setattr(queueHandler, "queueFunction", value)
		obj = queueHandler.queueFunction
		while True:
			if obj is not _queueFunction:
				if not hasattr(obj, "super"):
					log.error("Monkey-patch has been overridden: queueHandler.queueFunction")
					queueHandler.queueFunction = obj
					break
				setter = lambda value, obj=obj: setattr(obj, "super", value)
				obj = obj.super
				continue
			setter(obj.super)
			break
		setter = lambda value: setattr(speech, "speak", value)
		obj = speech.speak
		while True:
			if obj is not _speak:
				if not hasattr(obj, "super"):
					log.error("Monkey-patch has been overridden: speech.speak")
					speech.speak = obj
					break
				setter = lambda value, obj=obj: setattr(obj, "super", value)
				obj = obj.super
				continue
			setter(obj.super)
			break
		if not hasattr(speech, "speech"):
			# NVDA < 2020.1
			return
		setter = lambda value: setattr(speech.speech, "speak", value)
		obj = speech.speak
		while True:
			if obj is not _speak:
				if not hasattr(obj, "super"):
					log.error("Monkey-patch has been overridden: speech.speech.speak")
					speech.speech.speak = obj
					break
				setter = lambda value, obj=obj: setattr(obj, "super", value)
				obj = obj.super
				continue
			setter(obj.super)
			break



_activeContextsByThread = {}


def _queueFunction(queue, func, *args, **kwargs):
	ctx = _activeContextsByThread.get(get_ident())
	if ctx and ctx.propagates:
		func = _decorator(func, ctx.increment)
	return _queueFunction.super(queue, func, *args, **kwargs)


def _speak(*args, **kwargs):
	ctx = _activeContextsByThread.get(get_ident())
	if ctx and ctx.level < 0:
		ctx.mute(_speak, *args, **kwargs)
		return
	return _speak.super(*args, **kwargs)


class _SpeechContextManager(object):
	
	def __init__(self, increment, retains=False, propagates=True):
		if not isinstance(increment, int):
			raise ValueError("increment={!r}".format(increment))
		self.active = False
		self.increment = increment
		self.retains = retains
		self.propagates = propagates
		self.muted = []
	
	def __enter__(self):
		ident = get_ident()
		parent = self.parent = _activeContextsByThread.get(ident)
		increment = self.increment
		self.level = (parent.level if parent else 0) + increment
		self.muted = []
		self.active = True
		_activeContextsByThread[ident] = self
		return self
	
	def __exit__(self, exc_type, exc_value, traceback):
		ident = get_ident()
		parent = self.parent
		if parent:
			_activeContextsByThread[ident] = parent
		else:
			del _activeContextsByThread[ident]
	
	def mute(self, func, *args, **kwargs):
		if self.retains:
			self.muted.append((func, args, kwargs))
	
	def speakMuted(self):
		retains = self.retains
		if not retains:
			raise ValueError("retains={!r}".format(retains))
		increment = self.increment
		if not increment < 0:
			raise ValueError("increment={!r}".format(increment))
		with speechUnmuted(increment=-increment if self.active else 0):
			for func, args, kwargs in self.muted:
				func(*args, **kwargs)


def speechMuted(increment=-1, retains=False, propagates=True):
	return _SpeechContextManager(increment=increment, retains=retains, propagates=propagates)


def speechUnmuted(increment=1, retains=False):
	return _SpeechContextManager(increment=increment, retains=retains, propagates=False)


def _decorator(func, increment):
	
	@wraps(func)
	def wrapper(*args, **kwargs):
		with speechMuted(increment=increment):
			return func(*args, **kwargs)
	
	return wrapper


def speechMutedFunction(func, increment=-1):
	return _decorator(func, increment=increment)

def speechUnmutedFunction(func, increment=1):
	return _decorator(func, increment=increment)
