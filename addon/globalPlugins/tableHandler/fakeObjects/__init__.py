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

# Keep compatible with Python 2
from __future__ import absolute_import, division, print_function

__version__ = "2021.11.18"
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

from ..coreUtils import getDynamicClass
from ..textInfoUtils import LaxSelectionTextInfo


addonHandler.initTranslation()


CHILD_ACCESS_GETTER = "getter"
CHILD_ACCESS_ITERATION = "iteration"
CHILD_ACCESS_SEQUENCE = "sequence"


class FakeObject(NVDAObject):
	"""Base class for NVDA objects which do not strictly correspond to a real control.
	"""

	_childAccess = CHILD_ACCESS_GETTER
	
	def __init__(self, **kwargs):
		super(FakeObject, self).__init__()
		if "children" in kwargs:
			self._childAccess = CHILD_ACCESS_SEQUENCE
		elif "firstChild" in kwargs:
			self._childAccess = CHILD_ACCESS_ITERATION
		for key, value in kwargs.items():
			setattr(self, key, value)
	
	def __del__(self):
		# TODO: Fix delayed garbage collection
		pass
	
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
	
	_cache_parent = False
	
	def _get_parent(self):
		parent = None
		focus = api.getFocusObject()
		if self is focus:
			parent = next(reversed(api.getFocusAncestors()))
		else:
			from itertools import chain
			for obj in chain((focus,), reversed(api.getFocusAncestors())):
				if isinstance(obj, FakeObject):
					continue
				parent = obj
				break
		if parent is None:
			# Should be a warning, but let's make it "ding" for now…
			log.error("Could not determine a suitable parent within the focus ancestry.")
		
		return parent
	
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
		#log.info(f"setFocus({self!r})", stack_info=True)
		eventHandler.queueEvent("gainFocus", self)
	
	def _isEqual(self, obj):
		return self is obj
