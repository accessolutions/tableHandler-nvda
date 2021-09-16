# globalPlugins/tableHandler/behaviors.py
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

import addonHandler
import api
from baseObject import ScriptableObject
import braille
import config
import controlTypes
from logHandler import log
import speech
import textInfos
import ui

from .compoundDocuments import CompoundDocument
from .braille import TabularBrailleBuffer
from .fakeObjects import FakeObject
from .utils import getColumnSpanSafe, getRowSpanSafe


addonHandler.initTranslation()


SCRIPT_CATEGORY = "TableHandler"


class CellRegion(braille.TextInfoRegion):
	# TODO: Handle cursor routing (select/focus/activate)
	pass


class ColumnSeparatorRegion(braille.Region):
	
	def __init__(self, obj):
		super(ColumnSeparatorRegion, self).__init__()
		self.obj = obj
		self.rawText = "\u28b8"


class RowRegion(braille.TextInfoRegion):
		
	def __init__(self, cell):
		super(RowRegion, self).__init__(obj=cell)
		self.hidePreviousRegions = True
		self.buffer = TabularBrailleBuffer()
		self.windowNumber = None
		self.maxWindowNumber = None
		self.row = cell.row
		self.table = self.row.table
		#global _region
		#_region = self
	
	def getColumns(self):
		#from pprint import pformat
		from .fakeObjects.table import ColumnSeparator
		cells = []
		for colNum, colSpan, cell in self.row._iterCells():
			cells.append(cell)
		#log.info(f"cells: {pformat(cells, indent=2)}")
		columns = []
		displaySize = braille.handler.displaySize
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
				elif winSize + width + 1 <= displaySize:
					# Append this fixed-width cell to the current window.
					winSize += width + 1
					columns.append((winNum, width, cell))
					columns.append((winNum, 1, ColumnSeparator(parent=cell.parent)))
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
					columns.append(winNum, displaySize - 1, cell)
					columns.append((winNum, 1, ColumnSeparator(parent=cell.parent)))
					winNum += 1
					winSize = 0
					break
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
				if obj == self.obj:
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
			elif isinstance(obj, ColumnSeparator):
				region = ColumnSeparatorRegion(obj)
			else:
				region = braille.NVDAObjectRegion(obj)
			region.width = width
			yield region
	
	def routeTo(self, braillePos):
		self.buffer.routeTo(braillePos)
	
	def update(self):
		if self.buffer.regions:
			return
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
	"""Table Row.
	
	This class can be used as an overlay to an NVDAObject.
	"""
	
	cachePropertiesByDefault = True
	role = controlTypes.ROLE_TABLECELL
	
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
		return "<Cell {}/[{}, {}]>".format(tableID, rowNumber, columnNumber)
	
	def _get_columnWidthBraille(self):
		return self.table._tableConfig.getColumnWidth(self.rowNumber, self.columnNumber)
	
	def _set_columnWidthBraille(self, value):
		raise NotImplementedError
	
	_cache_row = False
	
	def _get_row(self):
		return self.parent
	
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
	
	def _isEqual(self, obj):
		try:
			return (
				self.table == obj.table
				and self.rowNumber == obj.rowNumber
				and self.columnNumber == obj.columnNumber
			)
		except Exception:
			return False


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
	
	_cache_focusRedirect = False
	
	def _get_focusRedirect(self):
		obj = self._currentCell
		# Oddly, NVDA's EventExecutor does not care about chained redirection
		return obj.focusRedirect or obj
	
	_cache_table = False
	
	def _get_table(self):
		return self.parent
	
	def _get_tableID(self):
		return self.table.tableID
	
	_cache__currentCell = False
	
	def _get__currentCell(self):
		return self._getCell(self.table._currentColumnNumber)
	
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
		super(TableManager, self).__init__(*args, **kwargs)
		self.initOverlayClass()
	
	def initOverlayClass(self):
		self._currentColumnNumber = 1
		self._currentRowNumber = 1
		self._markedColumnNumbers = []
		#global _tableManager
		#_tableManager = self
	
	_cache_focusRedirect = False
	
	def _get_focusRedirect(self):
		obj = self._currentRow
		# Oddly, NVDA's `executeEvent` does not care about chained redirection
		return obj.focusRedirect or obj
	
	_cache__currentCell = False
	
	def _get__currentCell(self):
		row = self._currentRow
		if row is None:
			return None
		return row._currentCell
	
	_cache__currentRow = False
	
	def _get__currentRow(self):
		return self._getRow(self._currentRowNumber)
	
	def reportFocus(self):  # TODO
		super(TableManager, self).reportFocus()
	
# 	def setFocus(self):
# 		focusRedirect = self.focusRedirect
# 		if focusRedirect is not None:
# 			focusRedirect.setFocus()
# 			return
# 		log.error("There is no table cell to focus")
	
	def _getCell(self, rowNumber, columnNumber):
		row = self._getRow(rowNumber)
		if row is None:
			return None
		return row._getCell(columnNumber)
	
	def _getRow(self, rowNumber):
		# TODO: Implement a base children lookup?
		raise NotImplementedError
		
	def _moveToColumn(self, columnNumber, cell=None):
		if cell is None:
			cell = self._getCell(self._currentRowNumber, columnNumber)
		if cell is None:
			if not self._currentRow:
				# Translators: Reported when a table is empty.
				ui.message(_("Table empty"))
				return
			ui.message(_("Edge of table"))
			return False
		self._currentColumnNumber = columnNumber
		cell.setFocus()
		self._reportColumnChange()
	
	def _moveToRow(self, rowNumber, row=None):
		if row is None:
			row = self._getRow(rowNumber)
		if row is None:
			if not self._currentRow:
				# Translators: Reported when a table is empty.
				ui.message(_("Table empty"))
				return False
			# Translators: Emitted when hitting the edge of a table
			ui.message(_("Edge of table"))
			return
		self._currentRowNumber = rowNumber
		row.setFocus()
		self._reportRowChange()
	
	def _reportColumnChange(self):
		cell = self._currentCell
		if cell is None:
			# Translators: Reported when a table is empty.
			ui.message(_("Table empty"))
			return
		parts = []
		header = cell.columnHeaderText
		if not header:
			# Translators: Reported as fail-back to a missing column header
			header = _("Col #{columnNumber}").format(columnNumber=cell.columnNumber)
		parts.append(header)
		parts.append(cell.basicText)
		msg = "\n".join(parts)
		speech.speakMessage(msg)
	
	def _reportRowChange(self):
		row = self._currentRow
		if row is None:
			# Translators: Reported when a table is empty.
			ui.message(_("Table empty"))
			return
		columnNumbers = self._markedColumnNumbers[:]
		if self._currentColumnNumber not in columnNumbers:
			columnNumbers.append(self._currentColumnNumber)
		content = []
		for columnNumber in sorted(columnNumbers):
			cell = self._getCell(self._currentRowNumber, columnNumber)
			if columnNumber == self._currentColumnNumber:
				content.append(cell.basicText)
			else:
				content.append(cell.basicText)
		try:
			doc = CompoundDocument(self, content)
		except Exception:
			log.exception("Error creating CompoundDocument with content={}".format(repr(content)))
			raise
		info = doc.makeTextInfo(textInfos.POSITION_ALL)
		# Store a strong reference to keep the `FakeObject` alive.
		info.obj = doc
		speech.speakTextInfo(info)
	
	def _tableMovementScriptHelper(self, axis, direction):
		"""Helper used to incrementally move along table axis.
		
		axis: Either AXIS_COLUMNS or AXIS_ROWS
		direction: Either DIRECTION_NEXT or DIRECTION_PREVIOUS
		"""
		if axis == AXIS_ROWS:
			getNum = lambda obj: obj.rowNumber
			getObj = lambda num: self._getRow(num)
			getSpan = getRowSpanSafe
			moveTo = self._moveToRow
		elif axis == AXIS_COLUMNS:
			getNum = lambda obj: obj.columnNumber
			getObj = lambda num: self._getCell(self._currentRowNumber, num)
			getSpan = getColumnSpanSafe
			moveTo = self._moveToColumn
		else:
			ValueError("axis={}".format(repr(axis)))
		fromNum = getNum(self._currentCell)
		if direction == DIRECTION_NEXT:
			fromObj = getObj(fromNum)
			span = getSpan(fromObj)
			toNum = fromNum + span
			toObj = getObj(toNum)
		elif direction == DIRECTION_PREVIOUS:
			fromObj = getObj(fromNum)
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
			# Translators: Emitted when hitting the edge of a table
			ui.message(_("Edge of table"))
			return
		toNum_ = toNum
		toNum = getNum(toObj)
		moveTo(getNum(toObj), toObj)
	
	def script_moveToFirstColumn(self, gesture):
		self._moveToColumn(1)
	
	script_moveToFirstColumn.canPropagate = True
	# Translators: The description of a command.
	script_moveToFirstColumn.__doc__ = _("Go to the first column")
	
	def script_moveToLastColumn(self, gesture):
		self._moveToColumn(self.columnCount)
	
	script_moveToLastColumn.canPropagate = True
	# Translators: The description of a command.
	script_moveToLastColumn.__doc__ = _("Go to the last column")
	
	def script_moveToNextColumn(self, gesture):
		self._tableMovementScriptHelper(AXIS_COLUMNS, DIRECTION_NEXT)
	
	script_moveToNextColumn.canPropagate = True
	# Translators: The description of a command.
	script_moveToNextColumn.__doc__ = _("Go to the next column")
	
	def script_moveToNextMarkedColumn(self, gesture):
		columnNumber = self._currentColumnNumber
		if not columnNumber:
			# Translators: Reported when a table is empty.
			ui.message(_("Table empty"))
			return
		curColIsMarked = False
		for marked in sorted(self._markedColumnNumbers):
			if marked > columnNumber:
				self._moveToColumn(marked)
				return
			if marked == columnNumber:
				curColIsMarked = True
		# Translators: Emitted when attempting to move to a marked column
		speech.speakMessage(_("No next marked column"))
		if curColIsMarked:
			# Translators: Emitted when attempting to move to a marked column
			speech.speakMessage(_("The current column is marked"))
	
	script_moveToNextMarkedColumn.canPropagate = True
	# Translators: The description of a command.
	script_moveToNextMarkedColumn.__doc__ = _("Go to the previous marked column")
	
	def script_moveToPreviousColumn(self, gesture):
		self._tableMovementScriptHelper(AXIS_COLUMNS, DIRECTION_PREVIOUS)
	
	script_moveToPreviousColumn.canPropagate = True
	# Translators: The description of a command.
	script_moveToPreviousColumn.__doc__ = _("Go to the previous column")
	
	def script_moveToPreviousMarkedColumn(self, gesture):
		columnNumber = self._currentColumnNumber
		curColIsMarked = False
		for marked in reversed(sorted(self._markedColumnNumbers)):
			if marked < columnNumber:
				self._moveToColumn(marked)
				return
			if marked == columnNumber:
				curColIsMarked = True
		# Translators: Emitted when attempting to move to a marked column
		speech.speakMessage(_("No next marked column"))
		if curColIsMarked:
			# Translators: Emitted when attempting to move to a marked column
			speech.speakMessage(_("The current column is marked"))
	
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
	
	def script_moveToPreviousRow(self, gesture):
		self._tableMovementScriptHelper(AXIS_ROWS, DIRECTION_PREVIOUS)
	
	script_moveToPreviousRow.canPropagate = True
	# Translators: The description of a command.
	script_moveToPreviousRow.__doc__ = _("Go to the previous row")
	
	def script_selectRow(self, gesture):  # TODO
		raise NotImplementedError()
	
	script_selectRow.canPropagate = True
	# Translators: The description of a command.
	script_selectRow.__doc__ = _("Select the current row, if supported")
	
	def script_toggleMarkedColumn(self, gesture):
		currentColumnNumber = self._currentColumnNumber
		if not currentColumnNumber:
			# Translators: Reported when a table is empty.
			ui.message(_("Table empty"))
			return
		try:
			self._markedColumnNumbers.remove(currentColumnNumber)
			# Translators: Reported when toggling marked columns
			ui.message(_("Column {} unmarked").format(currentColumnNumber))
		except ValueError:
			self._markedColumnNumbers.append(currentColumnNumber)
			# Translators: Reported when toggling marked columns
			ui.message(_("Column {} marked").format(currentColumnNumber))
	
	script_toggleMarkedColumn.canPropagate = True
	# Translators: The description of a command.
	script_toggleMarkedColumn.__doc__ = _("Toggle marked column")
	
	__gestures = {
		"kb:upArrow": "moveToPreviousRow",
		"kb:downArrow": "moveToNextRow",
		"kb:leftArrow": "moveToPreviousColumn",
		"kb:rightArrow": "moveToNextColumn",
		"kb:home": "moveToFirstColumn",
		"kb:end": "moveToLastColumn",
		"kb:control+home": "moveToFirstRow",
		"kb:control+end": "moveToLastRow",
		"kb:control+leftArrow": "moveToPreviousMarkedColumn",
		"kb:control+rightArrow": "moveToNextMarkedColumn",
		"kb:control+space": "toggleMarkedColumn",
		"kb:shift+space": "selectRow",
	}
