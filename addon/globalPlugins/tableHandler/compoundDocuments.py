# globalPlugins/tableHandler/compoundDocuments.py
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

"""Compound Documents
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
import compoundDocuments
import config
import controlTypes
from logHandler import log
import textInfos

from .fakeObjects import FakeFlowingObject, FakeObject


try:
	REASON_CARET = controlTypes.OutputReason.CARET
	REASON_ONLYCACHE = controlTypes.OutputReason.ONLYCACHE
except AttributeError:
	# NVDA < 2021.1
	REASON_CARET = controlTypes.REASON_CARET
	REASON_ONLYCACHE = controlTypes.REASON_ONLYCACHE


# addonHandler.initTranslation()


SCRIPT_CATEGORY = "TableHandler"



class TreeCompoundTextInfo(compoundDocuments.TreeCompoundTextInfo):
	"""A `TreeCompoundTextInfo` that presents all flowable descendants of its root object.
	
	Allows custom reporting in speech or braille of (fake) content.
	"""
	
	def expand(self, unit):
		if unit == textInfos.UNIT_STORY:
			rootObj = self.obj.rootNVDAObject
			obj = self._startObj = rootObj.firstChild
			self._start = obj.makeTextInfo(textInfos.POSITION_FIRST)
			obj = self._endObj = rootObj.lastChild
			self._end = obj.makeTextInfo(textInfos.POSITION_LAST)
			self._normalizeStartAndEnd()
			return
		super(TreeCompoundTextInfo, self).expand(unit)
	
	def getControlFieldBraille(self, field, ancestors, reportStart, formatConfig):
		if field.get("roleText") == "columnSeparator":
			presCat = field.getPresentationCategory(ancestors, formatConfig)
			field._presCat = presCat
			if reportStart:
				return "\u28b8"
		return super(TreeCompoundTextInfo, self).getControlFieldBraille(
			field, ancestors, reportStart, formatConfig
		)
	
	def getTextWithFields(self, formatConfig=None):
		fields = []
		rootObj = self.obj.rootNVDAObject
		embedIndex = None
		for info in self._getTextInfos():
			field = self._getControlFieldForObject(info.obj, ignoreEditableText=False)
			if field:
				fields.append(textInfos.FieldCommand("controlStart", field))
			if hasattr(info, "_iterTextWithEmbeddedObjects"):
				genFunc = info._iterTextWithEmbeddedObjects
			else:
				# `IA2TextTextInfo` provides an IA2-agnostic implementation.
				genFunc = IAccessible.IA2TextTextInfo._iterTextWithEmbeddedObjects.__get__(info)
			for field in genFunc(True, formatConfig=formatConfig):
				if isinstance(field, str):
					fields.append(field)
				elif isinstance(field, int): # Embedded object
					if embedIndex is None:
						embedIndex = self._getFirstEmbedIndex(info)
					else:
						embedIndex += 1
					field = info.obj.getChild(embedIndex)
					controlField = self._getControlFieldForObject(field, ignoreEditableText=False)
					controlField["content"] = field.name
					fields.extend((textInfos.FieldCommand("controlStart", controlField),
						u"\uFFFC",
						textInfos.FieldCommand("controlEnd", None)))
				else:
					fields.append(field)
			fields.append(textInfos.FieldCommand("controlEnd", None))
		return fields
	
	def _findContentDescendant(self, obj):
		return obj

	def _getControlFieldForObject(self, obj, ignoreEditableText=True):
		# Support "roleText", waiting for NVDA #11607 to be released.
		field = super(TreeCompoundTextInfo, self)._getControlFieldForObject(
			obj, ignoreEditableText=ignoreEditableText
		)
		if field is not None:
			field["roleText"] = obj.roleText
			field["roleTextBraille"] = getattr(obj, "roleTextBraille", None)
			field["_startOfNode"] = True
		return field
	
	def _getObjectPosition(self, obj):
		return super()._getObjectPosition(obj)


class CompoundDocument(compoundDocuments.CompoundDocument):
	"""A document presenting a given content.
	
	Content's element can either be strings or `NVDAObject` instances.
	Note: This implementation does not keep strong references to the `NVDAObject`
	instances it presents.
	"""	
	TextInfo = TreeCompoundTextInfo
	
	def __init__(self, parent, content):
		children = []
		if not isinstance(parent, weakref.ProxyType):
			parent = weakref.proxy(parent)
		root = FakeObject(parent=parent, children=children)
		for item in content:
			if isinstance(item, six.string_types):
				item = FakeFlowingObject(parent=weakref.proxy(root), basicText=item)
			elif isinstance(item, FakeObject):
				pass
			elif isinstance(item, NVDAObject):
				item = ProxyContent(parent=weakref.proxy(root), obj=item)
			else:
				raise TypeError("Unsupported type in content: {}".format(type(item)))
			children.append(item)
		if children:
			if isinstance(children[0], FakeFlowingObject):
				children[0]._startsFlow = True
			if isinstance(children[0], FakeFlowingObject):
				children[-1]._endsFlow = True
			for index, child in enumerate(children):
				if isinstance(child, FakeFlowingObject):
					continue
				if index > 0:
					child.flowsFrom = children[index - 1]
				if index < len(children) - 1:
					child.flowsTo = children[index + 1]
		super(CompoundDocument, self).__init__(root)
	
	def makeTextInfo(self, position):
		if position == textInfos.POSITION_SELECTION:
			position = textInfos.POSITION_FIRST
			info = super(CompoundDocument, self).makeTextInfo(position)
			# TODO: Handle selection within cells
			return info
		return super(CompoundDocument, self).makeTextInfo(position)
	
	_cache_caretObject = False
	
	def _get_caretObject(self):
		caretObj = super(CompoundDocument, self).caretObject
		rootObj = self.rootNVDAObject
		if rootObj == caretObj:
			return caretObject
		for child in rootObj.children:
			if child is caretObj:
				return caretObj
			if getattr(child, "obj", None) is caretObj:
				return child
		return caretObj
