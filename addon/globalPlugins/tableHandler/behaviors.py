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

__version__ = "2021.10.12"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

import six
import weakref

import addonHandler
import api
from baseObject import ScriptableObject
import braille
import brailleInput
import config
import controlTypes
from logHandler import log
import queueHandler
import scriptHandler
import speech
import textInfos
import ui
import vision

from globalPlugins.lastScriptUntimedRepeatCount import getLastScriptUntimedRepeatCount
from globalPlugins.withSpeechMuted import speechMuted, speechUnmutedFunction

from .coreUtils import translate
from .compoundDocuments import CompoundDocument
from .brailleUtils import TabularBrailleBuffer
from .fakeObjects import FakeObject
from .scriptUtils import getScriptGestureHint
from .tableUtils import getColumnSpanSafe, getRowSpanSafe


addonHandler.initTranslation()


SCRIPT_CATEGORY = "TableHandler"


class CellRegion(braille.TextInfoRegion):
	# TODO: Handle cursor routing (select/focus/activate)
	
	def routeTo(self, braillePos):
		cell = self.obj
		table = cell.table
		colNum = cell.columnNumber
		if not colNum == table._currentColumnNumber:
			table._moveToColumn(colNum, cell=cell)
			return
		super(CellRegion, self).routeTo(braillePos)
	
	def _getSelection(self):
		info = super(CellRegion, self)._getSelection()
		cell = self.obj
		if cell.columnNumber == cell.table._currentColumnNumber:
			#log.warning("expanding")
			info.expand(textInfos.UNIT_STORY)
		#else:
		#	log.info("not expanding")
		return info


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
		return "<Cell {}/[{}, {}] {}>".format(tableID, rowNumber, columnNumber, id(self))
	
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
				if getattr(focus, "table", None) is not self.table:
					table._hasFocusEntered = False
			
			queueHandler.queueFunction(queueHandler.eventQueue, loseFocus_trailer)
		
		super(Cell, self).event_loseFocus()


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
		return obj.focusRedirect or obj
	
	_cache_table = False
	
	def _get_table(self):
		return self.parent
	
	def _get_tableID(self):
		return self.table.tableID
	
	_cache__currentCell = False
	
	def _get__currentCell(self):
		curNum = self.table._currentColumnNumber
		if curNum is None:
			return None
		return self._getCell(curNum)
	
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
		super(TableManager, self).__init__(*args, **kwargs)
		self.initOverlayClass()
	
	def initOverlayClass(self):
		self._currentColumnNumber = 1
		self._currentRowNumber = 1
		self._markedColumnNumbers = {}
		#global _tableManager
		#_tableManager = self
	
	# The property is requested twice in a row by `eventHandler.executeEvent`
	_cache_focusRedirect = True
	
	def _get_focusRedirect(self):
		obj = self._currentRow
		# Oddly, NVDA's `executeEvent` does not care about chained redirection
		return obj.focusRedirect or obj
	
	_cache__currentCell = False
	
	def _get__currentCell(self):
		focus = api.getFocusObject()
		if isinstance(focus, Cell):
			cell = focus
			if cell.table is self and cell.rowNumber == self._currentRowNumber:
				if cell.columnNumber == self._currentColumnNumber:
					return cell
# 				log.info(f"nope1: focus={focus!r} passThrough={self.ti.passThrough}")
				return cell.row._currentCell
# 			log.info(
# 				f"nope2:"
# 				f" focus={focus!r}"
# 				f" passThrough={self.ti.passThrough}"
# 				f" tableID={self.tableID}"
# 				f" self={focus.table is self}"
# 				f" ({focus.table._currentRowNumber}, {focus.table._currentRowNumber})"
# 			)
# 		else:
# 			log.info(f"nope3: focus={focus!r} passThrough={self.ti.passThrough}")
		return self._getCell(self._currentRowNumber, self._currentColumnNumber)
	
	_cache__currentRow = False
	
	def _get__currentRow(self):
		focus = api.getFocusObject()
		if isinstance(focus, Cell):
			row = focus.row
			if row.table is self and row.rowNumber == self._currentRowNumber:
				return row
		curNum = self._currentRowNumber
		if curNum is None:
			return None
		return self._getRow(curNum)
	
	def reportFocus(self):  # TODO
		super(TableManager, self).reportFocus()
	
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
		queueHandler.queueFunction(queueHandler.eventQueue, self._reportColumnChange)
		return True
	
	def _moveToRow(self, rowNumber, row=None, notifyOnFailure=True):
		if row is None:
			row = self._getRow(rowNumber)
		if not row:
			if nofityOnFailure:
				# Translators: Reported when a table is empty.
				ui.message(translate("Edge of table"))
			return False
		self._currentRowNumber = rowNumber
		row.setFocus()
		# Wait for the cell to gain focus so it can be retrieved from `globalVars`
		# rather than being recomputed
		queueHandler.queueFunction(queueHandler.eventQueue, self._reportRowChange)
		return True
	
	@speechUnmutedFunction
	def _reportCellChange(self, axis=AXIS_COLUMNS):
		curRowNum = self._currentRowNumber
		curColNum = self._currentColumnNumber
		curCell = self._currentCell
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
		
		headerRowNum = self._tableConfig.columnHeaderRowNumber
		inColHeader = headerRowNum == curRowNum or curCell.role == controlTypes.ROLE_TABLECOLUMNHEADER
		headerColNum = self._tableConfig.rowHeaderColumnNumber
		inRowHeader = headerColNum == curColNum or curCell.role == controlTypes.ROLE_TABLEROWHEADER
		inHeader = inColHeader or inRowHeader
				
		if inHeader:
			if inColHeader:
				if inRowHeader:
					roleLabel = controlTypes.roleLabels[controlTypes.ROLE_TABLECOLUMNHEADER]
				else:
					roleLabel = controlTypes.roleLabels[controlTypes.ROLE_HEADER]
				if headerRowNum is False:
					# Translator: Announced when moving to a muted header cell
					content.append(_("Muted {header}").format(header=roleLabel))
				elif (
					isinstance(headerRowNum, int)
					and headerRowNum != curRowNum
					and curCell.role == controlTypes.ROLE_TABLECOLUMNHEADER
				):
					# Translator: Announced when moving to a superseded header cell
					content.append(_("Original {header}").format(header=roleLabel))
				elif axis==AXIS_ROWS or not inRowHeader:
					content.append(roleLabel)
			if inRowHeader:
				if inColHeader:
					roleLabel = controlTypes.roleLabels[controlTypes.ROLE_TABLEROWHEADER]
				else:
					roleLabel = controlTypes.roleLabels[controlTypes.ROLE_HEADER]
				if headerColNum is False:
					# Translator: Announced when moving to a muted header cell
					content.append(_("Muted {header}").format(header=roleLabel))
				elif (
					isinstance(headerColNum, int)
					and headerColNum != curColNum
					and curCell.role == controlTypes.ROLE_TABLEROWHEADER
				):
					# Translator: Announced when moving to a superseded header cell
					content.append(_("Original {header}").format(header=roleLabel))
				elif axis == AXIS_COLUMNS or not inColHeader:
					content.append(roleLabel)
		if (
			(axis == AXIS_COLUMNS and headerRowNum is None)
			or (axis == AXIS_ROWS and headerColNum is None)
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
				content.append(headerText)
		elif axis == AXIS_COLUMNS and headerRowNum not in (False, curRowNum):
			appendCell(headerRowNum)
		elif axis == AXIS_ROWS and headerColNum not in (False, curColNum):
			appendCell(headerColNum)
		
		content.append(curCell)
		
		if inColHeader:
			marked = self._markedColumnNumbers
			if curColNum in marked:
				if axis == AXIS_ROWS or curColNum != headerColNum:
					# Translators: Announced when moving to a marked header cell
					content.append(_("Column marked"))
					if axis == AXIS_ROWS:
						if len(marked) > 1:
							content.append(translate("{number} out of {total}").format(
								number=list(sorted(marked)).index(curColNum) + 1, total=len(marked)
							))
					if marked[curColNum]:
						# Translators: Announced when moving to a marked header cell
						content.append(_("with announce"))
					else:
						# Translators: Announced when moving to a marked header cell
						content.append(_("without announce"))
			elif marked and axis == AXIS_ROWS:
				count = len(marked)
				
				if len(marked) > 1:
					# Translators: Announced when moving to a header cell
					content.append(_("{count} columns marked").format(count=len(marked)))
				elif len(marked) == 1  and not isinstance(headerColNum, int):
					# Translators: Announced when moving to a header cell
					content.append(_("1 column marked"))
		if inRowHeader:
			# TODO: Implement marked rows
			marked = {headerRowNum: False} if isinstance(headerRowNum, int) else {}
			if curRowNum in marked:
				if axis == AXIS_COLUMNS or curRowNum != headerRowNum:
					# Translators: Announced when moving to a marked header cell
					content.append(_("Row marked"))
					if axis == AXIS_COLUMNS:
						if len(marked) > 1:
							content.append(translate("{number} out of {total}").format(
								number=list(marked).index(curRowNum) + 1, total=len(marked)
							))
					if marked[curRowNum]:
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
				marked = []
			else:
				marked = [
					colNum for colNum, announce in self._markedColumnNumbers.items()
					if announce and colNum not in (curColNum, headerColNum)
				]
			for colNum in marked:
				appendCell(colNum)
		
		try:
			doc = CompoundDocument(self, content)
		except Exception:
			log.exception("Error creating CompoundDocument with content={}".format(repr(content)))
			raise
		info = doc.makeTextInfo(textInfos.POSITION_ALL)
		# Store a strong reference to keep the `FakeObject` alive.
		info.obj = doc
		speech.speakTextInfo(info)

	def _reportColumnChange(self):
		self._reportCellChange(axis=AXIS_COLUMNS)

	def _reportFocusEntered(self):
		#self._reportColumnChange()
		pass
	
	def _reportRowChange(self):
		self._reportCellChange(axis=AXIS_ROWS)
	
	def _tableMovementScriptHelper(self, axis, direction, notifyOnFailure=True):
		"""Helper used to incrementally move along table axis.
		
		axis: Either AXIS_COLUMNS or AXIS_ROWS
		direction: Either DIRECTION_NEXT or DIRECTION_PREVIOUS
		"""
		if axis == AXIS_ROWS:
			fromObj = self._currentRow
			getNum = lambda obj: obj.rowNumber
			getObj = lambda num: self._getRow(num)
			getSpan = getRowSpanSafe
			moveTo = self._moveToRow
			repeat = self._reportRowChange
		elif axis == AXIS_COLUMNS:
			fromObj = self._currentCell
			getNum = lambda obj: obj.columnNumber
			getObj = lambda num: fromObj.row._getCell(num)
			getSpan = getColumnSpanSafe
			moveTo = self._moveToColumn
			repeat = self._reportColumnChange
		else:
			ValueError("axis={}".format(repr(axis)))
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
		return moveTo(getNum(toObj), toObj, notifyOnFailure=notifyOnFailure)
	
	def event_focusEntered(self):
		# We do not seem to receive focusEntered events with IE11
		self._receivedFocusEntered = True
		self._reportFocusEntered()
	
	def script_moveToFirstDataCell(self, gesture):
		cell = self._firstDataCell
		if not cell:
			ui.message(translate("Not in a table cell"))
			return
		rowNum = cell.rowNumber
		if self._currentRowNumber != rowNum:
			report = self._reportRowChange
		else:
			report = self._reportColumnChange
		self._currentRowNumber = rowNum
		self._currentColumnNumber = cell.columnNumber
		report()
		queueHandler.queueFunction(queueHandler.eventQueue, cell.setFocus)
	
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
		columnNumber = self._currentColumnNumber
		if not columnNumber:
			ui.message(translate("Not in a table cell"))
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
		columnNumber = self._currentColumnNumber
		curColIsMarked = False
		for marked in reversed(sorted(self._markedColumnNumbers)):
			if marked < columnNumber:
				self._moveToColumn(marked)
				return
			if marked == columnNumber:
				curColIsMarked = True
		# Translators: Emitted when attempting to move to a marked column
		speech.speakMessage(_("No previous marked column"))
		if curColIsMarked:
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
	
	def script_setColumnHeader(self, gesture):
		headerNum = self._tableConfig.columnHeaderRowNumber
		curNum = self._currentRowNumber
		#marked = self._markedRowNumbers
		#marked.pop(curNum, None)
		if headerNum == curNum:
			self._tableConfig.columnHeaderRowNumber = None
			try:
				headerText = self._currentCell.columnHeaderText
			except NotImplementedError:
				headerText = ""
			ui.message(_("Column header reset to default: {}").format(headerText))
		elif getLastScriptUntimedRepeatCount() > 0 and headerNum is None:
			self._tableConfig.columnHeaderRowNumber = False
			ui.message(_("Column header muted"))
		else:
			self._tableConfig.columnHeaderRowNumber = curNum
			#marked[curNum] = None
			ui.message(_("Row set as column header"))
	
	script_setColumnHeader.canPropagate = True
	# Translators: The description of a command.
	script_setColumnHeader.__doc__ = _("Set the current row as column header")
	
	def script_setRowHeader(self, gesture):
		headerNum = self._tableConfig.rowHeaderColumnNumber
		curNum = self._currentColumnNumber
		marked = self._markedColumnNumbers
		marked.pop(headerNum, None)
		if headerNum == curNum:
			self._tableConfig.rowHeaderColumnNumber = None
			try:
				headerText = self._currentCell.rowHeaderText
			except NotImplementedError:
				headerText = ""
			# Translators: Reported when customizing row headers
			ui.message(_("Row header reset to default: {}").format(headerText))
		elif getLastScriptUntimedRepeatCount() > 0 and headerNum is None:
			self._tableConfig.rowHeaderColumnNumber = False
			# Translators: Reported when customizing row headers
			ui.message(_("Row header muted"))
		else:
			self._tableConfig.rowHeaderColumnNumber = curNum
			marked[curNum] = None
			# Translators: Reported when customizing row headers
			ui.message(_("Column set as row header"))
	
	script_setRowHeader.canPropagate = True
	# Translators: The description of a command.
	script_setRowHeader.__doc__ = _("Set the current column as row header")
	
	def script_toggleMarkedColumn(self, gesture):
		curColNum = self._currentColumnNumber
		if not curColNum:
			ui.message(translate("Noe in a table cell"))
			return
		if curColNum == self._tableConfig.rowHeaderColumnNumber:
			# Translators: Reported when attempting to mark a column
			msg = _("This column is already marked as row header.")
			hint = getScriptGestureHint(
				TableManager,
				self.script_setRowHeader,
				# Translators: The {command} portion of a script hint message
				doc=_("reset")
			)
			if hint:
				msg += " " + hint
			ui.message(msg)
			return
		marked = self._markedColumnNumbers
		if curColNum in marked:
			announce = marked[curColNum]
			if announce:
				marked[curColNum] = False
				# Translators: Reported when toggling marked columns
				ui.message(_("Column {} marked without announce").format(curColNum))
				return
			del marked[curColNum]
			# Translators: Reported when toggling marked columns
			ui.message(_("Column {} unmarked").format(curColNum))
			return
		marked[curColNum] = True
		# Translators: Reported when toggling marked columns
		ui.message(_("Column {} marked with announce").format(curColNum))
	
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
		"kb:control+home": "moveToFirstDataCell",
		"kb:control+end": "moveToLastRow",
		"kb:control+leftArrow": "moveToPreviousMarkedColumn",
		"kb:control+rightArrow": "moveToNextMarkedColumn",
		"kb:control+upArrow": "moveToFirstRow",
		"kb:control+downArrow": "moveToLastRow",
		"kb:NVDA+shift+c": "setColumnHeader",
		"kb:NVDA+shift+r": "setRowHeader",
		"kb:control+space": "toggleMarkedColumn",
		"kb:shift+space": "selectRow",
	}
