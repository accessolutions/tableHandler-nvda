# globalPlugins/tableHandler/documents.py
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

"""Table Mode on documents
"""

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


from abc import abstractmethod
from collections import namedtuple
from itertools import chain
import os.path
import weakref

import NVDAObjects
import addonHandler
import api
from baseObject import AutoPropertyObject
import braille
import brailleInput
from browseMode import BrowseModeDocumentTreeInterceptor, reportPassThrough as browseMode_reportPassThrough
import config
import controlTypes
import eventHandler
from logHandler import log
import inputCore
import nvwave
import scriptHandler
import speech
import textInfos
from treeInterceptorHandler import TreeInterceptor
import ui
from virtualBuffers import VirtualBuffer
import vision

from globalPlugins.withSpeechMuted import speechMuted

from . import TableHandler, getTableConfig, getTableConfigKey, getTableManager, setDefaultTableKwargs
from .coreUtils import Break, catchAll, getDynamicClass, queueCall
from .fakeObjects import FakeObject
from .fakeObjects.table import (
	FakeTableManager,
	ResizingCell,
	TextInfoDrivenFakeCell,
	TextInfoDrivenFakeRow
)
from .scriptUtils import ScriptWrapper, overrides
from .tableUtils import iterVirtualBufferTableCellsSafe
from .textInfoUtils import getField


addonHandler.initTranslation()


DEBUG_MODE = False
SCRIPT_CATEGORY = "TableHandler"


TableCellCoords = namedtuple(
	"TableCellCoords",
	("tableID", "isLayout", "rowNum", "colNum", "rowSpan", "colSpan")
)


class DocumentTableHandler(TableHandler):
	
	def getTableConfigKey(self, nextHandler, **kwargs):
		"""Retrieve a key based on the column headers
		
		This implementation targets well-formed tables (layout or not).
		It creates a temporary default TableManager in order to fetch the headers.
		If no headers are defined, it considers as headers the basic text of the
		first row.
		If it fails, it returns the result of the next handler (which is
		normally the key of the default configuration: "")
		"""
		if kwargs.get("debug"):
			log.info(f">>> DTH.getTableConfigKey({kwargs})")
		try:
			kwargs["key"] = ""
			if kwargs.get("debug"):
				log.info(f"DTH.getTableConfigKey - Retrieve default TM")
			table = getTableManager(**kwargs)
			if kwargs.get("debug"):
				log.info(f"DTH.getTableConfigKey - Default TM: {table}")
			if not table:
				raise Break
			table.__dict__.setdefault("_trackingInfo", []).append("DTH.getTableConfigKey")
			cell = table._firstDataCell
			if not cell:
				del cell, table
				raise Break
			row = cell.row
			headers = [cell.columnHeaderText for colNum, colSpan, cell in row._iterCells()]
			if any(headers):
				del cell, row, table
				key = {"columnHeaders": headers}
				if kwargs.get("debug"):
					log.info(f"<<< DTH.getTableConfigKey: {key}")
				return key
			row = table._getRow(1)
			if not row:
				del cell, row, table
				raise Break
			headers = [cell.basicText for colNum, colSpan, cell in row._iterCells()]
			if any(headers):
				del cell, row, table
				key = {"columnHeaders": headers}
				if kwargs.get("debug"):
					log.info(f"<<< DTH.getTableConfigKey: {key}")
				return key
		except Break:
			pass
		except Exception:
			log.exception(f"getTableConfigKey(kwargs={kwargs!r})", stack_info=True)
			raise
		if kwargs.get("debug"):
			log.info(f"DTH.getTableConfigKey - Next handler")
		key = nextHandler(**kwargs)
		if kwargs.get("debug"):
			log.info(f"<<< DTH.getTableConfigKey: {key} (From next handler)")
		return key
	
	def getTableManager(self, nextHandler, **kwargs):
		"""Retrieve a TableManager for the given table ID.
		"""
		if kwargs.get("debug"):
			log.info(f">>> DTH.getTableManager({kwargs})")
		
		tableID = kwargs.get("tableID")
		if tableID is None:
			if kwargs.get("debug"):
				log.info(f"<<< DTH.getTableManager: None (no tableID)")
			return None
		cfg = kwargs.get("cfg")
		if cfg is None:
			cfg = getTableConfig(**kwargs)
		ti = kwargs["ti"]
		table = kwargs.get("tableManagerClass", DocumentTableManager)(
			_tableConfig=cfg,
			tableID=kwargs["tableID"],
			ti=ti,
			parent=ti.rootNVDAObject,
			startPos=kwargs["info"],
		)
		if kwargs.get("setPosition"):
			rowNum = kwargs.get("rowNum")
			colNum = kwargs.get("colNum")
			if rowNum is not None:
				table._currentRowNumber = rowNum
			elif DEBUG_MODE:
				log.error("setPosition: Unspecified row number")
			if colNum is not None:
				table._currentColumnNumber = colNum
			elif DEBUG_MODE:
				log.error("setPosition: Unspecified column number")
			table._currentRowNumber = rowNum
			table._currentColumnNumber = colNum
		if kwargs.get("debug"):
			log.info(f"<<< DTH.getTableManager: {table}")
		return table
	
# 	def __getTreeInterceptor(self, info):
# 		if isinstance(self, TreeInterceptor):
# 			return self
# 		if not info:
# 			return None
# 		try:
# 			if isinstance(info.obj, TreeInterceptor):
# 				return info.obj
# 			else:
# 				return info.obj.treeInterceptor
# 		except AttributeError:
# 			log.exception()


class PassThrough:
	"""Used to represent alternative values for `TreeInterceptor.passThrough`
	
	See `TABLE_MODE`.
	"""
	
	def __init__(self, name, bool):
		self.name = name
		self.bool = bool
	
	def __bool__(self):
		return self.bool
	
	def __repr__(self):
		return self.name


TABLE_MODE = PassThrough("<TableMode>", False)
BROWSE_MODE_FROM_TABLE_MODE = PassThrough("<BrowseModeFromTableMode>", False)
FOCUS_MODE_FROM_TABLE_MODE = PassThrough("<FocusModeFromTableMode>", True)

REASON_TABLE_MODE = "tableMode"


def reportPassThrough(treeInterceptor, onlyIfChanged=True):
	if treeInterceptor.passThrough == TABLE_MODE:
		if browseMode_reportPassThrough.last is not treeInterceptor.passThrough:
			if config.conf["virtualBuffers"]["passThroughAudioIndication"]:
				filePath = os.path.join(os.path.dirname(__file__), r"..\..\waves", "tableMode.wav")
				if os.path.isfile(filePath):
					nvwave.playWaveFile(filePath)
				elif not getattr(reportPassThrough, "missingTableModeWaveFileLogged", False):
					try:
						filePath = os.path.realpath(filePath)
					except Exception:
						pass
					log.error("Missing wave file: {}".format(filePath))
					reportPassThrough.missingTableModeWaveFileLogged = True
			else:
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
		superCls = super().treeInterceptorClass
		if issubclass(superCls, VirtualBuffer):
			return getDynamicClass((TableHandlerVirtualBuffer, superCls))
		elif issubclass(superCls, BrowseModeDocumentTreeInterceptor):
			# See DocumentTableManager._iterCellsTextInfos
			#return getDynamicClass((TableHandlerBmdti, superCls))
			pass
		return superCls


class TableHandlerBmdtiScriptWrapper(ScriptWrapper):
	
	def __init__(self, ti, script, **defaults):
		defaults.setdefault("disableTableModeBefore", True)
		defaults.setdefault("tryTableModeAfterIfBrowseMode", False)
		defaults.setdefault("enableTableModeAfter", False)
		defaults.setdefault("restoreTableModeAfter", False)
		defaults.setdefault("restoreTableModeAfterIfBrowseMode", False)
		defaults.setdefault("restoreTableModeAfterIfNotMoved", True)
		super().__init__(script, override=self.override, **defaults)
		# NVDA Input Help looks for this attribute
		self.__self__ = ti
	
	def override(self, *args, **kwargs):
		script = kwargs.pop(self.arg)
		disableTableModeBefore = self.disableTableModeBefore
		enableTableModeAfter = self.enableTableModeAfter
		tryTableModeAfterIfBrowseMode = self.tryTableModeAfterIfBrowseMode
		restoreTableModeAfter = self.restoreTableModeAfter
		restoreTableModeAfterIfBrowseMode = self.restoreTableModeAfterIfBrowseMode
		restoreTableModeAfterIfNotMoved = self.restoreTableModeAfterIfNotMoved
		
		ti = self.__self__
		fromBk = ti.selection.bookmark
		focus = api.getFocusObject()
		if isinstance(focus, DocumentFakeCell):
			cell = focus
			table = cell.table
			cache = ti._speakObjectTableCellChildrenPropertiesCache
			cache.clear()
			
			def getObjId(obj):
				if isinstance(obj, FakeObject):
					return id(obj)
				return (obj.event_windowHandle, obj.event_objectID, obj.event_childID)
			
			def cacheChildrenProperties(obj):
				for obj in obj.children:
					speech.speakObjectProperties(
						obj, states=True, reason=controlTypes.OutputReason.ONLYCACHE
					)
					#log.info(f"caching {getObjId(obj)}: {obj._speakObjectPropertiesCache}")
					cache[getObjId(obj)] = obj._speakObjectPropertiesCache
					cacheChildrenProperties(obj)
			
			cacheChildrenProperties(cell)
			#log.info(f"cached as {ti.selection._startOffset} by {self.__name__}: {cell.rowNumber, cell.columnNumber} {cache!r}", stack_info=True)
		else:
			table = None
		
		if not any((
			disableTableModeBefore,
			enableTableModeAfter,
			tryTableModeAfterIfBrowseMode,
			restoreTableModeAfter,
			restoreTableModeAfterIfBrowseMode,
			restoreTableModeAfterIfNotMoved
		)):
			script(*args, **kwargs)
			return
		
		passThroughBefore = ti.passThrough
		tableModeBefore = passThroughBefore == TABLE_MODE
		if tableModeBefore and disableTableModeBefore:
			ti.passThrough = BROWSE_MODE_FROM_TABLE_MODE
		checkRestore = tableModeBefore and any((
			restoreTableModeAfter, restoreTableModeAfterIfBrowseMode, restoreTableModeAfterIfNotMoved
		))
		if checkRestore:
			before = ti.selection.copy()
		
		script(*args, **kwargs)
		
		if not any((tryTableModeAfterIfBrowseMode, enableTableModeAfter, checkRestore)):
			return
		
		def thtiswo_trailer():
			passThrough = ti.passThrough
			if passThrough == TABLE_MODE:
				return
			if not enableTableModeAfter and tryTableModeAfterIfBrowseMode and not passThrough:
				try:
					ti.passThrough = TABLE_MODE
				except Exception:
					return
				queueCall(reportPassThrough, ti)
				return
			
			if enableTableModeAfter or (tableModeBefore and (
				restoreTableModeAfter
				or (restoreTableModeAfterIfBrowseMode and not passThrough)
			)):
				ti.passThrough = TABLE_MODE
				queueCall(reportPassThrough, ti)
				return
			
			if tableModeBefore and restoreTableModeAfterIfNotMoved:
				after = ti.selection.copy()
				if (
					before.compareEndPoints(after, "startToStart") == 0
					and before.compareEndPoints(after, "endToEnd") == 0
					and not ti.passThrough
				):
					if table is not None:
						table._shouldReportNextFocusEntered = False
					queueCall(setattr, ti, "passThrough", TABLE_MODE)
					queueCall(reportPassThrough, ti)
					return
		
		queueCall(thtiswo_trailer)


class TableHandlerBmdti(BrowseModeDocumentTreeInterceptor, DocumentTableHandler):
	"""Integrate Table UX into a `BrowseModeDocumentTreeInterceptor`.
	"""
	
	def __init__(self, rootNVDAObject):
		super().__init__(rootNVDAObject)
		self.autoTableMode = False
		self._currentTable = None
		self._speakObjectTableCellChildrenPropertiesCache = {}
	
	def __getattribute__(self, name):
		value = super().__getattribute__(name)
		if name.startswith("script_") and not isinstance(
			value, TableHandlerBmdtiScriptWrapper
		):
			return TableHandlerBmdtiScriptWrapper(self, value)
		return value
	
	def _set_passThrough(self, state):
		if self._passThrough == state:
			return
		#log.info(f">>> _set_passThrough({state}) was {self._passThrough}", stack_info=(False and state is True))
		if state == TABLE_MODE:
			table = self._currentTable
			if (
				table
				and self._passThrough != BROWSE_MODE_FROM_TABLE_MODE
				and (
					not self._lastCaretPosition
					or self._lastCaretPosition == self.selection.bookmark
				)
			):
				try:
					#log.info(f"before setPosition: {table._currentRowNumber, table._currentColumnNumber}")
					table._setPosition(self.selection)
					#log.info(f"after setPosition: {table._currentRowNumber, table._currentColumnNumber}")
				except ValueError:
					log.exception()
					table.__dict__.setdefault("_trackingInfo", []).append("dropped by _set_passThrough")
					table = self._currentTable = None
			#elif table:
			#	log.info(f"no setPosition: {table._currentRowNumber, table._currentColumnNumber}")
			if not table:
				table = self._currentTable = getTableManager(
					info=self.selection,
					setPosition=True,
					force=True
				)
				if not table:
					state = False
					if self._passThrough == state:
						return
				#else:
				#	log.info(f"new setPosition: {table._currentRowNumber, table._currentColumnNumber}")
			if state == TABLE_MODE:
				oldPassThrough = self._passThrough
				self._passThrough = state
				if oldPassThrough == BROWSE_MODE_FROM_TABLE_MODE:
					cell = table._currentCell
					if cell:
						cell.setFocus()
						return
				queueCall(table.setFocus)
				return
		if state:
			if self.passThrough in (
				TABLE_MODE,
				BROWSE_MODE_FROM_TABLE_MODE,
				FOCUS_MODE_FROM_TABLE_MODE
			):
				state = FOCUS_MODE_FROM_TABLE_MODE
		elif self.passThrough == TABLE_MODE:
			self._passThrough = None
			obj = self._lastFocusObj
			if not obj:
				obj = NVDAObjects.NVDAObject.objectWithFocus()
				if obj not in self:
					obj = self._currentTable.parent
				self._lastFocusObj = obj
				#log.info(f"TI.passThrough={state}, Back to real focus {obj!r}({obj.role!r})")
			#else:
			#	log.info(f"TI.passThrough={state}, Back to last focus {obj!r}({obj.role!r})")
			eventHandler.lastQueuedFocusObject = obj
			api.setFocusObject(obj)
			api.setNavigatorObject(obj)
		#log.info(f"_set_passThrough({state}) now {self._passThrough}")
		super()._set_passThrough(state)
	
	def _set_selection(self, info, reason=controlTypes.OutputReason.CARET):
		#log.info(f"_set_selection({info}, {reason})")
		if not self._hadFirstGainFocus:
			# Still initializing, most likely restoring caret position
			super()._set_selection(info, reason=reason)
			return
		if reason == REASON_TABLE_MODE:
			with speechMuted():
				super()._set_selection(info, reason=controlTypes.OutputReason.CARET)
			return
		elif reason == controlTypes.OutputReason.FOCUS and self.passThrough == TABLE_MODE:
			try:
				table = self._currentTable
			except Exception:
				log.exception()
				table = None
			if table:
				cell = table._currentCell
				if cell:
					cell.setFocus()
					return
#		elif reason == controlTypes.OutputReason.QUICKNAV and self.passThrough == TABLE_MODE:
#			self.passThrough = False
		try:
			super()._set_selection(info, reason=reason)
		except Exception:
			log.exception("_set_selection({!r}, {!r})".format(info, reason))
			raise

		def set_selection_trailer():
			#log.info(f"set_selection_trailer: {self.passThrough} {api.getFocusObject()}")
			oldTable = self._currentTable
			try:
				table = self._currentTable = getTableManager(ti=self, info=self.selection, setPosition=True)
			except Exception:
				log.exception()
				table = None
			if oldTable and table is not oldTable:
				oldTable.__dict__.setdefault("_trackingInfo", []).append("dropped by set_selection_trailer")
			del oldTable
			if not table and self.passThrough == TABLE_MODE:
				#log.info(f"set_selection_trailer: Canceling table mode")
				self.passThrough = False
				queueCall(reportPassThrough, self)
			del table
		
		queueCall(set_selection_trailer)
	
	def getBrailleRegions(self, review=False):
		if self.passThrough == TABLE_MODE:
			if self._currentTable is not None:
				cell = self._currentTable._currentCell
				if cell is not None:
					return cell.getBrailleRegions(review=review)
				# TODO: Handle braille reporting of empty tables
		return super().getBrailleRegions(review=review)
	
	@catchAll(log)
	def getAlternativeScript(self, gesture, script):
		script = super().getAlternativeScript(gesture, script)
		if script is not None and not isinstance(script, TableHandlerBmdtiScriptWrapper):
			script = TableHandlerBmdtiScriptWrapper(self, script)
		return script
	
	@catchAll(log)
	def getScript(self, gesture):
		func = super().getScript(gesture)
		if func is not None and not isinstance(func, TableHandlerBmdtiScriptWrapper):
			func = TableHandlerBmdtiScriptWrapper(self, func)
		return func
	
	def getTableConfigKey(self, nextHandler, **kwargs):
		if kwargs.get("debug"):
			log.info(f">>> THTI.getTableConfigKey({kwargs})")
		self.setDefaultTableKwargs(kwargs)
		res = super().getTableConfigKey(nextHandler=nextHandler, **kwargs)
		if kwargs.get("debug"):
			log.info(f"<<< THTI.getTableConfigKey: {res}")
		return res
	
	def getTableManager(self, nextHandler, **kwargs):
		if kwargs.get("debug"):
			log.info(f">>> THTI.getTableManager({kwargs})")
		self.setDefaultTableKwargs(kwargs)
		kwargs["ti"] = self
		table = super().getTableManager(nextHandler=nextHandler, **kwargs)
		if table:
			if kwargs.get("setPosition"):
				rowNum = kwargs.get("rowNum")
				colNum = kwargs.get("colNum")
				if rowNum is not None:
					table._currentRowNumber = rowNum
				elif DEBUG_MODE:
					log.error("setPosition: Unspecified row number")
				if colNum is not None:
					table._currentColumnNumber = colNum
				elif DEBUG_MODE:
					log.error("setPosition: Unspecified column number")
			if kwargs.get("debug"):
				log.info(f"<<< THTI.getTableManager: {table} (from super)")
			return table
		if kwargs.get("debug"):
			log.info(f"THTI.getTableManager - next handler")
		res = nextHandler(**kwargs)
		if kwargs.get("debug"):
			log.info(f"<<< THTI.getTableManager: {res} (from next handler)")
		return res
	
	def setDefaultTableKwargs(self, kwargs):
		kwargs["ti"] = self
		info = kwargs.get("info")
		if info is None:
			info = kwargs["info"] = self.selection
		if (
			kwargs.get("tableID") is None
			or (kwargs.get("setPosition") and (
				kwargs.get("rowNum") is None or kwargs.get("colNum") is None
			))
		):
			coords = kwargs.get("tableCellCoords")
			if coords is None:
				try:
					coords = self._getTableCellCoordsIncludingLayoutTables(info)
				except LookupError:
					if kwargs.get("debug"):
						log.exception()
					coords = False  # Avoid checking multiple times at same position
				kwargs["tableCellCoords"] = coords
			if coords:
				for name in ("tableID", "rowNum", "colNum"):
					if kwargs.get(name) is None:
						kwargs[name] = getattr(coords, name)
	
	def makeTextInfo(self, position):
		if isinstance(position, FakeObject):
			log.error("THTI asked for a fake object!", stack_info=True)
			return position.makeTextInfo(position)
		return super().makeTextInfo(position)
	
	def shouldPassThrough(self, obj, reason=None):
		if self.passThrough == TABLE_MODE:
			return TABLE_MODE
		return super().shouldPassThrough(obj, reason=reason)
# 		res = super().shouldPassThrough(obj, reason=reason)
# 		if self.passThrough == FOCUS_MODE_FROM_TABLE_MODE:
# 			return FOCUS_MODE_FROM_TABLE_MODE

# 		return res
	
	def _focusLastFocusableObject(self, activatePosition=False):
		"""Used when auto focus focusable elements is disabled to sync the focus
		to the browse mode cursor.
		When auto focus focusable elements is disabled, NVDA doesn't focus elements
		as the user moves the browse mode cursor. However, there are some cases
		where the user always wants to interact with the focus; e.g. if they press
		the applications key to open the context menu. In these cases, this method
		is called first to sync the focus to the browse mode cursor.
		"""
		#log.info(f"sel: {self.selection.bookmark}")
		obj = self.currentFocusableNVDAObject
		#if obj!=self.rootNVDAObject and self._shouldSetFocusToObj(obj) and obj!= api.getFocusObject():
		if obj!=self.rootNVDAObject and self._shouldSetFocusToObj(obj):
			focus = NVDAObjects.NVDAObject.objectWithFocus()
			if obj != focus:
				obj.setFocus()
				# We might be about to activate or pass through a key which will cause
				# this object to change (e.g. checking a check box). However, we won't
				# actually get the focus event until after the change has occurred.
				# Therefore, we must cache properties for speech before the change occurs.
				speech.speakObject(obj, controlTypes.OutputReason.ONLYCACHE)
				self._objPendingFocusBeforeActivate = obj
			#else:
			#	log.info(f"obj {obj.role!r} {getObjId(obj)} == focus {focus.role!r} {getObjId(focus)}")
			#log.info(f"obj: {obj.treeInterceptor.makeTextInfo(obj).bookmark}")
			#log.info(f"focus: {focus.treeInterceptor.makeTextInfo(focus).bookmark}")
		if activatePosition:
			# Make sure we activate the object at the caret, which is not necessarily focusable.
			self._activatePosition()
	
	def _getTableCellCoordsIncludingLayoutTables(self, info):
		"""
		Fetches information about the deepest table cell at the given position.
		Derived from `DocumentWithTableNavigation._getTableCellAt` to never exclude layout tables.
		@param info:  the position where the table cell should be looked for.
		@type info: L{textInfos.TextInfo}
		@returns: a tuple of table ID, is layout, row number, column number, row span, and column span.
		@rtype: TableCellCoords (namedtuple)
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
		return TableCellCoords(
			tableID,
			tableID in layoutIDs,
			attrs.get("table-rownumber"),
			attrs.get("table-columnnumber"),
			attrs.get("table-rowsspanned", 1),
			attrs.get("table-columnsspanned", 1)
		)
	
	def event_gainFocus(self, obj, nextHandler):
		#log.info(f"event_gainFocus({obj!r}): passThrough={self.passThrough!r} focus={api.getFocusObject()!r}")
		if self.passThrough == TABLE_MODE:
			try:
				with speechMuted():
					super().event_gainFocus(obj, nextHandler)
			except Exception:
				log.exception("obj={!r}".format(obj))
				raise
			api.setFocusObject(self._currentTable)
			return
		#log.info(f"TI.event_gainFocus({obj!r}({obj.role!r}), isLast={obj is self._lastFocusObj}, eqLast={obj == self._lastFocusObj}, isPending={obj is self._objPendingFocusBeforeActivate}, eqPending={obj == self._objPendingFocusBeforeActivate}")
		# After leaving table mode, the newly focused object might, if activated,
		# trigger both gainFocus and stateChange events.
		pending = self._objPendingFocusBeforeActivate
		oldCache = getattr(pending, "_speakObjectPropertiesCache", None)
		super().event_gainFocus(obj, nextHandler)
		newCache = getattr(pending, "_speakObjectPropertiesCache", None)
		if oldCache != newCache:
			obj._speakObjectPropertiesCache = newCache
		return
	
	def event_stateChange(self, obj, nextHandler):
		getEventId = lambda obj: (obj.event_windowHandle, obj.event_objectID, obj.event_childID)
		#log.info(f"event_stateChange({obj!r}{getEventId(obj)}): isFocus={obj is api.getFocusObject()}, eqFocus={obj == api.getFocusObject()}, lastFocus={obj is self._lastFocusObj}, cache={getattr(obj, '_speakObjectPropertiesCache', None)}")
		if not self.isAlive:
			from virtualBuffers.gecko_ia2 import Gecko_ia2
			if isinstance(self, Gecko_ia2):
				#log.info("TreeInterceptor is dead")
				return treeInterceptorHandler.killTreeInterceptor(self)
		if self.passThrough == TABLE_MODE:
			# Handled in `_handleUpdate`
#			log.info("table mode")
			return
# 		focus = api.getFocusObject()
# 		if isinstance(focus, DocumentFakeCell):
# 			log.warning("Force focus to parent before stateChange on {!r}".format(obj))
# 			focus = focus.table.parent
# 			api.setFocusObject(focus)
# 		cache = self._speakObjectTableCellChildrenPropertiesCache
# 		if (focus and focus is not obj):
# 			objId = getEventId(obj)
# 			if getEventId(focus) == objId:
# 				api.setFocusObject(obj)
# 				if obj is not self._lastFocusObj:
# 					if objId in cache:
# 						log.info(f"retreived from cache: {objId} -> {cache[objId]!r}")
# 						obj._speakObjectPropertiesCache = cache[objId]
# 					else:
# 						log.info(f"not in cache: {objId}")
		
		func = getattr(super(), "event_stateChange", None)
		if func:
			func(obj, nextHandler)
		else:
			nextHandler()
	
	def event_treeInterceptor_gainFocus(self):
		if self.passThrough == TABLE_MODE:
			# Avoid stock announce of the cell content in the event it contains
			# a focusable object and NVDA config has autoFocusFocusableElements=True
			with speechMuted():
				super().event_treeInterceptor_gainFocus()
				return
		super().event_treeInterceptor_gainFocus()
	
	@overrides(BrowseModeDocumentTreeInterceptor.script_nextColumn)
	def script_nextColumn(self, gesture):
		if self.passThrough == TABLE_MODE:
			self._currentTable.script_moveToNextColumn(gesture)
			return
		super().script_nextColumn(gesture)
	
	script_nextColumn.disableTableModeBefore = False
	
	@overrides(BrowseModeDocumentTreeInterceptor.script_previousColumn)
	def script_previousColumn(self, gesture):
		if self.passThrough == TABLE_MODE:
			self._currentTable.script_moveToPreviousColumn(gesture)
			return
		super().script_previousColumn(gesture)
	
	script_previousColumn.disableTableModeBefore = False
	
	@overrides(BrowseModeDocumentTreeInterceptor.script_firstRow)
	def script_firstRow(self, gesture):
		if self.passThrough == TABLE_MODE:
			self._currentTable.script_moveToFirstRow(gesture)
			return
		super().script_firstRow(gesture)
	
	script_firstRow.disableTableModeBefore = False
	
	@overrides(BrowseModeDocumentTreeInterceptor.script_lastRow)
	def script_lastRow(self, gesture):
		if self.passThrough == TABLE_MODE:
			self._currentTable.script_moveToLastRow(gesture)
			return
		super().script_LastRow(gesture)
	
	script_lastRow.disableTableModeBefore = False
	
	@overrides(BrowseModeDocumentTreeInterceptor.script_firstColumn)
	def script_firstColumn(self, gesture):
		if self.passThrough == TABLE_MODE:
			self._currentTable.script_moveToFirstColumn(gesture)
			return
		super().script_firstColumn(gesture)
	
	script_firstColumn.disableTableModeBefore = False
	
	@overrides(BrowseModeDocumentTreeInterceptor.script_lastColumn)
	def script_lastColumn(self, gesture):
		if self.passThrough == TABLE_MODE:
			self._currentTable.script_moveToLastColumn(gesture)
			return
		super().script_lastColumn(gesture)
	
	script_lastColumn.disableTableModeBefore = False
	
	@overrides(BrowseModeDocumentTreeInterceptor.script_disablePassThrough)
	def script_disablePassThrough(self, gesture):
		if self.passThrough == FOCUS_MODE_FROM_TABLE_MODE:
			self.passThrough = TABLE_MODE
			reportPassThrough(self)
			return
		super().script_disablePassThrough(gesture)
	
	@overrides(BrowseModeDocumentTreeInterceptor.script_nextRow)
	def script_nextRow(self, gesture):
# 		if self.passThrough == TABLE_MODE:
# 			# Translators: A tutor message
# 			ui.message(_("In table mode, use arrows to navigate table cells."))
# 			return
		super().script_nextRow(gesture)
	
	script_nextRow.disableTableModeBefore = False
	
	@overrides(BrowseModeDocumentTreeInterceptor.script_previousRow)
	def script_previousRow(self, gesture):
# 		if self.passThrough == TABLE_MODE:
# 			# Translators: A tutor message
# 			ui.message(_("In table mode, use arrows to navigate table cells."))
# 			return
		super().script_previousRow(gesture)
	
	script_previousRow.disableTableModeBefore = False
	
	@overrides(BrowseModeDocumentTreeInterceptor.script_nextTable)
	def script_nextTable(self, gesture):
		if not config.conf["tableHandler"]["enableOnQuickNav"]:
			super().script_nextTable(gesture)
			return
		if self.passThrough is False and self._currentTable:
			#log.info(f"script_nextTable: Table mode at current position")
			self.passThrough = TABLE_MODE
			queueCall(reportPassThrough, self)
			return
		bookmark = self.selection.bookmark
		with speechMuted(retains=True) as ctx:
			super().script_nextTable(gesture)
		
		def nextTable_trailer():
			#log.info(f"script_nextTable: Trailer start")
			if self.passThrough == TABLE_MODE:
				# Otherwise _set_passThrough short-circuits and doesn't focus the new table
				# when navigating from table to table in table mode.
				self._passThrough = False
			try:
				self.passThrough = TABLE_MODE
			except Exception:
				log.exception()
				pass
			queueCall(reportPassThrough, self)
			if bookmark == self.selection.bookmark:
				# No movement, quick-nav failed, speak the failure announce
				#log.info(f"script_nextTable: No movement")
				ctx.speakMuted()
			#log.info(f"script_nextTable: Trailer end")
		
		queueCall(nextTable_trailer)
	
	script_nextTable.disableTableModeBefore = False
	
	@overrides(BrowseModeDocumentTreeInterceptor.script_previousTable)
	def script_previousTable(self, gesture):
		if not config.conf["tableHandler"]["enableOnQuickNav"]:
			super().script_previousTable(gesture)
			return
		bookmark = self.selection.bookmark
		with speechMuted(retains=True) as ctx:
			super().script_previousTable(gesture)
		
		def previousTable_trailer():
			if self.passThrough == TABLE_MODE:
				# Otherwise _set_passThrough short-circuits and doesn't focus the new table
				# when navigating from table to table in table mode.
				self._passThrough = False
			try:
				self.passThrough = TABLE_MODE
			except Exception:
				pass
			queueCall(reportPassThrough, self)
			if bookmark == self.selection.bookmark:
				# No movement, quick-nav failed, speak the failure announce
				ctx.speakMuted()
		
		queueCall(previousTable_trailer)
	
	script_previousTable.disableTableModeBefore = False


class TableHandlerVirtualBuffer(TableHandlerBmdti):
	
	def getTableManager(self, nextHandler, **kwargs):
		kwargs.setdefault("tableManagerClass", VirtualBufferTableManager)
		return super().getTableManager(nextHandler, **kwargs)
	
	def _handleUpdate(self):
		super()._handleUpdate()
		if self.passThrough != TABLE_MODE:
			return
		table = self._currentTable
		rowNum = table._currentRowNumber
		colNum = table._currentColumnNumber
		#log.info(f"updating from {rowNum, colNum}")
		try:
			table = getTableManager(ti=self, info=self.selection, setPosition=True)
		except Exception:
			if not self.isAlive:
				return
			log.exception(stack_info=True)
			return
		if table:
			#log.info(f"updated at {rowNum, colNum}")
			table._currentRowNumber = rowNum
			table._currentColumnNumber = colNum
			cell = table._currentCell
			if not cell:
				log.warning(f"Could not retrieve current cell {table._currentRowNumber, table._currentColumnNumber}")
				table = getTableManager(ti=self, info=self.selection, setPosition=True)
				if not table:
					log.warning(f"Second table fetch failed")
					return
				cell = table._currentCell
				if not cell:
					log.warning(f"Second current cell fetch failed {table._currentRowNumber, table._currentColumnNumber}")
					return
			cell.__dict__.setdefault("_trackingInfo", []).append("TI._handleUpdate")
			cache = self._speakObjectTableCellChildrenPropertiesCache
			
			def getObjId(obj):
				if isinstance(obj, FakeObject):
					return id(obj)
				return (obj.event_windowHandle, obj.event_objectID, obj.event_childID)
			
			def speakChildrenPropertiesChange(obj):
				for obj in obj.children:
					objId = getObjId(obj)
					obj._speakObjectPropertiesCache = cache.get(objId, {})
					speech.speakObjectProperties(obj, states=True, reason=controlTypes.OutputReason.CHANGE)
					cache[objId] = obj._speakObjectPropertiesCache
					speakChildrenPropertiesChange(obj)
			
			if cache:
				speakChildrenPropertiesChange(cell)

			focus = api.getFocusObject()
			if isinstance(focus, DocumentFakeCell) or focus.treeInterceptor is self:
				#log.info(f"_handleUpdate() focusing {cell!r}")
				try:
					api.setFocusObject(cell)
				except Exception:
					if self.isAlive:
						log.exception()
					return
				braille.handler.handleGainFocus(cell)
				brailleInput.handler.handleGainFocus(cell)
				vision.handler.handleGainFocus(cell)
				#cell.setFocus()
				#log.info("setting _shouldReportNextFocusEntered False from _handleUpdate from thtiswo_trailer")
				#table._shouldReportNextFocusEntered = False
				#table.setFocus()
	
	def _loadBufferDone(self, success=True):
		#log.warning(f"_loadBufferDone({success})")
		super()._loadBufferDone(success=success)
		

class DocumentFakeObject(FakeObject):
	
	def _get_treeInterceptor(self):
		return None
	
	def _set_treeInterceptor(self, value):
		# Defeats NVDA's attempts with IE11 to set a TreeInterceptor
		pass
	
	def setFocus(self):
		obj = self.focusRedirect
		if obj and obj is not self:
			obj.setFocus()
			return
		if not api.setFocusObject(self):
			raise Exception("Could not set focus to {!r}".format(self))
		import globalVars
		#log.info(f"fdl={globalVars.focusDifferenceLevel}, ancestors={globalVars.focusAncestors}, parents={globalVars.focusAncestors[globalVars.focusDifferenceLevel:]}, tableInAnc={getattr(self, 'table', None) in globalVars.focusAncestors}")
		for parent in globalVars.focusAncestors[globalVars.focusDifferenceLevel:]:
			if not isinstance(parent, DocumentFakeObject):
				continue
			#log.info(f"entering {parent!r}")
			eventHandler.executeEvent("focusEntered", parent)
		self.event_gainFocus()


class DocumentFakeCell(TextInfoDrivenFakeCell, DocumentFakeObject):
	
	_cache_focusRedirect_ = False
	
	def _get_focusRedirect_(self):
		fromBk = self.info.bookmark
		renewed = self.row._getCell(self.columnNumber, refresh=True)
		if not renewed:
			log.warning("Unable to renew {self!r} from {self.row!r}")
			renewed = self.table._getCell(self.roaNumber, self.columnNumber, refresh=True)
			if not renewed:
				log.warning("Unable to renew {self!r} from {self.table!r}")			
		toBk = renewed.info.bookmark
# 		if fromBk == toBk:
# 			log.info(f"Redirecting as-is {self!r} at {fromBk}")
# 		else:
# 			log.warning(f"Redirecting {self!r} from {fromBk} to {toBk}")
		return renewed
		
	
	_cache_ti = False
	
	def _get_ti(self):
		return self.table.ti
	
	def event_gainFocus(self):
		#log.info(f"event_gainFocus({self!r}) at {self.info.bookmark}")
		focus = api.getFocusObject()
		if self is not focus:
			log.error(f"event_gainFocus({self!r}) while focus={focus!r}")
			return
		
		table = self.table
		ti = table.ti
		sel = self.info.copy()
		sel.collapse()
		ti._set_selection(sel, reason=REASON_TABLE_MODE)
		table._currentRowNumber = self.rowNumber
		table._currentColumnNumber = self.columnNumber
		super().event_gainFocus()	
	
	@overrides(TextInfoDrivenFakeCell.script_modifyColumnWidthBraille)
	def script_modifyColumnWidthBraille(self, gesture):
		DocumentResizingCell(cell=self).setFocus()


class DocumentResizingCell(ResizingCell, DocumentFakeObject):
	pass


class DocumentFakeRow(TextInfoDrivenFakeRow, DocumentFakeObject):
	
	CellClass = DocumentFakeCell
	
	_cache_ti = False
	
	def _get_ti(self):
		return self.table.ti


class DocumentRootFakeObject(DocumentFakeObject):
	
	def __init__(self, *args, ti=None, **kwargs):
		super().__init__(*args, ti=ti, **kwargs)
		self._parent = None
	
	_cache_ti = False
	
	def _get_ti(self):
		return self._ti() if self._ti else None
	
	def _set_ti(self, value):
		self._ti = weakref.ref(value)
	
	_cache_parent = False
	
	def _get_parent(self):
		parent = None
		focus = api.getFocusObject()
		if self is focus:
			parent = next(reversed(api.getFocusAncestors()))
		else:
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
	
	def _get_field(self):
		info = self.startPos if self.startPos else self._currentCell.info
		return getField(info, "controlStart", role=controlTypes.ROLE_TABLE)
	
	def _get_columnCount(self):
		count = self.field.get("table-columncount")
		if isinstance(count, str):
			count = int(count)
		return count
	
	def _get_rowCount(self):
		count = self.field.get("table-rowcount")
		if isinstance(count, str):
			count = int(count)
		return count
		
	@catchAll(log)
	def getScript(self, gesture):
		if hasattr(gesture, "__DocumentTableManager"):
			return None
		func = super().getScript(gesture)
		if func is not None:
			return func
		setattr(gesture, "__DocumentTableManager", None)  # Avoid recursion
		
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
	
	def _isEqual(self, obj):
		return (self is obj or (
			isinstance(obj, type(self))
			and self.ti == obj.ti
			and self.tableID == obj.tableID
		))
	
	@abstractmethod
	def _iterCellsTextInfos(self, rowNumber):
		# TODO: Provide a generic BrowseModeDocumentTreeInterceptor implementation
		# to add support of eg. MS Word.
		raise NotImplementedError
	
	@catchAll(log)
	def _onTableFilterChange(self, text=None, caseSensitive=None):
		focus = api.getFocusObject()
		if isinstance(focus, DocumentFakeCell):
			table = focus.table
			if table is not self and self == table:
				# The previously focused table has most likely been replaced after an update
				# of the virtual buffer as the focus re-entered the document.
				table._onTableFilterChange(text=text, caseSensitive=caseSensitive)
				return
		super()._onTableFilterChange(
			text=text, caseSensitive=caseSensitive
		)
	
	def _setPosition(self, info):
		#log.info(f"_setPosition({info._startOffset})", stack_info=True)
		coords = self.ti._getTableCellCoordsIncludingLayoutTables(info)
		if coords.tableID != self.tableID:
			raise ValueError("The given position is not inside this table")
		cell = None
		rowNum = coords.rowNum
		colNum = coords.colNum
		if rowNum is not None and colNum is not None:
			self._currentRowNumber = rowNum
			self._currentColumnNumber = colNum
			cell = self._currentCell
			#log.info(f"_setPosition({info._startOffset}): ({rowNum}, {colNum})")
		if (
			cell
			and cell.role == controlTypes.ROLE_TABLECELL
			and rowNum != self._tableConfig["columnHeaderRowNumber"]
			and colNum != self._tableConfig["rowHeaderColumnNumber"]
		):
			return
		cell = self._firstDataCell
		if cell:
			self._currentRowNumber = cell.rowNumber
			self._currentColumnNumber = cell.columnNumber
			#log.info(f"_setPosition({info._startOffset}): first ({rowNum}, {colNum})")
			return
		raise ValueError("Table empty?")
	
	def _tableMovementScriptHelper(self, axis, direction, notifyOnFailure=True, fromCell=None):
		from .behaviors import AXIS_ROWS, DIRECTION_NEXT, DIRECTION_PREVIOUS
		if not(axis == AXIS_ROWS and self.filterText):
			return super()._tableMovementScriptHelper(
				axis, direction, notifyOnFailure=notifyOnFailure, fromCell=fromCell
			)
		if fromCell:
			info = fromCell.info.copy()
		else:
			fromCell = self._currentCell
			info = self.ti.selection.copy()
		if direction == DIRECTION_NEXT:
			reverse = False
		elif direction == DIRECTION_PREVIOUS:
			reverse = True
		else:
			raise ValueError("direction={!r}".format(direction))
		while True:
			if not info.find(
				self.filterText,
				reverse=reverse,
				caseSensitive=self.filterCaseSensitive or False
			):
				break
			func = self.ti._getTableCellCoordsIncludingLayoutTables
			tableID, isLayout, rowNum, colNum, rowSpan, colSpan = func(info)
			if tableID is not None and tableID == self.tableID:
				if rowNum == fromCell.rowNumber:
					continue
				return self._moveToRow(rowNum)
			break
		if notifyOnFailure:
			if direction == DIRECTION_NEXT:
				# Translators: Reported when attempting to navigate table rows
				ui.message(_("No next matching row. Press escape to cancel filtering."))
			else:
				# Translators: Reported when attempting to navigate table rows
				ui.message(_("No previous matching row. Press escape to cancel filtering."))
			self._reportRowChange()
		return False
	
	def script_disableTableMode(self, gesture):
		if self.filterText:
			self._onTableFilterChange(text=None)
			return
		ti = self.ti
		if ti.passThrough == TABLE_MODE:
			ti.passThrough = False
			reportPassThrough(ti)
			return
		self.ti.script_disablePassThrough(gesture)
		
	script_disableTableMode.canPropagate = True
	script_disableTableMode.restoreTableModeAfterIfNotMoved = False
	
# 	def script_tab(self, gesture):
# 		sel = self._currentCell.info.copy()
# 		sel.move(textInfos.UNIT_CHARACTER, -1, endPoint="start")
# 		ti = self.ti
# 		item = next(ti._iterNodesByType("focusable", "next", sel), None)
# 		if item:
# 			info = item.textInfo.copy()
# 			info.collapse()
# 			if (
# 				info.compareEndPoints(sel, "startToStart") >= 0
# 				and info.compareEndPoints(sel, "endToEnd") <= 0
# 			):
# 				ti.passThrough = FOCUS_MODE_FROM_TABLE_MODE
# 				ti._set_selection(info, reason=controlTypes.OutputReason.FOCUS)
# 				ti.passThrough = FOCUS_MODE_FROM_TABLE_MODE
# 				obj = item.obj
# 				if NVDAObjects.NVDAObject.objectWithFocus() != obj:
# 					obj.setFocus()
# 				else:
# 					obj.event_gainFocus()
# 				return
# 		# Translators: Reported when attempting to tab into a table cell
# 		speech.speakMessage(_("No focusable element within this table cell"))
# 		log.info(f"sel: {sel.bookmark}, item: {item.textInfo.bookmark}, text={item.textInfo.text}")
# 	
# 	script_tab.canPropagate = True
	
	__gestures = {
		"kb:escape": "disableTableMode",
		"kb:control+alt+upArrow": "moveToPreviousRow",
		"kb:control+alt+downArrow": "moveToNextRow",
		"kb:control+alt+leftArrow": "moveToPreviousColumn",
		"kb:control+alt+rightArrow": "moveToNextColumn",
		"kb:control+alt+pageUp": "moveToFirstRow",
		"kb:control+alt+pageDown": "moveToLastRow",
		"kb:control+alt+home": "moveToFirstColumn",
		"kb:control+alt+end": "moveToLastColumn",
#		"kb:tab": "tab"
	}


class VirtualBufferTableManager(DocumentTableManager):
	
	def _iterCellsTextInfos(self, rowNumber):
		return iterVirtualBufferTableCellsSafe(self.ti, self.tableID, row=rowNumber)
