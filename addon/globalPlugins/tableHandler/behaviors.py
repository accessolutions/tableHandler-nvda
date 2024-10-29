# globalPlugins/tableHandler/behaviors.py
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

"""Table Handler Global Plugin
"""

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


import weakref

from NVDAObjects import NVDAObject
import addonHandler
import api
from baseObject import ScriptableObject
import braille
import brailleInput
import config
import controlTypes
from logHandler import log
import scriptHandler
import speech
import textInfos
import ui
import vision

from globalPlugins.lastScriptUntimedRepeatCount import getLastScriptUntimedRepeatCount
from globalPlugins.withSpeechMuted import speechUnmutedFunction

from .brailleUtils import (
	TabularBrailleBuffer,
	brailleCellsDecimalStringToIntegers,
	brailleCellsIntegersToUnicode
)
from .coreUtils import catchAll, queueCall, translate
from .scriptUtils import getScriptGestureTutorMessage
from .tableUtils import (
	getColumnHeaderTextSafe,
	getColumnSpanSafe,
	getRowHeaderTextSafe,
	getRowSpanSafe
)

addonHandler.initTranslation()


SCRIPT_CATEGORY = "TableHandler"


class CellRegion(braille.TextInfoRegion):
	
	def routeTo(self, braillePos):
		cell = self.obj
		table = cell.table
		colNum = cell.columnNumber
		if not colNum == table._currentColumnNumber:
			table._moveToColumn(colNum, cell=cell)
			return
		if config.conf["tableHandler"]["brailleRoutingDoubleClickToActivate"]:
			if scriptHandler.getLastScriptRepeatCount() < 1:
				table._reportColumnChange()
				return
		info = self.getTextInfoForBraillePos(braillePos)
		try:
			info.activate()
		except NotImplementedError:
			pass


class ColumnSeparatorRegion(braille.Region):
	
	brailleCells = None
	brailleToRawPos = None
	rawText = None
	rawToBraillePos = None
	
	@classmethod
	def handleConfigChange(cls):
		cells = cls.brailleCells = brailleCellsDecimalStringToIntegers(
			config.conf["tableHandler"]["brailleColumnSeparator"]
		)
		cls.rawText = brailleCellsIntegersToUnicode(cells)
		cls.brailleToRawPos = list(range(len(cells)))
		cls.rawToBraillePos = list(range(len(cells)))	
	
	def __init__(self, obj):
		super().__init__()
		self.obj = obj
		self.brailleCells = type(self).brailleCells
		self.brailleToRawPos = type(self).brailleToRawPos
		self.rawText = type(self).rawText
		self.rawToBraillePos = type(self).rawToBraillePos
	
	def routeTo(self, braillePos):
		cell = self.obj.cell
		table = cell.table
		colNum = cell.columnNumber
		if not colNum == table._currentColumnNumber:
			table._moveToColumn(colNum, cell=cell)
			return
		if config.conf["tableHandler"]["brailleRoutingDoubleClickToActivate"]:
			if scriptHandler.getLastScriptRepeatCount() < 1:
				table._reportColumnChange()
				return
		if not config.conf["tableHandler"]["brailleColumnSeparatorActivateToSetWidth"]:
			table._reportColumnChange()
			return
		self.obj.cell.script_modifyColumnWidthBraille(None)
	
	def update(self):
		# Handle by `.config.handleConfigChange_brailleColumnSeparator` 
		pass


class RowRegionBuffer(TabularBrailleBuffer):
	
	def __init__(self, rowRegion):
		super().__init__()
		self.rowRegion = weakref.proxy(rowRegion)
		self.resizingCell = None
	
	def onRegionUpdatedAfterPadding(self, region):
		if isinstance(region, CellRegion):
			obj = region.obj
			brailleCells = region.brailleCells
			isCellRegion = True
		else:
			assert isinstance(region, ColumnSeparatorRegion)
			if not isinstance(region, ColumnSeparatorRegion):
				raise ValueError(region)
			obj = region.obj.cell
			# Preserve the shared class attribute
			brailleCells = region.brailleCells = region.brailleCells.copy()
			isCellRegion = False
		if obj.columnNumber == obj.table._currentColumnNumber:
			#if obj is not self.rowRegion.obj and not isinstance(obj, weakref.ProxyType):
			#	log.warning(f"{obj!r} is not {self.rowRegion.obj!r}")
			markStart = 0
			if isCellRegion:
				if self.rowRegion.isResizingColumnWidth:
					markEnd = obj.table._tableConfig.getColumnWidth(obj.columnNumber)
					obj.columnsAfterInBrailleWindow = 0
					obj.effectiveColumnWidthBraille = region.width
					self.resizingCell = obj
				else:
					markEnd = None
			else:
				markEnd = next((
					index + 1
					for index, brailleCell in reversed(list(enumerate(brailleCells)))
					if brailleCell
				), 0)
			brailleCells[markStart:markEnd] = [
				brailleCell | braille.SELECTION_SHAPE
				for brailleCell in brailleCells[markStart:markEnd]
			]
		elif self.resizingCell and isCellRegion:
			self.resizingCell.columnsAfterInBrailleWindow += 1
	
	def update(self):
		self.resizingCell = None
		super().update()
		self.resizingCell = None


class RowRegion(braille.TextInfoRegion):
	
	def __init__(self, cell):
		super().__init__(obj=cell)
		self.hidePreviousRegions = True
		self.buffer = RowRegionBuffer(self)
		self.windowNumber = None
		self.maxWindowNumber = None
		self.cell = cell
		self.row = weakref.proxy(cell.row)
		self.table = weakref.proxy(self.row.table)
		self.isResizingColumnWidth = False
		self.currentCellRegion = None
		#global _region
		#_region = self
	
	def getColumns(self):
		#from pprint import pformat
		from .fakeObjects.table import ColumnSeparator
		cells = [cell for colNum, colSpan, cell in self.row._iterCells()]
		#log.info(f"cells: {pformat(cells, indent=2)}")
		columns = []
		displaySize = braille.handler.displaySize
		colSepWidth = len(ColumnSeparatorRegion.brailleCells)
		winNum = 0
		winSize = 0
		for index, cell in enumerate(cells):
			width = cell.columnWidthBraille
			while True:
				if width is None:
					# No fixed width: Make this cell the last of its window.
					columns.append((winNum, width, cell))
					winNum += 1
					winSize = 0
					break
				elif winSize + width + colSepWidth <= displaySize:
					# Append this fixed-width cell to the current window.
					winSize += width + colSepWidth
					columns.append((winNum, width, cell))
					columns.append((winNum, colSepWidth, ColumnSeparator(parent=cell.parent, cell=cell)))
					if winSize == displaySize:
						# Move on to the next window
						winNum += 1
						winSize = 0
					break
				elif winSize:
					# Not enough room in the current non-empty window:
					# Expand the last cell and move on to the next window.
					lastWinNum, lastWidth, lastCell = columns[-2]
					lastWidth += displaySize - winSize
					columns[-2] = (lastWinNum, lastWidth, lastCell)
					winNum += 1
					winSize = 0
					continue
				else:
					# Not enough room in the current empty window:
					# Truncate to the display size and move on to the next window.
					columns.append((winNum, displaySize - colSepWidth, cell))
					columns.append((winNum, colSepWidth, ColumnSeparator(parent=cell.parent)))
					winNum += 1
					winSize = 0
					break
		if columns:
			assert len(columns) >= 2
			# Remove the last column separator and expand the last column to the display size
			del columns[-1]
			lastWinNum, lastWidth, lastCell = columns[-1]
			lastWidth += displaySize - winSize
			columns[-1] = (lastWinNum, lastWidth, lastCell)
		#log.info(f"columns: {pformat(columns, indent=4)}")
		return columns
	
	def getWindowColumns(self):
		columns = []
		lastWinNum = 0
		for winNum, width, obj in self.getColumns():
			self.maxWindowNumber = winNum
			if self.windowNumber is None:
				if columns and winNum != lastWinNum:
					columns = []
				lastWinNum = winNum
				columns.append((width, obj))
				if obj == self.cell:
					self.windowNumber = winNum
			elif winNum == self.windowNumber:
				columns.append((width, obj))
			elif columns:
				break
		return columns
	
	def iterWindowRegions(self):
		from .fakeObjects.table import ColumnSeparator
		for width, obj in self.getWindowColumns():
			if isinstance(obj, Cell):
				region = CellRegion(obj)
				if obj == self.cell:
					self.currentCellRegion = region
			elif isinstance(obj, ColumnSeparator):
				region = ColumnSeparatorRegion(obj)
			else:
				region = braille.NVDAObjectRegion(obj)
			region.width = width
			yield region
	
	def routeTo(self, braillePos):
		if self.isResizingColumnWidth:
			if (
				config.conf["tableHandler"]["brailleRoutingDoubleClickToActivate"]
				and scriptHandler.getLastScriptRepeatCount() == 1
			):
				api.getFocusObject().script_done(None)
				return
			if config.conf["tableHandler"]["brailleSetColumnWidthWithRouting"]:
				start = self.buffer.regionPosToBufferPos(self.currentCellRegion, 0)
				width = braillePos - start
				if width >= 0:
					api.getFocusObject().setColumnWidthBraille(width)
				else:
					api.getFocusObject().script_done(None)
				return
		self.buffer.routeTo(braillePos)
	
	def update(self):
		buffer = self.buffer
		buffer.regions = list(self.iterWindowRegions())
		buffer.update()
		self.rawText = buffer.windowRawText
		self.brailleCells = buffer.windowBrailleCells
		self.cursorPos = buffer.cursorWindowPos
	
	def previousLine(self, start=False):
		# Pan left rather than moving to the previous line.
		buffer = self.buffer
		if buffer._previousWindow():
			self.rawText = buffer.windowRawText
			self.brailleCells = buffer.windowBrailleCells
			self.cursorPos = buffer.cursorWindowPos
		elif self.windowNumber:
			self.windowNumber -= 1
			self.update()
		else:
			return
		braille.handler.mainBuffer.update()
		braille.handler.mainBuffer.updateDisplay()
	
	def nextLine(self):
		# Pan right rather than moving to the next line.
		buffer = self.buffer
		if buffer._nextWindow():
			self.rawText = buffer.windowRawText
			self.brailleCells = buffer.windowBrailleCells
			self.cursorPos = buffer.cursorWindowPos
		if self.windowNumber < self.maxWindowNumber:
			self.windowNumber += 1
			self.update()
		else:
			return
		braille.handler.mainBuffer.update()
		braille.handler.mainBuffer.updateDisplay()


class Cell(ScriptableObject):
	"""Table Cell
	
	This class can be used as an overlay to an NVDAObject.
	"""
	
	scriptCategory = SCRIPT_CATEGORY
	cachePropertiesByDefault = True
	
	def __repr__(self):
		try:
			tableID = self.tableID
		except Exception:
			tableID = None
		try:
			rowNumber = self.rowNumber
		except Exception:
			rowNumber = None
		try:
			columnNumber = self.columnNumber
		except Exception:
			columnNumber = None
		return "<Cell {}/[{}, {}] {} {!r}>".format(
			tableID, rowNumber, columnNumber, id(self), getattr(self, "_trackingInfo", [])
		)
	
	def _get_columnHeaderText(self):
		num = self.columnNumber
		customHeaders = self.table._tableConfig["customColumnHeaders"]
		if num in customHeaders:
			return customHeaders[num]
		return self.getColumnHeaderText()
	
	def _get_columnWidthBraille(self):
		return self.table._tableConfig.getColumnWidth(self.columnNumber)
	
	def _set_columnWidthBraille(self, value):
		raise NotImplementedError
	
	_cache_row = False
	
	def _get_role(self):
		cfg = self.table._tableConfig
		colHeaRowNum = cfg["columnHeaderRowNumber"]
		if self.rowNumber == colHeaRowNum:
			return controlTypes.ROLE_TABLEROWHEADER
		rowHeaColNum = cfg["rowHeaderColumnNumber"]
		if self.columnNumber == rowHeaColNum:
			return controlTypes.ROLE_TABLECOLUMNHEADER
		if (
			colHeaRowNum and self.rowNumber != colHeaRowNum
			and rowHeaColNum and self.columnNumber != rowHeaColNum
		):
			return controlTypes.ROLE_TABLECELL
		return self.getRole()
	
	def _get_row(self):
		return self.parent
	
	def _get_rowHeaderText(self):
		num = self.rowNumber
		customHeaders = self.table._tableConfig["customRowHeaders"]
		if num in customHeaders:
			return customHeaders[num]
		return self.getRowHeaderText()
	
	def _get_states(self):
		states = self.parent.states.copy()
		try:
			location = self.location
		except NotImplementedError:
			location = None
		if location and location.width == 0:
			states.add(controlTypes.STATE_INVISIBLE)
		states.discard(controlTypes.STATE_CHECKED)
		return states
	
	_cache_table = False
	
	def _get_table(self):
		return self.row.table
	
	def _get_tableID(self):
		return self.table.tableID
	
	def getBrailleRegions(self, review=False):
		if review:
			# Review this cell.
			raise NotImplementedError
		else:
			# Render the whole row.
			return [RowRegion(cell=self),]
	
	def getColumnHeaderText(self):
		return getColumnHeaderTextSafe(super())
	
	def getRole(self):
		return controlTypes.ROLE_TABLECELL
	
	def getRowHeaderText(self):
		return getRowHeaderTextSafe(super())
	
	def honorsFilter(self, text, caseSensitive=False):
		needle = text
		if not needle:
			return True
		haystack = self.basicText
		if not caseSensitive:
			haystack = haystack.casefold()
			needle = needle.casefold()
		return needle in haystack
	
	def reportFocus(self):
		speech.speakMessage(
			# Translators: Announced when reporting the table cell with focus
			_("Table cell row {row} column {column}").format(
				row=self.rowHeaderText or self.rowNumber,
				column=self.columnHeaderText or self.columnNumber,
				containing=self.basicText
			)
		)
	
	def _isEqual(self, obj):
		try:
			return (
				self.table == obj.table
				and self.rowNumber == obj.rowNumber
				and self.columnNumber == obj.columnNumber
			)
		except Exception:
			return False
	
	def event_gainFocus(self):
		# Not calling super avoids `reportFocus`
		braille.handler.handleGainFocus(self)
		brailleInput.handler.handleGainFocus(self)
		vision.handler.handleGainFocus(self)
		
		table = self.table
		if not getattr(table, "_receivedFocusEntered", False):
			if not getattr(table, "_hasFocusEntered", False):
				table._reportFocusEntered()
				table._hasFocusEntered = True
	
	def event_loseFocus(self):
		table = self.table
		if not getattr(table, "_receivedFocusEntered", False):
			
			def loseFocus_trailer():
				focus = api.getFocusObject()
				if getattr(focus, "table", None) is not table:
					table._hasFocusEntered = False
			
			queueCall(loseFocus_trailer)
		
		super().event_loseFocus()
	
	def script_modifyColumnWidthBraille(self, gesture):
		from .fakeObjects.table import ResizingCell
		ResizingCell(cell=self).setFocus()
	
	# Translators: The description of a command.
	script_modifyColumnWidthBraille.__doc__ = _("Set the width of the current column in braille")
	
	def script_reportCurrentFocus(self, gesture):
		self.reportFocus()
	
	__gestures = {
		"kb:NVDA+control+shift+l": "modifyColumnWidthBraille",
		"kb:NVDA+tab": "reportCurrentFocus"
	}


class Row(ScriptableObject):
	"""Table Row.
	
	This class can be used as an overlay to an NVDAObject.
	"""
	
	cachePropertiesByDefault = True
	role = controlTypes.ROLE_TABLEROW

	def __repr__(self):
		try:
			tableID = self.tableID
		except Exception:
			tableID = None
		try:
			rowNum = self.rowNumber
		except Exception:
			rowNum = None
		return "<Row {}/[{}]>".format(tableID, rowNum)
	
	def _get_columnCount(self):
		return self.table.columnCount
	
	_cache_focusRedirect = True
	
	def _get_focusRedirect(self):
		obj = self._currentCell
		# Oddly, NVDA's EventExecutor does not care about chained redirection
		return obj and (obj.focusRedirect or obj)
	
	_cache_table = False
	
	def _get_table(self):
		return self.parent
	
	def _get_tableID(self):
		return self.table.tableID
	
	_cache__currentCell = False
	
	def _get__currentCell(self):
		curNum = self.table._currentColumnNumber
		if curNum is None:
			log.warning("Current column number is None")  # @@@
			return None
		return self._getCell(curNum)
	
	def honorsFilter(self, text, caseSensitive=False):
		return any((
			True
			for colNum, colSpan, cell in self._iterCells()
			if cell.honorsFilter(text, caseSensitive)
		))
	
	def _getCell(self, columnNumber):
		for colNum, colSpan, cell in self._iterCells():
			if colNum <= columnNumber < colNum + colSpan:
				return cell
	
	def _iterCells(self):
		obj = self.firstChild
		while obj:
			colNum = obj.columnNumber
			colSpan = getColumnSpanSafe(obj)
			yield colNum, colSpan, obj
			obj = obj.next
	
	def event_focusEntered(self):
		# Prevent execution of the default handler
		pass


AXIS_ROWS = "row"
AXIS_COLUMNS = "column"

DIRECTION_NEXT = "next"
DIRECTION_PREVIOUS = "previous"


class TableManager(ScriptableObject):
	"""Table UX.
	
	This class can be used as an overlay to an NVDAObject.
	"""
	
	scriptCategory = SCRIPT_CATEGORY
	cachePropertiesByDefault = True
	role = controlTypes.ROLE_TABLE
	
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.initOverlayClass()
	
	def __repr__(self):
		try:
			tableID = self.tableID
		except Exception:
			tableID = None
		return "<Table {}>".format(tableID)
	
	def initOverlayClass(self):
		self.filterText = None
		self.filterCaseSensitive = None
		self._shouldReportNextFocusEntered = True
		self._currentColumnNumber = None
		self._currentRowNumber = None
		#global _tableManager
		#_tableManager = self
	
	# The property is requested twice in a row by `eventHandler.executeEvent`
	_cache_focusRedirect = True
	
	def _get_focusRedirect(self):
		obj = self._currentRow
		# Oddly, NVDA's `executeEvent` does not care about chained redirection
		return obj and (obj.focusRedirect or obj)
	
	_cache__currentCell = False
	
	def _get__currentCell(self):
		focus = api.getFocusObject()
		if isinstance(focus, Cell):
			cell = focus
			if cell.table is self:
				if self._currentRowNumber is None or self._currentColumnNumber is None:
					self._currentRowNumber = cell.rowNumber
					self._currentColumnNumber = cell.columnNumber
					return cell
				elif cell.rowNumber == self._currentRowNumber:
					if cell.columnNumber == self._currentColumnNumber:
						#log.info(f"table._get__currentCell: {self._currentRowNumber, self._currentColumnNumber} -> focus {cell!r}")
						return cell
					#return cell.row._currentCell
					newCell = cell.row._currentCell
					#log.info(f"table._get__currentCell: {self._currentRowNumber, self._currentColumnNumber} -> row {cell!r} -> {newCell!r}")
					return newCell
		if self._currentRowNumber is None or self._currentColumnNumber is None:
			cell = self._firstDataCell
			if cell:
				self._currentRowNumber = cell.rowNumber
				self._currentColumnNumber = cell.columnNumber
		else:
			cell = self._getCell(self._currentRowNumber, self._currentColumnNumber)
			#log.info(f"table._get__currentCell: {self._currentRowNumber, self._currentColumnNumber} -> table._getCell {cell!r}")
		if not cell:
			log.warning("Could not retrieve current cell ({}, {})".format(self._currentRowNumber, self._currentColumnNumber))
		return cell
	
	_cache__currentRow = False
	
	def _get__currentRow(self):
		focus = api.getFocusObject()
		curNum = self._currentRowNumber
		if isinstance(focus, Cell):
			row = focus.row
			if row.table is self and (curNum is None or row.rowNumber == curNum):
				return row
		if curNum is None:
			cell = self._firstDataCell
			if cell:
				return cell.row
		else:
			return self._getRow(curNum)
		return None
	
	def _get__firstDataCell(self):
		firstRowNum = self._tableConfig["firstDataRowNumber"]
		firstColNum = self._tableConfig["firstDataColumnNumber"]
		if firstRowNum is not None and firstColNum is not None:
			return self._getCell(firstRowNum, firstColNum)
		rowNums = (firstRowNum,) if firstRowNum else tuple(range(1, self.rowCount + 1))
		colNums = (firstColNum,) if firstColNum else tuple(range(1, self.columnCount + 1))
		for rowNum in rowNums:
			for colNum in colNums:
				cell = self._getCell(rowNum, colNum)
				if cell:
					if len(rowNums) > 1 and cell.role == controlTypes.ROLE_TABLEROWHEADER:
						continue
					if len(colNums) > 1 and cell.role == controlTypes.ROLE_TABLECOLUMNHEADER:
						continue
					return cell
		return self._getCell(1, 1)
	
	def reportFocus(self):  # TODO
		super().reportFocus()
	
	def _getCell(self, rowNumber, columnNumber):
		row = self._getRow(rowNumber)
		if row is None:
			return None
		return row._getCell(columnNumber)
	
	def _getRow(self, rowNumber):
		# TODO: Implement a base children lookup?
		raise NotImplementedError
		
	def _moveToColumn(self, columnNumber, cell=None, notifyOnFailure=True):
		if cell is None:
			cell = self._getCell(self._currentRowNumber, columnNumber)
		if not cell:
			if notifyOnFailure:
				ui.message(translate("Edge of table"))
			self._reportColumnChange()
			return False
		self._currentColumnNumber = columnNumber
		cell.setFocus()
		# Wait for the cell to gain focus so it can be retrieved from `globalVars`
		# rather than being recomputed
		queueCall(self._reportColumnChange)
		return True
	
	def _moveToRow(self, rowNumber, row=None, notifyOnFailure=True):
		if row is None:
			row = self._getRow(rowNumber)
		if not row:
			if notifyOnFailure:
				# Translators: Reported when a table is empty.
				ui.message(translate("Edge of table"))
			return False
		self._currentRowNumber = rowNumber
		row.setFocus()
		# Wait for the cell to gain focus so it can be retrieved from `globalVars`
		# rather than being recomputed
		queueCall(self._reportRowChange)
		return True
	
	@catchAll(log)
	def _onTableFilterChange(self, text=None, caseSensitive=None):
		speech.cancelSpeech()
		if not text:
			# Translators: Announced when canceling the filtering of table rows
			speech.speakMessage(_("Table filter canceled"))
		self.filterText = text
		self.filterCaseSensitive = caseSensitive
		if text:
			self._shouldReportNextFocusEntered = False
			self.script_moveToFirstDataCell(None)
			# It is faster to reset than to check if we needed to prevent reporting at all
			self._shouldReportNextFocusEntered = True
	
	@speechUnmutedFunction
	def _reportCellChange(self, axis=AXIS_COLUMNS):
# 		#@@@
# 		speech.speakMessage("{}, {}".format(self._currentRowNumber, self._currentColumnNumber))
# 		speech.speakTextInfo(self._currentCell.makeTextInfo(textInfos.POSITION_ALL))
# 		return
		curCell = self._currentCell
		curRowNum = curCell.rowNumber
		curColNum = curCell.columnNumber
		if curCell is None:
			ui.message(translate("Not in a table cell"))
			return

		if axis == AXIS_COLUMNS:
			getCell = lambda num: self._getCell(num, curColNum)
		elif axis == AXIS_ROWS:
			curRow = curCell.row
			getCell = lambda num: curRow._getCell(num)
		else:
			raise ValueError("axis={!r}".format(axis))
		
		content = []
		
		def appendCell(num):
			cell = getCell(num)
			if not cell:
				log.warning("Could not fetch cell {}".format(num))
				return
			content.append(cell.basicText)
		
		cfg = self._tableConfig
		headerRowNum = cfg["columnHeaderRowNumber"]
		inColHeader = headerRowNum == curRowNum or curCell.role == controlTypes.ROLE_TABLECOLUMNHEADER
		headerColNum = cfg["rowHeaderColumnNumber"]
		inRowHeader = headerColNum == curColNum or curCell.role == controlTypes.ROLE_TABLEROWHEADER
		inHeader = inColHeader or inRowHeader
		hasCustomRowHeader = curRowNum in cfg["customRowHeaders"]
		hasCustomColHeader = curColNum in cfg["customColumnHeaders"]
				
		if inHeader:
			if inColHeader:
				if inRowHeader:
					roleLabel = controlTypes.roleLabels[controlTypes.ROLE_TABLECOLUMNHEADER]
				else:
					roleLabel = controlTypes.roleLabels[controlTypes.ROLE_HEADER]
				if headerRowNum is False:
					# Translator: Announced when moving to a disabled header cell
					content.append(_("Disabled {role}").format(role=roleLabel))
				elif (curCell.role == controlTypes.ROLE_TABLECOLUMNHEADER and (
					isinstance(headerRowNum, int)
					and headerRowNum != curRowNum
				) or hasCustomColHeader):
					# Translator: Announced when moving to a superseded header cell
					content.append(_("Original {role}").format(role=roleLabel))
				elif axis==AXIS_ROWS or not inRowHeader:
					content.append(roleLabel)
			if inRowHeader and axis == AXIS_COLUMNS:
				if inColHeader:
					roleLabel = controlTypes.roleLabels[controlTypes.ROLE_TABLEROWHEADER]
				else:
					roleLabel = controlTypes.roleLabels[controlTypes.ROLE_HEADER]
				if headerColNum is False:
					# Translator: Announced when moving to a disabled header cell
					content.append(_("Disabled {role}").format(role=roleLabel))
				elif (curCell.role == controlTypes.ROLE_TABLEROWHEADER and (
					isinstance(headerColNum, int)
					and headerColNum != curColNum
				) or hasCustomRowHeader):
					# Translator: Announced when moving to a superseded header cell
					content.append(_("Original {role}").format(role=roleLabel))
				else:
					content.append(roleLabel)
		# Do not announce the row header of a column header cell,
		# but do announce the column header of a row header cell
		if (
			(axis == AXIS_COLUMNS and not inColHeader and (headerRowNum is None or hasCustomRowHeader))
			or (axis == AXIS_ROWS and (headerColNum is None or hasCustomRowHeader))
		):
			headerText = None
			try:
				if axis == AXIS_COLUMNS:
					headerText = curCell.columnHeaderText
				else:
					headerText = curCell.rowHeaderText
			except NotImplementedError:
				pass
			if headerText:
				headerText = headerText.strip()
			if headerText:
				content.append(headerText)
		elif axis == AXIS_COLUMNS and not inColHeader and headerRowNum is not False and not hasCustomRowHeader:
			appendCell(headerRowNum)
		elif axis == AXIS_ROWS and not hasCustomColHeader and headerColNum not in (False, curColNum):
			appendCell(headerColNum)
		
		content.append(curCell)
		
		if inColHeader:
			marked = cfg["markedColumnNumbers"]
			if curColNum in marked:
				if axis == AXIS_ROWS or curColNum != headerColNum:
					# Translators: Announced when moving to a marked header cell
					content.append(_("Column marked"))
					if axis == AXIS_ROWS:
						if len(marked) > 1:
							content.append(translate("{number} out of {total}").format(
								number=list(sorted(marked)).index(curColNum) + 1, total=len(marked)
							))
					if curColNum == headerColNum:
						# Translators: Announced when moving to a marked header cell
						content.append(_("as row header"))
					elif marked[curColNum]:
						# Translators: Announced when moving to a marked header cell
						content.append(_("with announce"))
					else:
						# Translators: Announced when moving to a marked header cell
						content.append(_("without announce"))
			elif marked and axis == AXIS_ROWS:
				count = len(marked)
				if count > 1:
					# Translators: Announced when moving to a header cell
					content.append(_("{count} columns marked").format(count=len(marked)))
				elif len(marked) == 1  and not isinstance(headerColNum, int):
					# Translators: Announced when moving to a header cell
					content.append(_("1 column marked"))
		if inRowHeader:
			# TODO: Implement marked rows
			#marked = {headerRowNum: False} if isinstance(headerRowNum, int) else {}
			marked = cfg["markedRowNumbers"]
			if curRowNum in marked:
				if axis == AXIS_COLUMNS or curRowNum != headerRowNum:
					# Translators: Announced when moving to a marked header cell
					content.append(_("Row marked"))
					if axis == AXIS_COLUMNS:
						if len(marked) > 1:
							content.append(translate("{number} out of {total}").format(
								number=list(marked).index(curRowNum) + 1, total=len(marked)
							))
					if curRowNum == headerRowNum:
						# Translators: Announced when moving to a marked header cell
						content.append(_("as column header"))
					elif marked[curRowNum]:
						# Translators: Announced when moving to a marked header cell
						content.append(_("with announce"))
					else:
						# Translators: Announced when moving to a marked header cell
						content.append(_("without announce"))
			elif marked and axis == AXIS_COLUMNS:
				if len(marked) > 1:
					# Translators: Announced when moving to a header cell
					content.append(_("{count} rows marked").format(count=len(marked)))
				elif len(marked) == 1 and not isinstance(headerRowNum, int):
					# Translators: Announced when moving to a header cell
					content.append(_("1 row marked"))
		if not inHeader:
			if axis == AXIS_COLUMNS:
				marked = sorted([
					num for num, announce in cfg["markedRowNumbers"].items()
					if announce and num not in (curRowNum, headerRowNum)
				])
			else:
				# The following `sorted` leads to announcing in natural columns order
				# rather than in the order of which the columns were marked.
				# TODO: Make marked columns announce order configurable?
				marked = sorted([
					num for num, announce in cfg["markedColumnNumbers"].items()
					if announce and num not in (curColNum, headerColNum)
				])
			for num in marked:
				appendCell(num)
		
		for part in content:
			if isinstance(part, str):
				speech.speakText(part)
			elif isinstance(part, NVDAObject):
				speech.speakTextInfo(
					part.makeTextInfo(textInfos.POSITION_ALL),
					reason=controlTypes.OutputReason.CARET
				)
			else:
				raise ValueError(part)

	def _reportColumnChange(self):
		self._reportCellChange(axis=AXIS_COLUMNS)

	@speechUnmutedFunction
	def _reportFocusEntered(self):
		if not self._shouldReportNextFocusEntered:
			self._shouldReportNextFocusEntered = True
			return
		speech.cancelSpeech()
		rowCount = self.rowCount
		if rowCount is not None:
			speech.speakMessage(_("Table with {rowCount} rows").format(rowCount=rowCount))
		else:
			speech.speakMessage(translate("table"))
		self._reportColumnChange()
	
	def _reportRowChange(self):
		self._reportCellChange(axis=AXIS_ROWS)
	
	def _tableMovementScriptHelper(self, axis, direction, notifyOnFailure=True, fromCell=None):
		"""Helper used to incrementally move along table axis.
		
		axis: Either AXIS_COLUMNS or AXIS_ROWS
		direction: Either DIRECTION_NEXT or DIRECTION_PREVIOUS
		"""
		if axis == AXIS_ROWS:
			fromObj = self._currentRow if not fromCell else fromCell.row
			getNum = lambda obj: obj.rowNumber
			getObj = lambda num: self._getRow(num)
			getSpan = getRowSpanSafe
			moveTo = self._moveToRow
			repeat = self._reportRowChange
		elif axis == AXIS_COLUMNS:
			fromObj = self._currentCell if not fromCell else fromCell
			getNum = lambda obj: obj.columnNumber
			getObj = lambda num: fromObj.row._getCell(num)
			getSpan = getColumnSpanSafe
			moveTo = self._moveToColumn
			repeat = self._reportColumnChange
		else:
			ValueError("axis={}".format(repr(axis)))
		filtered = False
		while True:
			fromNum = getNum(fromObj)
			if direction == DIRECTION_NEXT:
				span = getSpan(fromObj)
				toNum = fromNum + span
				toObj = getObj(toNum)
			elif direction == DIRECTION_PREVIOUS:
				toNum = fromNum - 1
				while True:
					toObj = getObj(toNum)
					if toObj is fromObj and toNum > 1:
						toNum -= 1
						continue
					break
			else:
				raise ValueError("direction={!r}".format(direction))
			if toObj is None:
				if notifyOnFailure:
					if filtered:
						if direction == DIRECTION_NEXT:
							# Translators: Reported when attempting to navigate table rows
							ui.message(_("No next matching row. Press escape to cancel filtering."))
						else:
							# Translators: Reported when attempting to navigate table rows
							ui.message(_("No previous matching row. Press escape to cancel filtering."))
					else:
						ui.message(translate("Edge of table"))
					repeat()
				return False
			toNum_ = toNum
			toNum = getNum(toObj)
			if toNum == fromNum:
				if notifyOnFailure:
					ui.message(translate("Edge of table"))
					repeat()
				return False
			filterText = self.filterText
			if axis == AXIS_ROWS and filterText:
				if toObj.honorsFilter(filterText, self.filterCaseSensitive):
					break
				filtered = True
				fromObj = toObj
				continue
			break
		return moveTo(getNum(toObj), toObj, notifyOnFailure=notifyOnFailure)
	
	def event_focusEntered(self):
		# We do not seem to receive focusEntered events with IE11
		self._receivedFocusEntered = True
		self._reportFocusEntered()
		
	def script_contextMenu(self, gesture):
		from .gui import menu
		menu.show()
	
	script_contextMenu.canPropagate = True
	# Translators: The description of a command.
	script_contextMenu.__doc__ = _("Open the Table Mode context menu")
	
	def script_copyToClipboard(self, gesture):
		cell = self._currentCell
		if not cell:
			ui.message(translate("No selection"))
			return
		info = cell.makeTextInfo(textInfos.POSITION_ALL)
		if info.isCollapsed:
			ui.message(translate("No selection"))
			return
		info.copyToClipboard(notify=True)
	
	script_copyToClipboard.canPropagate = True
	
	def script_filter(self, gesture):
		from .gui import filter
		filter.show(self)
	
	script_filter.canPropagate = True
	# Translators: The description of a command.
	script_filter.__doc__ = _("Filter the table rows")
	
	def script_moveToFirstDataCell(self, gesture):
		cell = self._firstDataCell
		if not cell:
			ui.message(translate("Not in a table cell"))
			return
		if not cell.row.honorsFilter(self.filterText, self.filterCaseSensitive):
			if self._tableMovementScriptHelper(
				AXIS_ROWS, DIRECTION_NEXT,
				notifyOnFailure=False,
				fromCell=cell
			):
				return
			# Translators: Announced when trying to apply a table filter with no matching row
			speech.speakMessage(_("There is no row matching this filter"))
			self.filterText = None
		rowNum = cell.rowNumber
		if self._currentRowNumber != rowNum:
			report = self._reportRowChange
		else:
			report = self._reportColumnChange
		self._currentRowNumber = rowNum
		self._currentColumnNumber = cell.columnNumber
		report()
		cell.setFocus()
	
	script_moveToFirstDataCell.canPropagate = True
	# Translators: The description of a command.
	script_moveToFirstDataCell.__doc__ = _("Go to the first data cell")
	
	def script_moveToFirstColumn(self, gesture):
		curCell = self._currentCell
		if curCell is None:
			ui.message(translate("Not in a table cell"))
			return
		curNum = self._currentColumnNumber
		firstCell = self._firstDataCell
		firstNum = None
		if firstCell is not None:
			firstNum = firstCell.columnNumber
			if firstNum < curNum and self._moveToColumn(firstNum, notifyOnFailure=False):
				return
		# All rows might not have cells for all columns.
		# Let's itteratively try the first reachable column.
		for colNum in range(curNum):
			if self._moveToColumn(colNum, notifyOnFailure=False):
				break
		else:
			# Repeat on failure
			self._reportColumnChange()
	
	script_moveToFirstColumn.canPropagate = True
	# Translators: The description of a command.
	script_moveToFirstColumn.__doc__ = _("Go to the first column")
	
	def script_moveToLastColumn(self, gesture):
		if self._currentCell is None:
			ui.message(translate("Not in a table cell"))
			return
		curNum = self._currentColumnNumber
		# All rows might not have cells for all columns.
		# Let's itteratively try the last reachable column.
		for colNum in range(self.columnCount, curNum, -1):
			if self._moveToColumn(colNum, notifyOnFailure=False):
				break
		else:
			# Repeat on failure
			self._reportColumnChange()
	
	script_moveToLastColumn.canPropagate = True
	# Translators: The description of a command.
	script_moveToLastColumn.__doc__ = _("Go to the last column")
	
	def script_moveToNextColumn(self, gesture):
		self._tableMovementScriptHelper(AXIS_COLUMNS, DIRECTION_NEXT)
	
	script_moveToNextColumn.canPropagate = True
	# Translators: The description of a command.
	script_moveToNextColumn.__doc__ = _("Go to the next column")
	
	def script_moveToNextMarkedColumn(self, gesture):
		cell = self._currentCell
		if not cell:
			ui.message(translate("Not in a table cell"))
			return
		num = cell.columnNumber
		isMarked = False
		for marked in sorted(self._tableConfig["markedColumnNumbers"]):
			if marked > num:
				self._moveToColumn(marked)
				return
			if marked == num:
				isMarked = True
		# Translators: Emitted when attempting to move to a marked column
		speech.speakMessage(_("No next marked column"))
		if isMarked:
			self._reportColumnChange()
	
	script_moveToNextMarkedColumn.canPropagate = True
	# Translators: The description of a command.
	script_moveToNextMarkedColumn.__doc__ = _("Go to the next marked column")
	
	def script_moveToPreviousColumn(self, gesture):
		self._tableMovementScriptHelper(AXIS_COLUMNS, DIRECTION_PREVIOUS)
	
	script_moveToPreviousColumn.canPropagate = True
	# Translators: The description of a command.
	script_moveToPreviousColumn.__doc__ = _("Go to the previous column")
	
	def script_moveToPreviousMarkedColumn(self, gesture):
		cell = self._currentCell
		if not cell:
			ui.message(translate("Not in a table cell"))
			return
		num = cell.columnNumber
		isMarked = False
		for marked in reversed(sorted(self._tableConfig["markedColumnNumbers"])):
			if marked < num:
				self._moveToColumn(marked)
				return
			if marked == num:
				isMarked = True
		# Translators: Emitted when attempting to move to a marked column
		speech.speakMessage(_("No previous marked column"))
		if isMarked:
			self._reportColumnChange()
	
	script_moveToPreviousMarkedColumn.canPropagate = True
	# Translators: The description of a command.
	script_moveToPreviousMarkedColumn.__doc__ = _("Go to the previous marked column")
	
	def script_moveToFirstRow(self, gesture):
		self._moveToRow(1)
	
	script_moveToFirstRow.canPropagate = True
	# Translators: The description of a command.
	script_moveToFirstRow.__doc__ = _("Go to the first row")
	
	def script_moveToLastRow(self, gesture):
		# rowCount has been found to be unreliable with some implementations
		rowNumber = self.rowCount 
		while True:
			row = None
			cell = None
			try:
				row = self._getRow(rowNumber)
				cell = row._getCell(self._currentColumnNumber)
			except Exception:
				pass
			if row is None or cell is None:
				if rowNumber > self._currentRowNumber + 1:
					rowNumber -= 1
					continue
			break
		self._moveToRow(rowNumber, row=row)
	
	script_moveToLastRow.canPropagate = True
	# Translators: The description of a command.
	script_moveToLastRow.__doc__ = _("Go to the last row")
	
	def script_moveToNextRow(self, gesture):
		self._tableMovementScriptHelper(AXIS_ROWS, DIRECTION_NEXT)
	
	script_moveToNextRow.canPropagate = True
	# Translators: The description of a command.
	script_moveToNextRow.__doc__ = _("Go to the next row")
	
	def script_moveToNextMarkedRow(self, gesture):
		cell = self._currentCell
		if not cell:
			ui.message(translate("Not in a table cell"))
			return
		num = cell.rowNumber
		isMarked = False
		for marked in sorted(self._tableConfig["markedRowNumbers"]):
			if marked > num:
				self._moveToRow(marked)
				return
			if marked == num:
				isMarked = True
		# Translators: Emitted when attempting to move to a marked row
		speech.speakMessage(_("No next marked row"))
		if isMarked:
			self._reportRowChange()
	
	script_moveToNextMarkedRow.canPropagate = True
	# Translators: The description of a command.
	script_moveToNextMarkedRow.__doc__ = _("Go to the next marked row")
	
	def script_moveToPreviousRow(self, gesture):
		self._tableMovementScriptHelper(AXIS_ROWS, DIRECTION_PREVIOUS)
	
	script_moveToPreviousRow.canPropagate = True
	# Translators: The description of a command.
	script_moveToPreviousRow.__doc__ = _("Go to the previous row")
	
	def script_moveToPreviousMarkedRow(self, gesture):
		cell = self._currentCell
		if not cell:
			ui.message(translate("Not in a table cell"))
			return
		num = cell.rowNumber
		isMarked = False
		for marked in reversed(sorted(self._tableConfig["markedRowNumbers"])):
			if marked < num:
				self._moveToRow(marked)
				return
			if marked == num:
				isMarked = True
		# Translators: Emitted when attempting to move to a marked row
		speech.speakMessage(_("No previous marked row"))
		if isMarked:
			self._reportRowChange()
	
	script_moveToPreviousMarkedRow.canPropagate = True
	# Translators: The description of a command.
	script_moveToPreviousMarkedRow.__doc__ = _("Go to the previous marked row")
	
	def script_selectRow(self, gesture):  # TODO
		ui.message(_("Not supported on this table"))
	
	script_selectRow.canPropagate = True
	# Translators: The description of a command.
	script_selectRow.__doc__ = _("Select the current row, if supported")
	
	def script_setColumnHeader(self, gesture):
		cell = self._currentCell
		if not cell:
			ui.message(translate("Not in a table cell"))
			return
		curNum = cell.rowNumber
		cfg = self._tableConfig
		headerNum = cfg["columnHeaderRowNumber"]
		marked = cfg["markedRowNumbers"]
		marked.pop(headerNum, None)
		if headerNum == curNum:
			cfg["columnHeaderRowNumber"] = None
			headerText = getColumnHeaderTextSafe(cell)
			# Translators: Announced when customizing column headers
			ui.message(_("Column header reset to default: {}").format(headerText))
		elif getLastScriptUntimedRepeatCount() > 0 and headerNum is None:
			cfg["columnHeaderRowNumber"] = False
			# Translators: Announced when customizing column headers
			ui.message(_("Column header disabled"))
		else:
			marked[curNum] = None
			cfg["columnHeaderRowNumber"] = curNum
			# Translators: Announced when customizing column headers
			ui.message(_("Row set as column header"))
	
	script_setColumnHeader.canPropagate = True
	# Translators: The description of a command.
	script_setColumnHeader.__doc__ = _("Set the current row as column header")
	
	def script_setRowHeader(self, gesture):
		cell = self._currentCell
		if not cell:
			ui.message(translate("Not in a table cell"))
			return
		curNum = cell.columnNumber
		cfg = self._tableConfig
		headerNum = cfg["rowHeaderColumnNumber"]
		marked = cfg["markedColumnNumbers"]
		marked.pop(headerNum, None)
		if headerNum == curNum:
			cfg["rowHeaderColumnNumber"] = None
			headerText = getRowHeaderTextSafe(cell)
			# Translators: Reported when customizing row headers
			ui.message(_("Row header reset to default: {}").format(headerText))
		elif getLastScriptUntimedRepeatCount() > 0 and headerNum is None:
			cfg["rowHeaderColumnNumber"] = False
			# Translators: Reported when customizing row headers
			ui.message(_("Row header disabled"))
		else:
			marked[curNum] = None
			cfg["rowHeaderColumnNumber"] = curNum
			# Translators: Reported when customizing row headers
			ui.message(_("Column set as row header"))
	
	script_setRowHeader.canPropagate = True
	# Translators: The description of a command.
	script_setRowHeader.__doc__ = _("Set the current column as row header")
	
	def script_toggleMarkedColumn(self, gesture):
		num = self._currentColumnNumber
		if not num:
			ui.message(translate("Not in a table cell"))
			return
		if num == self._tableConfig["rowHeaderColumnNumber"]:
			# Translators: Reported when attempting to mark a column
			msg = _("This column is already marked as row header.")
			hint = getScriptGestureTutorMessage(
				TableManager,
				self.script_setRowHeader,
				# Translators: The {command} portion of a script hint message
				doc=_("reset")
			)
			if hint:
				msg += " " + hint
			ui.message(msg)
			return
		cfg = self._tableConfig
		marked = cfg["markedColumnNumbers"]
		if num in marked:
			announce = marked[num]
			if announce:
				marked[num] = False
				cfg.save()
				# Translators: Reported when toggling marked columns
				ui.message(_("Column marked without announce"))
				return
			del marked[num]
			cfg.save()
			# Translators: Reported when toggling marked columns
			ui.message(_("Column unmarked"))
			return
		marked[num] = True
		cfg.save()
		# Translators: Reported when toggling marked columns
		ui.message(_("Column marked with announce"))
	
	script_toggleMarkedColumn.canPropagate = True
	# Translators: The description of a command.
	script_toggleMarkedColumn.__doc__ = _("Toggle marked column")
	
	def script_toggleMarkedRow(self, gesture):
		num = self._currentRowNumber
		if not num:
			ui.message(translate("Not in a table cell"))
			return
		if num == self._tableConfig["rowHeaderRowNumber"]:
			# Translators: Reported when attempting to mark a row
			msg = _("This row is already marked as column header.")
			hint = getScriptGestureTutorMessage(
				TableManager,
				self.script_setRowHeader,
				# Translators: The {command} portion of a script hint message
				doc=_("reset")
			)
			if hint:
				msg += " " + hint
			ui.message(msg)
			return
		cfg = self._tableConfig
		marked = cfg["markedRowNumbers"]
		if num in marked:
			announce = marked[num]
			if announce:
				marked[num] = False
				cfg.save()
				# Translators: Reported when toggling marked rows
				ui.message(_("Row marked without announce"))
				return
			del marked[num]
			cfg.save()
			# Translators: Reported when toggling marked rows
			ui.message(_("Row unmarked"))
			return
		marked[num] = True
		cfg.save()
		# Translators: Reported when toggling marked rows
		ui.message(_("Row marked with announce"))
	
	script_toggleMarkedRow.canPropagate = True
	# Translators: The description of a command.
	script_toggleMarkedRow.__doc__ = _("Toggle marked row")

	__gestures = {
		"kb:applications": "contextMenu",
		"kb:upArrow": "moveToPreviousRow",
		"kb:downArrow": "moveToNextRow",
		"kb:leftArrow": "moveToPreviousColumn",
		"kb:rightArrow": "moveToNextColumn",
		"kb:home": "moveToFirstColumn",
		"kb:end": "moveToLastColumn",
		"kb:control+home": "moveToFirstDataCell",
		"kb:control+end": "moveToLastRow",
		"kb:control+leftArrow": "moveToPreviousMarkedColumn",
		"kb:control+rightArrow": "moveToNextMarkedColumn",
		"kb:control+upArrow": "moveToPreviousMarkedRow",
		"kb:control+downArrow": "moveToNextMarkedRow",
		"kb:NVDA+shift+c": "setColumnHeader",
		"kb:NVDA+shift+r": "setRowHeader",
		"kb:control+space": "toggleMarkedColumn",
		"kb:control+shift+space": "toggleMarkedRow",
		"kb:shift+space": "selectRow",
		"kb:control+c": "copyToClipboard",
		"kb:control+f": "filter"
	}
