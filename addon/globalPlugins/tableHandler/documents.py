# globalPlugins/tableHandler/documents.py
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

"""Table Mode on documents
"""

# Get ready for Python 3
from __future__ import absolute_import, division, print_function

__version__ = "2021.10.12"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

from itertools import chain
import six
import weakref

import addonHandler
import api
from baseObject import AutoPropertyObject
import braille
import brailleInput
from browseMode import BrowseModeDocumentTreeInterceptor, reportPassThrough as browseMode_reportPassThrough
import config
import controlTypes
from logHandler import log
import queueHandler
import inputCore
import scriptHandler
import speech
import textInfos
import textInfos.offsets
from treeInterceptorHandler import TreeInterceptor
import ui
import vision

from globalPlugins.withSpeechMuted import speechMuted

from . import TableHandler, getTableManager, registerTableHandler
from .coreUtils import catchAll, getDynamicClass, getObjLogInfo
from .fakeObjects import FakeObject
from .fakeObjects.table import FakeTableManager, TextInfoDrivenFakeCell, TextInfoDrivenFakeRow
from .scriptUtils import ScriptWrapper
from .textInfoUtils import getField


try:
	REASON_CARET = controlTypes.OutputReason.CARET
	REASON_CHANGE = controlTypes.OutputReason.CHANGE
	REASON_FOCUS = controlTypes.OutputReason.FOCUS
	REASON_ONLYCACHE = controlTypes.OutputReason.ONLYCACHE
except AttributeError:
	# NVDA < 2021.1
	REASON_CHANGE = controlTypes.REASON_CHANGE
	REASON_CARET = controlTypes.REASON_CARET
	REASON_FOCUS = controlTypes.REASON_FOCUS
	REASON_ONLYCACHE = controlTypes.REASON_ONLYCACHE


addonHandler.initTranslation()


SCRIPT_CATEGORY = "TableHandler"


class DocumentTableHandler(TableHandler):
	
	def getTableConfigKey(self, info=None, tableCellCoords=None, **kwargs):
		ti = self.__getTreeInterceptor(info)
		if not isinstance(ti, TableHandlerTreeInterceptor):
			log.warning("Unexpected TreeInterceptor implementation (MRO={!r})".format(ti.__class__.__mro__))
			return None
		if not tableCellCoords:
			try:
				tableCellCoords = ti._getTableCellCoordsIncludingLayoutTables(info)
			except LookupError:
				return None
			return self.getTableConfigKey(info=info, tableCellCoords=tableCellCoords, **kwargs)
		# TODO: Column headers sequence
		return super(DocumentTableHandler, self).getTableConfigKey(
			info=info, tableCellCoords=tableCellCoords, **kwargs
		)
	
	def getTableManager(
		self,
		info=None,
		tableCellCoords=None,
		tableConfigKey=None,
		tableConfig=None,
		setPosition=False,
		force=False,
		**kwargs
	):
		ti = self.__getTreeInterceptor(info)
		if not isinstance(ti, TableHandlerTreeInterceptor):
			log.warning("Unexpected TreeInterceptor implementation (MRO={!r})".format(ti.__class__.__mro__))
			return None
		if not tableCellCoords:
			func = ti._getTableCellCoordsIncludingLayoutTables
			try:
				tableCellCoords = func(info)
			except LookupError:
				return None
			return self.getTableManager(
				info=info,
				tableCellCoords=tableCellCoords,
				tableConfigKey=tableConfigKey,
				tableConfig=tableConfig,
				setPosition=setPosition,
				force=force,
				**kwargs
			)
		tableID, isLayout, rowNum, colNum, rowSpan, colSpan = tableCellCoords
		if not tableConfig:
			if not tableConfigKey:
				tableConfigKey = self.getTableConfigKey(
					info=info, tableCellCoords=tableCellCoords, **kwargs
				)
			tableConfig = self.getTableConfig(tableConfigKey)
		table = DocumentTableManager(
			_tableConfig=tableConfig,
			tableID=tableID,
			ti=ti,
			parent=ti.rootNVDAObject,
			startPos=info,
		)
		if setPosition:
			table._currentRowNumber = rowNum
			table._currentColumnNumber = colNum
		#log.info(f"new position {info._startOffset if info else None}, ({rowNum}, {colNum}), {setPosition}, -({table._currentRowNumber}, {table._currentColumnNumber})")
		return table
	
	def __getTreeInterceptor(self, info):
		if isinstance(self, TreeInterceptor):
			return self
		if not info:
			return None
		try:
			if isinstance(info.obj, TreeInterceptor):
				return info.obj
			else:
				return info.obj.treeInterceptor
		except AttributeError:
			log.exception()


class TableMode(object):
	"""Used to represent Table Mode as an alternative value of `TreeInterceptor.passThrough`
	
	See `TABLE_MODE`.
	"""
	
	def __bool__(self):
		# Mostly considered as Browse Mode
		return False
	
	def __repr__(self):
		return "<TableMode>"


TABLE_MODE = TableMode()
REASON_TABLE_MODE = "tableMode"


def reportPassThrough(treeInterceptor, onlyIfChanged=True):
	if treeInterceptor.passThrough == TABLE_MODE:
		if browseMode_reportPassThrough.last is not treeInterceptor.passThrough:
			# Translators: Announced when switching to Table Mode
			speech.speakMessage(_("Table Mode"))
		browseMode_reportPassThrough.last = treeInterceptor.passThrough
		return
	browseMode_reportPassThrough(treeInterceptor, onlyIfChanged=onlyIfChanged)


class TableHandlerDocument(AutoPropertyObject):
	"""Integrate Table UX into a document.
	
	This class is intended to be used as an overlay to an `NVDAObject` with role document.
	"""
	
	def _get_treeInterceptorClass(self):
		# Might raise NotImplementedError on purpose.
		superCls = super(TableHandlerDocument, self).treeInterceptorClass
		if not issubclass(superCls, BrowseModeDocumentTreeInterceptor):
			return superCls
		return getDynamicClass((TableHandlerTreeInterceptor, superCls))


class TableHandlerTreeInterceptorScriptWrapper(ScriptWrapper):
	
	def __init__(self, ti, script, **defaults):
		defaults.setdefault("disableTableModeBefore", True)
		defaults.setdefault("tryTableModeAfterIfBrowseMode", False)
		defaults.setdefault("enableTableModeAfter", False)
		defaults.setdefault("restoreTableModeAfter", False)
		defaults.setdefault("restoreTableModeAfterIfBrowseMode", False)
		defaults.setdefault("restoreTableModeAfterIfNotMoved", True)
		super(TableHandlerTreeInterceptorScriptWrapper, self).__init__(
			script, override=self.override, **defaults
		)
		# NVDA Input Help looks for this attribute
		self.__self__ = ti
	
	def override(self, gesture, script=None, **kwargs):
		disableTableModeBefore = self.disableTableModeBefore
		enableTableModeAfter = self.enableTableModeAfter
		tryTableModeAfterIfBrowseMode = self.tryTableModeAfterIfBrowseMode
		restoreTableModeAfter = self.restoreTableModeAfter
		restoreTableModeAfterIfBrowseMode = self.restoreTableModeAfterIfBrowseMode
		restoreTableModeAfterIfNotMoved = self.restoreTableModeAfterIfNotMoved
		
		ti = self.__self__
		focus = api.getFocusObject()
		if isinstance(focus, DocumentFakeCell):
			cell = focus
			if not hasattr(ti, "_speakObjectTableCellChildrenPropertiesCache"):
				ti._speakObjectTableCellChildrenPropertiesCache = {}
			cache = ti._speakObjectTableCellChildrenPropertiesCache
			cache.clear()
			
			def cacheChildrenProperties(obj):
				for obj in obj.children:
					speech.speakObjectProperties(obj, states=True, reason=REASON_ONLYCACHE)
					cache[obj.IA2UniqueID] = obj._speakObjectPropertiesCache
					cacheChildrenProperties(obj)
			
			cacheChildrenProperties(cell)
			#log.info(f"cached as {ti.selection._startOffset} by {self.__name__}: {cell.rowNumber, cell.columnNumber} {cache!r}", stack_info=True)
		
		if not any((
			disableTableModeBefore,
			enableTableModeAfter,
			tryTableModeAfterIfBrowseMode,
			restoreTableModeAfter,
			restoreTableModeAfterIfBrowseMode,
			restoreTableModeAfterIfNotMoved
		)):
			script(gesture, **kwargs)
			return
		
		passThroughBefore = ti.passThrough
		tableModeBefore = passThroughBefore == TABLE_MODE
		if tableModeBefore and disableTableModeBefore:
			ti.passThrough = False
		checkRestore = tableModeBefore and any((
			restoreTableModeAfter, restoreTableModeAfterIfBrowseMode, restoreTableModeAfterIfNotMoved
		))
		if checkRestore:
			before = ti.selection.copy()
		script(gesture, **kwargs)
		
		if not any((tryTableModeAfterIfBrowseMode, enableTableModeAfter, checkRestore)):
			return
		
		def trailer():
			passThrough = ti.passThrough
			if passThrough == TABLE_MODE:
				return
			if not enableTableModeAfter and tryTableModeAfterIfBrowseMode:
				try:
					ti.passThrough = TABLE_MODE
				except Exception:
					return
				queueHandler.queueFunction(queueHandler.eventQueue, reportPassThrough, ti)
				return
			
			if enableTableModeAfter or (tableModeBefore and (
				restoreTableModeAfter
				or (restoreTableModeAfterIfBrowseMode and not passThrough)
			)):
				ti.passThrough = TABLE_MODE
				queueHandler.queueFunction(queueHandler.eventQueue, reportPassThrough, ti)
				return
			if tableModeBefore and restoreTableModeAfterIfNotMoved:
				after = ti.selection.copy()
				if (
					before.compareEndPoints(after, "startToStart") == 0
					and before.compareEndPoints(after, "endToEnd") == 0
				):
					#log.info(f"No movement, restoring TABLE_MODE ({before._startOffset} / {after._startOffset}")
					#ti.passThrough = TABLE_MODE
					queueHandler.queueFunction(
						queueHandler.eventQueue, setattr, ti, "passThrough", TABLE_MODE
					)
					queueHandler.queueFunction(queueHandler.eventQueue, reportPassThrough, ti)
					return
		
		queueHandler.queueFunction(queueHandler.eventQueue, trailer)


class TableHandlerTreeInterceptor(BrowseModeDocumentTreeInterceptor, DocumentTableHandler):
	"""Integrate Table UX into a `BrowseModeDocumentTreeInterceptor`.
	""" 
	
	def __init__(self, rootNVDAObject):
		super(TableHandlerTreeInterceptor, self).__init__(rootNVDAObject)
		
		self.autoTableMode = False
		self._tableManagers = {}
		self._currentTable = None
		registerTableHandler(weakref.ref(self))
	
	def __getattribute__(self, name):
		value = super(TableHandlerTreeInterceptor, self).__getattribute__(name)
		if name.startswith("script_") and not isinstance(
			value, TableHandlerTreeInterceptorScriptWrapper
		):
			return TableHandlerTreeInterceptorScriptWrapper(self, value)
		return value
	
	def _set_passThrough(self, state):
		if self._passThrough == state:
			return
		#log.info(f"_set_passThrough({state}) was {self._passThrough}", stack_info=True)
		if state == TABLE_MODE:
			table = self._currentTable
			if table is not None:
				#table._setPosition(self.selection)
				table._setPosition(self.makeTextInfo(textInfos.POSITION_SELECTION))
			else:
				table = self._currentTable = self.getTableManager(
					#info=self.selection,
					info=self.makeTextInfo(textInfos.POSITION_SELECTION),
					setPosition=True,
					force=True
				)
				if table is None:
					raise Exception("No table at current position")
			self._passThrough = state
			queueHandler.queueFunction(queueHandler.eventQueue, table.setFocus)
			return
		if self.passThrough == TABLE_MODE:
			self._passThrough = None
			api.setFocusObject(self._currentTable.parent)
		super(TableHandlerTreeInterceptor, self)._set_passThrough(state)
	
	def _set_selection(self, info, reason=REASON_CARET):
		#log.info(f"_set_selection({info._startOffset}, {reason})")
		#log.info(f"_set_selection({info}, reason={reason!r})", stack_info=True)
		if reason == REASON_TABLE_MODE:
			#with speechMuted():
			super(TableHandlerTreeInterceptor, self)._set_selection(info, reason=REASON_CARET)
			return
		prevTable = self._currentTable
		try:
			super(TableHandlerTreeInterceptor, self)._set_selection(info, reason=reason)
		except Exception:
			log.exception("_set_selection({!r}, {!r})".format(info, reason))
			raise

		def set_selection_trailer():
			table = self._currentTable = self.getTableManager(info=info, setPosition=True)
			if table:
				if False and not (reason == REASON_FOCUS and self.passThrough is False) and table != prevTable and (
					not table
					or not prevTable
					or table.tableID != prevTable.tableID 
				):
					self.passThrough = TABLE_MODE
					queueHandler.queueFunction(queueHandler.eventQueue, reportPassThrough, self)
			elif self.passThrough == TABLE_MODE:
				self.passThrough = False
				queueHandler.queueFunction(queueHandler.eventQueue, reportPassThrough, self)
		
		queueHandler.queueFunction(queueHandler.eventQueue, set_selection_trailer)
	
	def getBrailleRegions(self, review=False):
		if self.passThrough == TABLE_MODE:
			if self._currentTable is not None:
				cell = self._currentTable._currentCell
				if cell is not None:
					return cell.getBrailleRegions(review=review)
				# TODO: Handle braille reporting of empty tables
		return super(TableHandlerTreeInterceptor, self).getBrailleRegions(review=review)
	
	@catchAll(log)
	def getAlternativeScript(self, gesture, script):
		script = super(TableHandlerTreeInterceptor, self).getAlternativeScript(gesture, script)
		if script is not None and not isinstance(script, TableHandlerTreeInterceptorScriptWrapper):
			script = TableHandlerTreeInterceptorScriptWrapper(self, script)
		return script
	
	@catchAll(log)
	def getScript(self, gesture):
		if self.passThrough == TABLE_MODE:
			table = self._currentTable
			if table is not None:
				cell = table._currentCell
				if cell is not None:
					func = cell.getScript(gesture)
					if func is not None:
						return func
				row = table._currentRow
				if row is not None:
					func = row.getScript(gesture)
					if func is not None:
						return func
				func = table.getScript(gesture)
				if func is not None:
					return func
		func = super(TableHandlerTreeInterceptor, self).getScript(gesture)
		if func is not None and not isinstance(func, TableHandlerTreeInterceptorScriptWrapper):
			func = TableHandlerTreeInterceptorScriptWrapper(self, func)
		return func
	
	def getTableManager(self, tableCellCoords=None, setPosition=False, refresh=False, **kwargs):
		#log.info(f"getTableManager(tableCellCoords={tableCellCoords!r}, setPosition={setPosition!r}, refresh={refresh!r}, kwargs={kwargs!r})")
		if tableCellCoords:
			tableID, isLayout, rowNum, colNum, rowSpan, colSpan = tableCellCoords
			if not refresh:
				table = self._tableManagers.get(tableID)
				if table:
					return table
		table = super(TableHandlerTreeInterceptor, self).getTableManager(
			tableCellCoords=tableCellCoords, setPosition=setPosition, refresh=refresh, **kwargs
		)
		if table:
			self._tableManagers[table.tableID] = table
		if setPosition and tableCellCoords and rowNum is not None and colNum is not None:
			table._currentRowNumber = rowNum
			table._currentColumnNumber = colNum
		return table
	
	def makeTextInfo(self, position):
		if isinstance(position, FakeObject):
			return position.makeTextInfo(position)
		return super(TableHandlerTreeInterceptor, self).makeTextInfo(position)
	
# 	def _focusLastFocusableObject(self, activatePosition=False):
# 		"""Used when auto focus focusable elements is disabled to sync the focus
# 		to the browse mode cursor.
# 		When auto focus focusable elements is disabled, NVDA doesn't focus elements
# 		as the user moves the browse mode cursor. However, there are some cases
# 		where the user always wants to interact with the focus; e.g. if they press
# 		the applications key to open the context menu. In these cases, this method
# 		is called first to sync the focus to the browse mode cursor.
# 		"""
# 		#if activatePosition: # and self.passThrough == TABLE_MODE:
# 		with speechMuted():
# 			return super(TableHandlerTreeInterceptor, self)._focusLastFocusableObject(activatePosition=activatePosition)
# 		obj = self.currentFocusableNVDAObject
# 		#log.info(f"currentFocusableNVDAObject={getObjLogInfo(obj)}")
# 		if obj!=self.rootNVDAObject and self._shouldSetFocusToObj(obj) and obj!= api.getFocusObject():
# 			obj.setFocus()
# 			if api.getFocusObject() is not obj:
# 				api.setFocusObject(obj)
# 			# We might be about to activate or pass through a key which will cause
# 			# this object to change (e.g. checking a check box). However, we won't
# 			# actually get the focus event until after the change has occurred.
# 			# Therefore, we must cache properties for speech before the change occurs.
# 			speech.speakObject(obj, REASON_ONLYCACHE)
# 			self._objPendingFocusBeforeActivate = obj
# 		if activatePosition:
# 			# Make sure we activate the object at the caret, which is not necessarily focusable.
# 			self._activatePosition()
	
	def _getTableCellCoordsIncludingLayoutTables(self, info):
		"""
		Fetches information about the deepest table cell at the given position.
		Derived from `DocumentWithTableNavigation._getTableCellAt` to never exclude layout tables.
		@param info:  the position where the table cell should be looked for.
		@type info: L{textInfos.TextInfo}
		@returns: a tuple of table ID, is layout, row number, column number, row span, and column span.
		@rtype: tuple
		@raises: LookupError if there is no table cell at this position.
		"""
		if info.isCollapsed:
			info = info.copy()
			info.expand(textInfos.UNIT_CHARACTER)
		fields = list(info.getTextWithFields())
		layoutIDs = set()
		if not config.conf["documentFormatting"]["includeLayoutTables"]:
			for field in fields:
				if isinstance(field, textInfos.FieldCommand) and field.command == "controlStart" and field.field.get('table-layout'):
					tableID = field.field.get('table-id')
					if tableID is not None:
						layoutIDs.add(tableID)
		for field in reversed(fields):
			if not (isinstance(field, textInfos.FieldCommand) and field.command == "controlStart"):
				# Not a control field.
				continue
			attrs = field.field
			tableID=attrs.get('table-id')
			# if tableID is None or tableID in layoutIDs:
			#	continue
			#if "table-columnnumber" in attrs and not attrs.get('table-layout'):
			if tableID is not None:
				break
		else:
			raise LookupError("Not in a table cell")
		return (
			tableID,
			tableID in layoutIDs,
			attrs.get("table-rownumber"),
			attrs.get("table-columnnumber"),
			attrs.get("table-rowsspanned", 1),
			attrs.get("table-columnsspanned", 1)
		)
	
	def _handleUpdate(self):
		#log.warning(f"_handleUpdate {self.selection._startOffset} {self.passThrough!r}")		
		super(TableHandlerTreeInterceptor, self)._handleUpdate()
		if self.passThrough != TABLE_MODE:
			return
		table = self.getTableManager(info=self.selection, setPosition=True, refresh=True)
		if table:
			cell = table._currentCell
			cache = getattr(cell.table.ti, "_speakObjectTableCellChildrenPropertiesCache", {})
			#log.info(f"REASON_CHANGE {cell.rowNumber, cell.columnNumber} {cache!r}")
			
			def speakChildrenPropertiesChange(obj):
				for obj in obj.children:
					obj._speakObjectPropertiesCache = cache.get(obj.IA2UniqueID, {})
					speech.speakObjectProperties(obj, states=True, reason=REASON_CHANGE)
					cache[obj.IA2UniqueID] = obj._speakObjectPropertiesCache
					#log.info(f"after update: {obj.IA2UniqueID}: {obj._speakObjectPropertiesCache}")
					speakChildrenPropertiesChange(obj)
			
			if cache:
				speakChildrenPropertiesChange(cell)

			focus = api.getFocusObject()
			if isinstance(focus, DocumentFakeCell) or focus.treeInterceptor is self:
				table.setFocus()
	
	def _loadBufferDone(self, success=True):
		#log.warning(f"_loadBufferDone({success})")
		super(TableHandlerTreeInterceptor, self)._loadBufferDone(success=success)
		self._tableManagers.clear()
	
	def event_documentLoadComplete(self, *args, **kwargs):
		#log.warning(f"event_documentLoadComplete({args}, {kwargs})")
		getattr(
			super(TableHandlerTreeInterceptor, self),
			"event_documentLoadComplete",
			lambda *args, **kwargs: None
		)(*args, **kwargs)
		self._tableManagers.clear()
	
	def _event_gainFocus(self, obj, nextHandler):
		if self.passThrough == TABLE_MODE:
			if isinstance(obj, FakeObject):
				with speechMuted():
					nextHandler()
				return
			else:
				log.warning(
					"Received, while in Table Mode, a gainFocus event for {!r}".format(obj)
				)
				# TODO: Support "focus follows caret"
				table = self._currentTable
				if table:
					table.setFocus()
					return
		if isinstance(obj, FakeObject):
			log.warning("event_gainFocus({!r}, {!r})".format(obj, nextHandler))
			with speechMuted():
				nextHandler()
			return
		super(TableHandlerTreeInterceptor, self).event_gainFocus(obj, nextHandler)
		if hasattr(obj, "_speakObjectPropertiesCache") and hasattr(self, "_speakObjectTableCellChildrenPropertiesCache"):
			cache = self._speakObjectTableCellChildrenPropertiesCache
			if obj.IA2UniqueID in cache:
				cache[obj.IA2UniqueID] = obj._speakObjectPropertiesCache
		
# 	def script_activatePosition(self, gesture):
# 		log.info(f"script_activatePosition - sel={self.selection._startOffset} - passThrough={self.passThrough}")
# 		super(TableHandlerTreeInterceptor, self).script_activatePosition(gesture)
# 	
# 	script_activatePosition.__dict__.update(
# 		BrowseModeDocumentTreeInterceptor.script_activatePosition.__dict__
# 	)
	
	def event_stateChange(self, obj, nextHandler):
		#log.warning(f"event_stateChanged({args}, {kwargs})")
		if self.passThrough == TABLE_MODE:
			# Handled in `_handleUpdate`
			return
		func = getattr(super(TableHandlerTreeInterceptor, self), "event_stateChange", None)
		if func:
			func(obj, nextHandler)
		else:
			nextHandler()
	
	def script_nextColumn(self, gesture):
		if self.passThrough == TABLE_MODE:
			# Translators: A tutor message
			ui.message(_("In table mode, use arrows to navigate table cells."))
			return
		super(BrowseModeDocumentTreeInterceptor, self).script_nextColumn(gesture)
	
	script_nextColumn.__dict__.update(
		BrowseModeDocumentTreeInterceptor.script_nextColumn.__dict__
	)
	script_nextColumn.disableTableModeBefore = False
	
	def script_previousColumn(self, gesture):
		if self.passThrough == TABLE_MODE:
			# Translators: A tutor message
			ui.message(_("In table mode, use arrows to navigate table cells."))
			return
		super(BrowseModeDocumentTreeInterceptor, self).script_previousColumn(gesture)
	
	script_previousColumn.__dict__.update(
		BrowseModeDocumentTreeInterceptor.script_previousColumn.__dict__
	)
	script_previousColumn.disableTableModeBefore = False
	
	def script_nextRow(self, gesture):
		if self.passThrough == TABLE_MODE:
			# Translators: A tutor message
			ui.message(_("In table mode, use arrows to navigate table cells."))
			return
		super(BrowseModeDocumentTreeInterceptor, self).script_nextRow(gesture)
	
	script_nextRow.__dict__.update(
		BrowseModeDocumentTreeInterceptor.script_nextRow.__dict__
	)
	script_nextRow.disableTableModeBefore = False
	
	def script_previousRow(self, gesture):
		if self.passThrough == TABLE_MODE:
			# Translators: A tutor message
			ui.message(_("In table mode, use arrows to navigate table cells."))
			return
		super(BrowseModeDocumentTreeInterceptor, self).script_previousRow(gesture)
	
	script_previousRow.__dict__.update(
		BrowseModeDocumentTreeInterceptor.script_previousRow.__dict__
	)
	script_previousRow.disableTableModeBefore = False
	
	def script_nextTable(self, gesture):
		if self.passThrough is False and self._currentTable:
			self.passThrough = TABLE_MODE
			queueHandler.queueFunction(queueHandler.eventQueue, reportPassThrough, self)
			return
		bookmark = self.selection.bookmark
		with speechMuted(retains=True) as ctx:
			super(TableHandlerTreeInterceptor, self).script_nextTable(gesture)
		
		def nextTable_trailer():
			try:
				self.passThrough = TABLE_MODE
			except Exception:
				pass
			queueHandler.queueFunction(queueHandler.eventQueue, reportPassThrough, self)
			if bookmark == self.selection.bookmark:
				# No movement, quick-nav failed, speak the failure announce
				ctx.speakMuted()
		
		queueHandler.queueFunction(queueHandler.eventQueue, nextTable_trailer)
	
	script_nextTable.__dict__.update(BrowseModeDocumentTreeInterceptor.script_nextTable.__dict__)
	script_nextTable.disableTableModeBefore = False
	
	def script_previousTable(self, gesture):
		bookmark = self.selection.bookmark
		with speechMuted(retains=True) as ctx:
			super(TableHandlerTreeInterceptor, self).script_previousTable(gesture)
		
		def previousTable_trailer():
			try:
				self.passThrough = TABLE_MODE
			except Exception:
				pass
			queueHandler.queueFunction(queueHandler.eventQueue, reportPassThrough, self)
			if bookmark == self.selection.bookmark:
				# No movement, quick-nav failed, speak the failure announce
				ctx.speakMuted()
		
		queueHandler.queueFunction(queueHandler.eventQueue, previousTable_trailer)
	
	script_previousTable.__dict__.update(BrowseModeDocumentTreeInterceptor.script_previousTable.__dict__)
	script_previousTable.disableTableModeBefore = False


class DocumentFakeObject(FakeObject):
	
	def _get_treeInterceptor(self):
		return None
	
	def _set_treeInterceptor(self, value):
		# Defeats NVDA's attempts with IE11 to set a TreeInterceptor
		pass


class DocumentFakeCell(TextInfoDrivenFakeCell, DocumentFakeObject):
	
	def event_gainFocus(self):
		#log.info(f"event_gainFocus({self!r}) - before: {self.table.ti.selection._startOffset}")
		renewed = self.row._getCell(self.columnNumber, refresh=True)
		self.__dict__ = renewed.__dict__.copy()
		sel = self.info.copy()
		sel.collapse()
		table = self.table
		table.ti._set_selection(sel, reason=REASON_TABLE_MODE)
		table._currentRowNumber = self.rowNumber
		table._currentColumnNumber = self.columnNumber
		super(DocumentFakeCell, self).event_gainFocus()
		#log.info(f"event_gainFocus({self!r}) - after: {self.table.ti.selection._startOffset}")


class DocumentFakeRow(TextInfoDrivenFakeRow, DocumentFakeObject):
	
	CellClass = DocumentFakeCell


class DocumentRootFakeObject(DocumentFakeObject):
	
	def __init__(self, *args, ti=None, **kwargs):
		super(DocumentRootFakeObject, self).__init__(*args, ti=ti, **kwargs)
		self._parent = None
	
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
				if obj.treeInterceptor is self.ti:
					parent = obj
				break
		if parent is None:
			# Should be a warning, but let's make it "ding" for now…
			log.error("Could not determine a suitable parent within the focus ancestry.")
			parent = self.ti.rootNVDAObject
		
		self._parent = weakref.ref(parent)
		self.ti = parent.treeInterceptor
		return parent
	
	def _set_parent(self, value):
		if self._parent and self._parent() is value:
			# Ignoring NVDA's attempt to force-cache the parent.
			return
		# Should be a warning, but let's make it "ding" for now…
		log.error("Parent forced: parent={!r}, self={!r}".format(value, self), stack_info=True)
		self.ti = value.treeInterceptor
		self.parent = value


class DocumentTableManager(FakeTableManager, DocumentFakeObject):
	
	RowClass = DocumentFakeRow
	
	def __init__(self, *args, ti=None, startPos=None, **kwargs):
		super(DocumentTableManager, self).__init__(*args, ti=ti, startPos=startPos, **kwargs)
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
	
	def _get__firstDataCell(self):
		#log.info("_get__firstDataCell")
		tableID = self.tableID
		for info in self.ti._iterTableCells(tableID, startPos=None):
			field = getField(info, "controlStart", role=controlTypes.ROLE_TABLECELL)
			if field:
				rowNum = field.get("table-rownumber")
				colNum = field.get("table-columnnumber")
				if (
					rowNum is not None and rowNum != self._tableConfig.columnHeaderRowNumber
					and colNum is not None and colNum != self._tableConfig.rowHeaderColumnNumber
				):
					cell = self._getCell(rowNum, colNum)
					return cell
				continue
	
	@catchAll(log)
	def getScript(self, gesture):
		if hasattr(gesture, "__BrowseModeFakeTableManager"):
			return None
		func = super(DocumentTableManager, self).getScript(gesture)
		if func is not None:
			return func
		setattr(gesture, "__BrowseModeFakeTableManager", None)  # Avoid recursion
		
		# From `scriptHandler.findScript`
		globalMapScripts = []
		globalMaps = [inputCore.manager.userGestureMap, inputCore.manager.localeGestureMap]
		globalMap = braille.handler.display.gestureMap
		if globalMap:
			globalMaps.append(globalMap)
		for globalMap in globalMaps:
			for identifier in gesture.normalizedIdentifiers:
				globalMapScripts.extend(globalMap.getScriptsForGesture(identifier))
		ti = self.ti
		func = scriptHandler._getObjScript(ti, gesture, globalMapScripts)
		if func is not None:
			func = ti.getAlternativeScript(gesture, func)
		if func is not None:
			func.canPropagate = True
			return func
	
	def _canCreateRow(self, rowNumber):
		return True
	
	def _iterCellsTextInfos(self, rowNumber):
		return self.ti._iterTableCells(self.tableID, row=rowNumber)
	
	def _setPosition(self, info):
		#log.info(f"_setPosition({info._startOffset})")
		func = self.ti._getTableCellCoordsIncludingLayoutTables
		tableID = None
		try:
			tableID, isLayout, rowNum, colNum, rowSpan, colSpan = func(info)
		except LookupError:
			pass
		if tableID is None or tableID != self.tableID:
			raise ValueError("The given position is not inside this table")
		cell = None
		if rowNum is not None and colNum is not None:
			self._currentRowNumber = rowNum
			self._currentColumnNumber = colNum
			cell = self._currentCell
			#log.info(f"_setPosition({info._startOffset}): ({rowNum}, {colNum})")
		if cell and cell.role == controlTypes.ROLE_TABLECELL:
			return
		cell = self._firstDataCell
		if cell:
			self._currentRowNumber = cell.rowNumber
			self._currentColumnNumber = cell.columnNumber
			#log.info(f"_setPosition({info._startOffset}): first ({rowNum}, {colNum})")
			return
		raise ValueError("Table empty?")
	
	def script_disableTableMode(self, gesture):
		ti = self.ti
		if ti.passThrough == TABLE_MODE:
			ti.passThrough = False
			reportPassThrough(ti)
			return
		self.ti.script_disablePassThrough(gesture)
		
	script_disableTableMode.canPropagate = True
	script_disableTableMode.restoreTableModeAfterIfNotMoved = False
	
	__gestures = {
		"kb:escape": "disableTableMode"
	}
