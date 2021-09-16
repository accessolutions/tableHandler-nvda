# globalPlugins/tableHandler/fakeObjects/__init__.py
# -*- coding: utf-8 -*-

# This file is part of Table Handler for NVDA.
# Copyright (C) 2020 Accessolutions (https://accessolutions.fr)
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

from NVDAObjects import IAccessible, NVDAObject
import addonHandler
import api
import braille
import browseMode
import config
import eventHandler
from logHandler import log
import textInfos.offsets

from ..textInfos import LaxSelectionTextInfo
from ..utils import getDynamicClass


addonHandler.initTranslation()


CHILD_ACCESS_GETTER = "getter"
CHILD_ACCESS_ITERATION = "iteration"
CHILD_ACCESS_SEQUENCE = "sequence"


class FakeObject(NVDAObject):
	"""Base class for NVDA objects which do not strictly correspond to a real control.
	"""

	_childAccess = CHILD_ACCESS_GETTER
	
	#def __init__(self, parent=None, **kwargs):
	def __init__(self, **kwargs):
		super(FakeObject, self).__init__()
		if "children" in kwargs:
			self._childAccess = CHILD_ACCESS_SEQUENCE
		elif "firstChild" in kwargs:
			self._childAccess = CHILD_ACCESS_ITERATION
		for key, value in kwargs.items():
			setattr(self, key, value)
# 		if parent is not None:
# 			self.parent = parent
# 		else:
# 			parent = self.parent  # Retrieve from eventually overloaded property.
# 		self.appModule = parent.appModule
# 		self.processID = parent.processID
# 		try:
# 			# HACK: Some NVDA code depends on window properties, even for non-Window objects.
# 			self.windowHandle = parent.windowHandle
# 			self.windowClassName = parent.windowClassName
# 			self.windowControlID = parent.windowControlID
# 			self.windowThreadID = parent.windowThreadID
# 		except AttributeError:
# 			pass
		
	def _get_TextInfo(self):
		superCls = super(FakeObject, self).TextInfo
		if not issubclass(
			superCls,
			textInfos.offsets.OffsetsTextInfo
		):
			return superCls
		return getDynamicClass((LaxSelectionTextInfo, superCls))
	
	_cache_children = False
	
	def _get_children(self):
		if self._childAccess == CHILD_ACCESS_GETTER:
			children = []
			index = 0
			while True:
				try:
					child = self.getChild(index)
				except Exception:
					break
				if child is None:
					break
				children.append(child)
				index += 1
			return children
		elif self._childAccess == CHILD_ACCESS_ITERATION:
			children = []
			child = self.firstChild
			while child is not None:
				children.append(child)
				child = child.next
			return children
		elif self._childAccess == CHILD_ACCESS_SEQUENCE:
			return []  # The `children` method is expected to be overwritten in this mode.
		else:
			raise ValueError("_childAccess={}".format(repr(self._childAccess)))
	
	def _get_appModule(self):
		return self.parent.appModule
	
	def _set_appModule(self, value):
		raise Exception("Just checking")
	
	def _get_event_windowHandle(self):
		return self.parent.windowHandle
	
	def _get_event_objectID(self):
		return self.parent.event_objectID
	
	def _get_event_childID(self):
		return self.parent.event_childID
	
	_cache_firstChild = False
	
	def _get_firstChild(self):
		if self._childAccess == CHILD_ACCESS_GETTER:
			return self.getChild(0)
		elif self._childAccess == CHILD_ACCESS_ITERATION:
			return None  # The `firstChild` property is expected to be overwritten in this mode.
		elif self._childAccess == CHILD_ACCESS_SEQUENCE:
			return self.children[0]
		else:
			raise ValueError("_childAccess={}".format(repr(self._childAccess)))
	
	_cache_lastChild = False
	
	def _get_lastChild(self):
		if self._childAccess == CHILD_ACCESS_GETTER:
			return self._getChild(self.childCount - 1)
		elif self._childAccess == CHILD_ACCESS_ITERATION:
			prevChild = currChild = self.firstChild
			while currChild is not None:
				prevChild = currChild
				currChild = currChild.next
			return prevChild
		elif self._childAccess == CHILD_ACCESS_SEQUENCE:
			return self.children[-1]
		else:
			raise ValueError("_childAccess={}".format(repr(self._childAccess)))
	
# 	def _get_parent(self):
# 		return self._parent
# 	
# 	def _set_parent(self, value):
# 		self._parent = value
	
	def _get_processID(self):
		return self.parent.processID
	
	def _get_windowClassName(self):
		return self.parent.windowClassName
	
	def _get_windowControlID(self):
		return self.parent.windowControlID
	
	def _get_windowHandle(self):
		return self.parent.windowHandle
	
	def _get_windowThreadID(self):
		return self.parent.windowThreadID
	
	def getChild(self, index):
		if self._childAccess == CHILD_ACCESS_GETTER:
			return None  # The `getChild` method is expected to be overloaded in this mode.
		elif self._childAccess == CHILD_ACCESS_ITERATION:
			child = self.firstChild
			target = index
			current = 0
			while child is not None:
				if current == target:
					return child
				child = child.next
				current += 1
		elif self._childAccess == CHILD_ACCESS_SEQUENCE:
			return self.children[index]
		else:
			raise ValueError("_childAccess={}".format(repr(self._childAccess)))
	
	def setFocus(self):
		ti = self.parent.treeInterceptor
		if isinstance(ti, browseMode.BrowseModeDocumentTreeInterceptor):
			# Normally, when entering browse mode from a descendant (e.g. dialog),
			# we want the cursor to move to the focus (#3145).
			# However, we don't want this for fake objects, as these aren't focusable.
			ti._enteringFromOutside = True
		# This might get called from a background thread and all NVDA events must run in the main thread.
		eventHandler.queueEvent("gainFocus", self)
	
	def _isEqual(self, obj):
		return self is obj
	
# 	def event_loseFocus(self):
# 		log.info(f"{self!r}.event_loseFocus", stack_info=True)
# 		import globalVars
# 		obj = globalVars.focusObject
# 		if obj is self:
# 			while isinstance(obj, FakeObject):
# 				obj = globalVars.focusAncestors.pop()
# 				log.info(f"Step up to {_getObjLogInfo(obj)}")
# 				globalVars.focusObject = obj

# 				parent = globalVars.focusObject.parent
# 				if parent is None:
# 					if globalVars.focusObject is self:
# 						log.error("Parentless focus object: {!r}".format(globalVars.focusObject))
# 					else:
# 						log.error("Parentless focus ancestor: {!r}".format(globalVars.focusObject))
# 					break
# 				if parent != globalVars.focusAncestors[-1]:
# 					log.error("Parent missing from focus ancestors: {!r}".format(parent))
# 					break
# 				#log.info(f"Step up to {parent!r}(ti={parent.treeInterceptor!r}")
# 				log.info(f"Step up to {_getObjLogInfo(parent)}")
# 				globalVars.focusObject = parent
# 				del globalVars.focusAncestors[-1]
# 		super(FakeObject, self).event_loseFocus()
		

class FakeFlowingObject(FakeObject):
	"""A `FakeObject` that flows with its siblings.
	
	This is typically used as content of a `CompoundDocument`.
	"""
	
	def __init__(self, *args, startsFlow=False, endsFlow=False, **kwargs):
		super(FakeFlowingObject, self).__init__(*args, **kwargs)
		self._startsFlow = startsFlow
		self._endsFlow = endsFlow
	
	_cache_flowsFrom = False
	
	def _get_flowsFrom(self):
		if self._startsFlow:
			return None
		obj = self.previous
		if obj is not None:
			return obj
		try:
			obj = self.parent.flowsFrom
		except Exception:
			pass
		return obj
	
	_cache_flowsTo = False
	
	def _get_flowsTo(self):
		if self._endsFlow:
			return None
		obj = self.firstChild
		if obj is not None:
			return obj
		obj = self.next
		if obj is not None:
			return obj
		try:
			obj = self.parent.flowsTo
		except Exception:
			pass
		return obj
	
	def _get_indexInParent(self):
		try:
			return self.parent.children.index(self)
		except Exception:
			pass
		return super(FakeFlowingObject, self).indexInParent
	
	_cache_next = False
	
	def _get_next(self):
		return self.parent.getChild(self.indexInParent + 1)
	
	_cache_previous = False
	
	def _get_previous(self):
		return self.parent.getChild(self.indexInParent - 1)


class BaseProxy(FakeObject):
	"""Base class for objects that selectively proxy attribute access to another object.
	
	This implementation only takes care on maintaining the proxied object reference.
	"""
	
	def __init__(self, obj, *args, objPreFinalizeCallback=None, **kwargs):
		if isinstance(obj, IAccessible.IAccessible):
			self._obj = lambda args=(
				obj.event_windowHandle,
				obj.event_objectID,
				obj.event_childID
			): IAccessible.getNVDAObjectFromEvent(*args)
		elif isinstance(obj, weakref.ReferenceType):
			self._obj = obj
		else:
			self._obj = weakref.ref(obj, objPreFinalizeCallback)
		super(BaseProxy, self).__init__(*args, **kwargs)
	
	_cache_obj = False
	
	def _get_obj(self):
		return self._obj()


class ProxyContent(FakeFlowingObject, BaseProxy):
	
	def _get_TextInfo(self):
		return self.obj.TextInfo
	
	def _get_basicText(self):
		return self.obj.basicText
	
	def _get_role(self):
		return self.obj.role
	
	def _get_roleText(self):
		return self.obj.roleText
	
	def _get_roleTextBraille(self):
		return self.obj.roleTextBraille
	
	def _get_states(self):
		return self.obj.states
	
	def _get_value(self):
		return self.obj.value
	
	def makeTextInfo(self, *args, **kwargs):
		return self.obj.makeTextInfo(*args, **kwargs)
