# globalPlugins/tableHandler/virtualBuffers.py
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

import addonHandler
import api
import braille
import brailleInput
import config
import controlTypes
import eventHandler
from logHandler import log
from treeInterceptorHandler import TreeInterceptor
import ui
import vision

from . import TableHandler
from .browseMode import TABLE_MODE, TableHandlerTreeInterceptor, reportPassThrough
from .fakeObjects import FakeObject
from .fakeObjects.table import FakeTableManager, TextInfoDrivenFakeCell, TextInfoDrivenFakeRow
from .textInfos import getField
from .utils import catchAll, getObjLogInfo


try:
	REASON_CARET = controlTypes.OutputReason.CARET
	REASON_ONLYCACHE = controlTypes.OutputReason.ONLYCACHE
except AttributeError:
	# NVDA < 2021.1
	REASON_CARET = controlTypes.REASON_CARET
	REASON_ONLYCACHE = controlTypes.REASON_ONLYCACHE


# addonHandler.initTranslation()


SCRIPT_CATEGORY = "TableHandler"


class VBufTableHandler(TableHandler):
	
	def getTableManager(self, info=None, tableConfig=None, setPosition=False, force=False, **kwargs):
		ti = None
		try:
			if isinstance(info.obj, TreeInterceptor):
				ti = info.obj
			else:
				ti = info.obj.treeInterceptor
		except AttributeError:
			log.exception()
			ti = None
		if not isinstance(ti, TableHandlerTreeInterceptor):
			log.warning("Unexpected TreeInterceptor implementation (MRO={!r})".format(ti.__class__.__mro__))
			return None
		func = ti._getTableCellCoordsIncludingLayoutTables
		try:
			tableID, isLayout, rowNum, colNum, rowSpan, colSpan = func(info)
		except LookupError:
			return None
		if not tableConfig:
			# TODO: Determine TableConfig key
			tableConfig = self.getTableConfig(key="default")
		table = VBufFakeTableManager(
			#parent=self.rootNVDAObject,
			_tableConfig=tableConfig,
			tableID=tableID,
			treeInterceptor=ti,
			startPos=info,
		)
		if setPosition:
			table._currentRowNumber = rowNum
			table._currentColumnNumber = colNum
			ti._currentTable = table
			ti.passThrough = TABLE_MODE
			reportPassThrough(ti)
		return table


class VBufFakeObject(FakeObject):
	
	def _get_treeInterceptor(self):
		return self.parent.treeInterceptor
	
# 	def event_loseFocus(self):
# 		log.info(f"{self!r}.event_loseFocus", stack_info=True)
# 		import globalVars
# 		obj = globalVars.focusObject
# 		if obj is self:
# 			while isinstance(obj, FakeObject):
# 				obj = globalVars.focusAncestors.pop()
# 				log.info(f"Step up to {_getObjLogInfo(obj)}")
# 				globalVars.focusObject = obj


class VBufRootFakeObject(VBufFakeObject):
	
	def __init__(self, *args, **kwargs):
		super(VBufRootFakeObject, self).__init__(*args, **kwargs)
		self._parent = None
	
	_cache_parent = False
	
	def _get_parent(self):
		parent = None
		for obj in reversed(api.getFocusAncestors()):
			if isinstance(obj, FakeObject):
				continue
			if obj.treeInterceptor is self.treeInterceptor:
				parent = obj
				break
		if parent is None:
			# Should be a warning, but let's make it "ding" for now…
			log.error("Could not determine a suitable parent within the focus ancestry.")
			parent = self.treeInterceptor.rootNVDAObject
		
		self._parent = weakref.ref(parent)
		return parent
# 		ti = self.treeInterceptor
# 		
# 		def gen():
# 			yield ti._lastFocusObj
# 			yield eventHandler.lastQueuedFocusObject
# 			yield self._parent
# 			yield ti.rootNVDAObject
# 		
# 		for obj in gen():
# 			if obj and obj.treeInterceptor is ti:
# 				self._parent = obj
# 				return obj
	
	def _set_parent(self, value):
		if self._parent and self._parent() is value:
			# Ignoring NVDA's attempt to force-cache the parent.
			return
		# Should be a warning, but let's make it "ding" for now…
		log.error("Parent forced: parent={!r}, self={!r}".format(value, self), stack_info=True)
		self.parent = value


class VBufFakeCell(TextInfoDrivenFakeCell, VBufFakeObject):
	
	def event_gainFocus(self):
# 		log.info(f"@@@ event_gainFocus({self!r})")
		sel = self.info.copy()
		sel.collapse()
		self.treeInterceptor.selection = sel
		# Not calling super avoids `reportFocus`
		braille.handler.handleGainFocus(self)
		brailleInput.handler.handleGainFocus(self)
		vision.handler.handleGainFocus(self)


class VBufFakeRow(TextInfoDrivenFakeRow, VBufFakeObject):
	
	CellClass = VBufFakeCell


class VBufFakeTableManager(FakeTableManager, VBufRootFakeObject):
	
	RowClass = VBufFakeRow
	
	def __init__(self, *args, ti=None, startPos=None, **kwargs):
		super(VBufFakeTableManager, self).__init__(*args, ti=ti, startPos=startPos, **kwargs)
		self._cache = None
		self._lastRow = None
	
	def _get_field(self):
		info = self.startPos if self.startPos else self._currentCell.info
		return getField(info, "controlStart", role=controlTypes.ROLE_TABLE)
	
	def _get_columnCount(self):
		count = self.field.get("table-columncount")
		if isinstance(count, six.string_types):
			count = int(count)
		return count
	
	def _get_rowCount(self):
		count = self.field.get("table-rowcount")
		if isinstance(count, six.string_types):
			count = int(count)
		return count
	
	@catchAll(log)
	def getScript(self, gesture):
		func = super(VBufFakeTableManager, self).getScript(gesture)
		if func is not None:
			return func
	
	def _canCreateRow(self, rowNumber):
		return True
	
	def _iterCellsTextInfos(self, rowNumber):
		return self.treeInterceptor._iterTableCells(self.tableID, row=rowNumber)
	
	def script_disablePassThrough(self, gesture):
		self.treeInterceptor.script_disablePassThrough(gesture)
		
	script_disablePassThrough.canPropagate = True
	
	__gestures = {
		"kb:escape": "disablePassThrough"
	}
