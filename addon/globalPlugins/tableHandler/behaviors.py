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


import enum
import weakref

from NVDAObjects import NVDAObject
import addonHandler
import api
from baseObject import ScriptableObject
import braille
import brailleInput
from buildVersion import version_detailed as NVDA_VERSION
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
	brailleCellsIntegersToUnicode,
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


class ColumnSeparatorPosition(enum.Enum):
	DEFAULT = enum.auto()
	BEFORE_SELECTION = enum.auto()
	AFTER_SELECTION = enum.auto()
	END_OF_WINDOW = enum.auto()
	EOW_AFTER_SEL = enum.auto()


class ColumnSeparatorRegion(braille.Region):
	
	SCHEMES = {
		"bar": {
			ColumnSeparatorPosition.DEFAULT: "4568",
			ColumnSeparatorPosition.BEFORE_SELECTION: "4568",
			ColumnSeparatorPosition.AFTER_SELECTION: "45678",
			ColumnSeparatorPosition.END_OF_WINDOW: "4568",
			ColumnSeparatorPosition.EOW_AFTER_SEL: "45678",
		},
		"bracket": {
			ColumnSeparatorPosition.DEFAULT: "4568",
			ColumnSeparatorPosition.BEFORE_SELECTION: "123478",
			ColumnSeparatorPosition.AFTER_SELECTION: "145678",
			ColumnSeparatorPosition.END_OF_WINDOW: "4568",
			ColumnSeparatorPosition.EOW_AFTER_SEL: "145678",
		},
		"twoSpaces": {
			ColumnSeparatorPosition.DEFAULT: "0-0",
			ColumnSeparatorPosition.BEFORE_SELECTION: "0-78",
			ColumnSeparatorPosition.AFTER_SELECTION: "78-0",
			ColumnSeparatorPosition.END_OF_WINDOW: "0",
			ColumnSeparatorPosition.EOW_AFTER_SEL: "78",
		},
		"barSpace": {
			ColumnSeparatorPosition.DEFAULT: "4568-0",
			ColumnSeparatorPosition.BEFORE_SELECTION: "4568-78",
			ColumnSeparatorPosition.AFTER_SELECTION: "74568-0",
			ColumnSeparatorPosition.END_OF_WINDOW: "4568",
			ColumnSeparatorPosition.EOW_AFTER_SEL: "45678",
		},
		"bracketSpace": {
			ColumnSeparatorPosition.DEFAULT: "4568-0",
			ColumnSeparatorPosition.BEFORE_SELECTION: "123478-0",
			ColumnSeparatorPosition.AFTER_SELECTION: "174568-0",
			ColumnSeparatorPosition.END_OF_WINDOW: "4568",
			ColumnSeparatorPosition.EOW_AFTER_SEL: "145678",
		},
		"spaceBarSpace": {
			ColumnSeparatorPosition.DEFAULT: "0-4568-0",
			ColumnSeparatorPosition.BEFORE_SELECTION: "0-4568-78",
			ColumnSeparatorPosition.AFTER_SELECTION: "78-74568-0",
			ColumnSeparatorPosition.END_OF_WINDOW: "0-4568",
			ColumnSeparatorPosition.EOW_AFTER_SEL: "78-45678",
		},
	}
	
	scheme = None
	widthDefault = None
	widthAtEoW = None
	
	@classmethod
	def handleConfigChange(cls):
		style = config.conf["tableHandler"]["brailleColumnSeparatorStyle"]
		# 0 - bar or bracket if no selected cell underline
		# 1 - same as 0, but bar then space if display size > 40
		# 2 - two spaces
		# 3 - bar then space
		# 4 - same as 3, but add a leading space if display size > 40
		if style in (0, 1):
			if style == 1 and braille.handler.displaySize > 40:
				cls.scheme = "barSpace"
			else:
				if config.conf["tableHandler"]["brailleShowSelection"]:
					cls.scheme = "bar"
				else:
					cls.scheme = "bracket"
		elif style == 2:
			cls.scheme = "twoSpaces"
		elif style in (3, 4):
			if style == 4 and braille.handler.displaySize >= 40:
				cls.scheme = "spaceBarSpace"
			else:
				if config.conf["tableHandler"]["brailleShowSelection"]:
					cls.scheme = "barSpace"
				else:
					cls.scheme = "bracketSpace"
		widths = set(
			len(brailleCellsDecimalStringToIntegers(cls.SCHEMES[cls.scheme][position]))
			for position in (
				ColumnSeparatorPosition.DEFAULT,
				ColumnSeparatorPosition.BEFORE_SELECTION,
				ColumnSeparatorPosition.AFTER_SELECTION,
			)
		)
		widthDefault = cls.widthDefault = widths.pop()
		assert not widths
		widths = set(
			len(brailleCellsDecimalStringToIntegers(cls.SCHEMES[cls.scheme][position]))
			for position in (
				ColumnSeparatorPosition.END_OF_WINDOW,
				ColumnSeparatorPosition.EOW_AFTER_SEL,
			)
		)
		widthAtEoW = cls.widthAtEoW = widths.pop()
		assert not widths
		assert widthDefault >= widthAtEoW
	
	def __init__(self, obj):
		super().__init__()
		self.obj = obj
	
	def routeTo(self, braillePos):
		if (
			braillePos == self.width - 1
			and self.obj.position not in (
				ColumnSeparatorPosition.END_OF_WINDOW, ColumnSeparatorPosition.EOW_AFTER_SEL
			) and self.scheme in (
				"twoSpaces", "barSpace", "bracketSpace", "spaceBarSpace"
			)
		):
			cell = self.obj.cellAfter
		else:
			cell = self.obj.cellBefore
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
		self.obj.cellBefore.script_modifyColumnWidthBraille(None)
	
	def update(self):
		pattern = self.SCHEMES[self.scheme][self.obj.position]
		self.brailleCells = cells = brailleCellsDecimalStringToIntegers(pattern)
		self.rawText = text = brailleCellsIntegersToUnicode(cells)
		self.width = width = len(cells)
		assert width == len(text)
		self.brailleToRawPos = self.rawToBraillePos = tuple(range(width))


class RowRegionBuffer(TabularBrailleBuffer):
	
	def __init__(self, rowRegion):
		super().__init__()
		self.rowRegion = weakref.proxy(rowRegion)
	
	def _get_windowEndPos(self):
		# Changed from stock implementation:
		#  - Also consider SELECTION_SHAPE as a word break
		endPos = self.windowStartPos + self.handler.displaySize
		cellsLen = len(self.brailleCells)
		if endPos >= cellsLen:
			return cellsLen
		if not config.conf["braille"]["wordWrap"]:
			return endPos
		# Try not to split words across windows.
		# To do this, break after the furthest possible space.
		cells = self.brailleCells
		for index in range(endPos - 1, self.windowStartPos - 1, -1):
			if cells[index] in (0, braille.SELECTION_SHAPE):
				return index
		return endPos
	
	def _set_windowEndPos(self, endPos):
		# Changed from stock implementation:
		#  - Also consider SELECTION_SHAPE as a word break
		"""Sets the end position for the braille window and recalculates the window start position based on several variables.
		1. Braille display size.
		2. Whether one of the regions should be shown hard left on the braille display;
			i.e. because of The configuration setting for focus context representation
			or whether the braille region that corresponds with the focus represents a multi line edit box.
		3. Whether word wrap is enabled."""
		startPos = endPos - self.handler.displaySize
		# Loop through the currently displayed regions in reverse order
		# If focusToHardLeft is set for one of the regions, the display shouldn't scroll further back than the start of that region
		for region, regionStart, regionEnd in reversed(list(self.regionsWithPositions)):
			if regionStart < endPos:
				if region.focusToHardLeft:
					# Only scroll to the start of this region.
					restrictPos = regionStart
					break
				elif config.conf["braille"]["focusContextPresentation"] != braille.CONTEXTPRES_CHANGEDCONTEXT:
					# We aren't currently dealing with context change presentation
					# thus, we only need to consider the last region
					# since it doesn't have focusToHardLeftSet, the window start position isn't restricted
					restrictPos = 0
					break
		else:
			restrictPos = 0
		if startPos <= restrictPos:
			self.windowStartPos = restrictPos
			return
		if not config.conf["braille"]["wordWrap"]:
			self.windowStartPos = startPos
			return
		try:
			# Try not to split words across windows.
			# To do this, break after the furthest possible block of spaces.
			# Find the start of the first block of spaces.
			# Search from 1 cell before in case startPos is just after a space.
			for index in range(endPos - 1, startPos - 2, -1):
				if cells[index] in (0, braille.SELECTION_SHAPE):
					startPos = index
					break
			else:
				raise ValueError()
			# Skip past spaces.
			for startPos in range(startPos, endPos):
				if cells[startPos] not in (0, braille.SELECTION_SHAPE):
					break
		except ValueError:
			pass
		# When word wrap is enabled, the first block of spaces may be removed from the current window.
		# This may prevent displaying the start of paragraphs.
		paragraphStartMarker = getParagraphStartMarker()
		if paragraphStartMarker and self.regions[-1].rawText.startswith(
			paragraphStartMarker + TEXT_SEPARATOR,
		):
			region, regionStart, regionEnd = list(self.regionsWithPositions)[-1]
			# Show paragraph start indicator if it is now at the left of the current braille window
			if startPos <= len(paragraphStartMarker) + 1:
				startPos = self.regionPosToBufferPos(region, regionStart)
		self.windowStartPos = startPos
	
	def onRegionUpdatedAfterPadding(self, region):
		if not isinstance(region, CellRegion):
			return
		# - Underline selection
		# - During resize: Retrieve effective width and count columns after
		brailleCells = region.brailleCells
		cell = region.obj
		colNum = cell.columnNumber
		if colNum == cell.table._currentColumnNumber:
			if config.conf["tableHandler"]["brailleShowSelection"]:
				brailleCells[:] = [
					brailleCell | braille.SELECTION_SHAPE
					for brailleCell in brailleCells[:]
				]
		from .fakeObjects.table import ResizingCell
		obj = self.rowRegion.obj
		if isinstance(obj, ResizingCell):
			resizingNum = obj.cell.columnNumber
			if colNum == resizingNum:
				self.resizingCell = cell
				obj.cell.brailleWindowNumber = self.rowRegion.windowNumber
				obj.cell.columnsAfterInBrailleWindow = 0
				obj.cell.effectiveColumnWidthBraille = region.width
			elif colNum > resizingNum:
				obj.cell.columnsAfterInBrailleWindow += 1


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
	
	def getColumns(self):
		from .fakeObjects.table import ColumnSeparator
		row = self.row
		cells = tuple(cell for colNum, colSpan, cell in row._iterCells())
		selNum = row.table._currentColumnNumber
		columns = []
		displaySize = braille.handler.displaySize
		sepWidthDefault = ColumnSeparatorRegion.widthDefault
		sepWidthAtEoW = ColumnSeparatorRegion.widthAtEoW
		winNum = 0
		winSize = 0
		for index, cell in enumerate(cells):
			cellWidth = cell.columnWidthBraille
			last = index + 1 >= len(cells)
			if not (
				(
					cellWidth is not None
					and winSize + cellWidth + (0 if last else sepWidthAtEoW) <= displaySize
				) or winSize == 0 or cellWidth is None
			):
				# Not enough room in the current window
				if columns:
					assert len(columns) >= 2
					# Shrink previous column separator
					prevWinNum, prevWidth, colSep = columns[-1]
					if colSep.position == ColumnSeparatorPosition.AFTER_SELECTION:
						colSep.position = ColumnSeparatorPosition.EOW_AFTER_SEL
						expandPrevCell = True
					elif colSep.position in (
						ColumnSeparatorPosition.DEFAULT,
						ColumnSeparatorPosition.BEFORE_SELECTION,
					):
						colSep.position == ColumnSeparatorPosition.END_OF_WINDOW
						expandPrevCell = True
					else:
						expandPrevCell = False
					columns[-1] = (prevWinNum, sepWidthAtEoW, colSep)
					if expandPrevCell:
						# Expand the last cell of this window
						prevWinNum, prevWidth, prevCell = columns[-2]
						winSize -= prevWidth + sepWidthDefault - sepWidthAtEoW
						prevWidth = displaySize - winSize
						columns[-2] = (prevWinNum, prevWidth, prevCell)
				# Move on to the next window
				winNum += 1
				winSize = 0
			if not last and cellWidth is None:
				# Expand to a whole window
				assert winSize == 0
				sepWidth = colSepWidthAtEoW
				cellWidth = displaySize - sepWidth
			elif last:
				# Allow to overflow to additional windows
				cellWidth = None
			else:
				sepWidth = sepWidthDefault
			columns.append((winNum, cellWidth, cell))
			if cell.columnNumber == selNum:
				if len(columns) > 1:
					# Change the separator pattern if on the same window
					colSep = columns[-2][2]
					if colSep.position == ColumnSeparatorPosition.DEFAULT:
						colSep.position = ColumnSeparatorPosition.BEFORE_SELECTION
				position = ColumnSeparatorPosition.AFTER_SELECTION
			else:
				position = ColumnSeparatorPosition.DEFAULT
			if last:
				# No column separator after the last column
				break
			columns.append((winNum, sepWidth, ColumnSeparator(
				parent=cell.parent,
				position=position,
				cellBefore=cell,
				cellAfter=cells[index + 1],
			)))
			winSize += cellWidth + sepWidth
		self.maxWindowNumber = winNum
		return columns
	
	def getWindowColumns(self):
		columns = []
		lastWinNum = 0
		obj = self.obj
		from .fakeObjects.table import ResizingCell
		if isinstance(obj, ResizingCell) and obj.forceFocus:
			obj.forceFocus = False
			forceNum = obj.cell.columnNumber
			self.windowNumber = None
			obj = obj.cell
		for winNum, width, obj in self.getColumns():
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
			elif isinstance(obj, ColumnSeparator):
				region = ColumnSeparatorRegion(obj)
			else:
				region = braille.NVDAObjectRegion(obj)
			region.width = width
			yield region
	
	def routeTo(self, braillePos):
		buffer = self.buffer
		obj = self.obj
		from .fakeObjects.table import ResizingCell
		if isinstance(obj, ResizingCell):
			resizingCell = obj
			resizingNum = obj.cell.columnNumber
			if config.conf["tableHandler"]["brailleSetColumnWidthWithRouting"]:
				pos = buffer.windowStartPos + braillePos
				for region, start, end in buffer.regionsWithPositions:
					obj = region.obj
					if isinstance(obj, Cell) and obj.columnNumber == resizingNum:
						width = pos - start
						if ColumnSeparatorRegion.scheme == "spaceBarSpace":
							width -= 1
						if width >= 0 and obj.columnWidthBraille != width:
							resizingCell.setColumnWidthBraille(width)
							return
			resizingCell.script_done(None)
			return
		buffer.routeTo(braillePos)
	
	def update(self):
		buffer = self.buffer
		buffer.regions = list(self.iterWindowRegions())
		buffer.update()
		self.rawText = buffer.windowRawText
		self.brailleCells = brailleCells = buffer.windowBrailleCells
		displaySize = braille.handler.displaySize
		unused = displaySize - len(brailleCells)
		if unused > 0:
			# Fill the whole display, so that cursor routing can be captured on the eventual unused portion
			# when resizing column widths.
			self.brailleCells = brailleCells + [0] * unused
		self.cursorPos = buffer.cursorWindowPos
		if NVDA_VERSION >= "2023.3":
			# Braille update is asynchronous as of NVDA PR #15163.
			# As the system focus did not change, this set might still contain
			# a region for a live TreeInterceptor.
			for region in braille.handler._regionsPendingUpdate.copy():
				if region is not self:
					braille.handler._regionsPendingUpdate.discard(region)
	
	def previousLine(self, start=False):
		# Pan left rather than moving to the previous line.
		buffer = self.buffer
		if buffer._previousWindow():
			self.rawText = buffer.windowRawText
			self.brailleCells = buffer.windowBrailleCells
			self.cursorPos = buffer.cursorWindowPos
		elif self.windowNumber > 0:
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
		elif self.windowNumber < self.maxWindowNumber:
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
				if not isinstance(focus, Cell) or focus.table is not table:
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
		self._lastReportedCellStates = set()
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
						return cell
					return cell.row._currentCell
		if self._currentRowNumber is None or self._currentColumnNumber is None:
			cell = self._firstDataCell
			if cell:
				self._currentRowNumber = cell.rowNumber
				self._currentColumnNumber = cell.columnNumber
		else:
			cell = self._getCell(self._currentRowNumber, self._currentColumnNumber)
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
		
		for state in curCell.states:
			if state in self._lastReportedCellStates:
				continue
			if state == controlTypes.STATE_SELECTED:
				content.append(controlTypes.stateLabels[state])
		self._lastReportedCellStates = curCell.states
		
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
			try:
				firstDataCell = self._firstDataCell
				rowCount -= firstDataCell.rowNumber - 1  # Row number is 1-based
			except Exception:
				pass
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
		curCell = self._currentCell
		if curCell is None:
			ui.message(translate("Not in a table cell"))
			return
		curNum = self._currentRowNumber
		firstCell = self._firstDataCell
		firstNum = None
		if firstCell is not None:
			firstNum = firstCell.rowNumber
			if firstNum < curNum and self._moveToRow(firstNum, notifyOnFailure=False):
				return
		# All columns might not have cells for all rows.
		# Let's itteratively try the first reachable row.
		for rowNum in range(curNum):
			if self._moveToRow(rowNum, notifyOnFailure=False):
				break
		else:
			# Repeat on failure
			self._reportRowChange()
	
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
