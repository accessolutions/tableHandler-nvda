# globalPlugins/tableHandler/fakeObjects/table.py
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

"""Fake table objects
"""

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


import weakref

from NVDAObjects import NVDAObject
import addonHandler
import api
import braille
import config
import controlTypes
from logHandler import log
from scriptHandler import getLastScriptRepeatCount
import speech

from ..behaviors import Cell, Row, TableManager
from ..tableUtils import getColumnSpanSafe, getRowSpanSafe
from ..textInfoUtils import WindowedProxyTextInfo, getField
from . import CHILD_ACCESS_GETTER, CHILD_ACCESS_ITERATION, CHILD_ACCESS_SEQUENCE, FakeObject


addonHandler.initTranslation()


class ColumnSeparator(FakeObject):
	"""Represents a column separator, as presented on a table row's braille region.
	"""
	
	roleText = "columnSeparator"



class FakeCell(Cell, FakeObject):
	"""Table Cell.
	
	Extend this class when there are no real control corresponding to the cell.  
	"""
	
	firstChild = None
	
	def __init__(self, *args, row=None, **kwargs):
		if "parent" not in kwargs:
			kwargs["parent"] = row
		else:
			kwargs["row"] = row
		super().__init__(*args, **kwargs)
		if not self.parent:
			log.error("No parent! args={}, kwargs={}".format(args, kwargs))
		#self._trackingInfo = [f"{self!r}({id(self)})"]
	
	def _get_basicText(self):
		func = getattr(self.row, "_getCellBasicText", None)
		if func is not None:
			return func(self.columnNumber)
		func = getattr(self.table, "_getCellBasicText", None)
		if func is not None:
			return func(self.rowNumber, self.columnNumber)
		raise NotImplementedError
	
	def _get_location(self):
		func = getattr(self.row, "_getCellLocation", None)
		if func is not None:
			return func(self.columnNumber)
		func = getattr(self.table, "_getCellLocation", None)
		if func is not None:
			return func(self.rowNumber, self.columnNumber)
		raise NotImplementedError
	
	_cache_next = False
	
	def _get_next(self):
		row = self.row
		if isinstance(row, FakeRow):
			return super().next
		return row._getCell(self.columnNumber + 1)
	
	_cache_previous = False
	
	def _get_previous(self):
		row = self.row
		if isinstance(row, FakeRow):
			return super().previous
		return row._getCell(self.columnNumber - 1)
	
	def _get_rowNumber(self):
		return self.row.rowNumber
	
	def getColumnHeaderText(self):
		func = getattr(self.row, "_getColumnHeaderText", None)
		if func is not None:
			return func(num)
		func = getattr(self.table, "_getColumnHeaderText", None)
		if func is not None:
			return func(self.columnNumber)
		return ""
	
	def getRowHeaderText(self):
		func = getattr(self.row, "_getRowHeaderText", None)
		if func is not None:
			return func(num)
		func = getattr(self.table, "_getRowHeaderText", None)
		if func is not None:
			return func(self.rowNumber)
		return ""
	
	def script_reportCurrentFocus(self, gesture):
		if getLastScriptRepeatCount() == 0:
			self.reportFocus()
		elif getLastScriptRepeatCount() == 1:
			# Translators: Announced when reporting system focus
			speech.speakMessage(_("System focus"))
			obj = NVDAObject.objectWithFocus()
			obj.reportFocus()
		#elif getLastScriptRepeatCount() == 2:
		#	cellBk = self.info.bookmark
		#	selBk = self.ti.selection.bookmark
		#	speech.speakMessage(f"cell {cellBk.startOffset} caret {selBk.startOffset}")


class ResizingCell(FakeObject):
	"""Table Cell being resized (braille column width)
	"""
	def __init__(self, cell=None):
		super().__init__(cell=cell, parent=cell.parent)
	
	def getBrailleRegions(self, review=False):
		try:
			regions = self.cell.getBrailleRegions(review=review)
		except NotImplementedError:
			raise
		except Exception:
			log.exception()
			raise
		assert regions
		region = regions[-1]
		region.obj = self
		region.isResizingColumnWidth = True
		return regions
	
	def getScript(self, gesture):
		func = super().getScript(gesture)
		if func:
			return func
		if (
			config.conf["tableHandler"]["brailleSetColumnWidthWithRouting"]
			and isinstance(gesture, braille.BrailleDisplayGesture)
			and gesture.id == "routing"
		):
			return None
		return self.script_done
	
	def setColumnWidthBraille(self, width):
		cell = self.cell
		table = cell.table
		oldColsAfter = getattr(cell, "columnsAfterInBrailleWindow", None)
		width = table._tableConfig.setColumnWidth(cell.columnNumber, width)
		braille.handler.handleUpdate(self)
		# Translators: Announced when adjusting the width in braille of a table column
		speech.speakMessage(_("Column width set to {count} braille cells").format(count=width))
		if getattr(cell, "effectiveColumnWidthBraille", 0) > width:
			speech.speakMessage(_("extended to {count}").format(count=cell.effectiveColumnWidthBraille))
		newColsAfter = getattr(cell, "columnsAfterInBrailleWindow", None)
		if oldColsAfter != newColsAfter:
			if newColsAfter:
				if newColsAfter == 1:
					# Translators: Announced when adjusting the width in braille of a table column
					msg = _("1 next column on the right")
				else:
					# Translators: Announced when adjusting the width in braille of a table column
					msg = _("{count} next columns on the right")
				speech.speakMessage(msg.format(count=newColsAfter))
			else:
				# Translators: Announced when adjusting the width in braille of a table column
				speech.speakMessage(_("The next column does not fit in this braille window"))
	
	def reportFocus(self):
		# Translators: Announced when initiating table column resizing in braille
		speech.speakMessage(_("Use the left and right arrows to set the desired column width in braille"))
	
	def script_done(self, gesture):
		# Translators: Announced when terminating table column resizing in braille
		speech.speakMessage(_("End of customizing"))
		self.cell.setFocus()
	
	def script_expand(self, gesture):
		cell = self.cell
		oldColsAfter = getattr(cell, "columnsAfterInBrailleWindow", None)
		width = cell.table._tableConfig.getColumnWidth(cell.columnNumber)
		self.setColumnWidthBraille(width + 1)
	
	# Translators: The description of a command.
	script_expand.__doc__ = _("Increase the width of the current column in braille")
	
	def script_shrink(self, gesture):
		cell = self.cell
		oldColsAfter = getattr(cell, "columnsAfterInBrailleWindow", None)
		width = cell.table._tableConfig.getColumnWidth(cell.columnNumber)
		self.setColumnWidthBraille(width - 1)
	
	# Translators: The description of a command.
	script_shrink.__doc__ = _("Decrease the width of the current column in braille")
	
	__gestures = {
		"kb:leftArrow": "shrink",
		"kb:rightArrow": "expand",
	}


class TextInfoDrivenFakeCell(FakeCell):
	
	_childAccess = CHILD_ACCESS_ITERATION
	
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
	
	def __del__(self):
		self.info = None
		# TODO: Fix delayed garbage collection
		#super().__del__()
	
	def _get_field(self):
		info = self.info
		if not info:
			return None
		field = getField(info, "controlStart", role=controlTypes.ROLE_TABLECELL)
		if field is None:
			field = getField(info, "controlStart", role=controlTypes.ROLE_TABLECOLUMNHEADER)
		if field is None:
			field = getField(info, "controlStart", role=controlTypes.ROLE_TABLEROWHEADER)
		if field is None:
			from pprint import pformat
			log.error(f"twf={pformat(info.getTextWithFields(), indent=4)}", stack_info=True)
		return field
	
	def _get_basicText(self):
		if self.info is None:
			return None
		return self.info.text
	
	def _get_columnNumber(self):
		if self.info is None:
			return None
		return self.field.get("table-columnnumber")
	
	def _get_columnSpan(self):
		if self.info is None:
			return None
		return self.field.get("table-columnsspanned")
	
	def _get_firstChild(self):
		info = self.info
		obj = info.NVDAObjectAtStart if info else None
		return obj if obj is not self else None
	
	def _get_location(self):
		if self.info is None:
			return None
		return self.info.NVDAObjectAtStart.location
	
	def _get_columnNumber(self):
		if self.info is None:
			return None
		return self.field.get("table-columnnumber")
	
	def _get_rowNumber(self):
		if self.info is None:
			return None
		return self.field.get("table-rownumber")
	
	def _get_rowSpan(self):
		if self.info is None:
			return None
		return self.field.get("table-rowsspanned")
	
	def getColumnHeaderText(self):
		if self.info is None:
			return None
		return self.field.get("table-columnheadertext")
	
	def getRole(self):
		if self.info is None:
			return super().getRole()
		return self.field.get("role")
	
	def getRowHeaderText(self):
		if self.info is None:
			return None
		return self.field.get("table-rowheadertext")
	
	def makeTextInfo(self, position):
		info = self.info
		if info is None:
			return None
		field = self.field
		if field is None:
			return None
		return WindowedProxyTextInfo(self, position, proxied=info, role=field["role"])


CELL_ACCESS_CHILDREN = "children"
CELL_ACCESS_MANAGED = "managed"


class FakeRow(Row, FakeObject):
	"""Table Row.
	
	Extend this class when there are no real control corresponding to the row.  
	"""
	
	CellClass = FakeCell
	_childAccess = CHILD_ACCESS_GETTER
	
	def __init__(self, *args, table=None, rowNumber=None, **kwargs):
		if "parent" not in kwargs:
			kwargs["parent"] = table
		else:
			kwargs["table"] = table
		super().__init__(*args, rowNumber=rowNumber, **kwargs)
		self._cache = {}
	
	def _get_columnCount(self):
		return self.table.columnCount
	
	def _get__cellAccess(self):
		return getattr(self.table, "_cellAccess", CELL_ACCESS_CHILDREN)
		
	def _createCell(self, *args, **kwargs):
		return self.CellClass(*args, row=self, **kwargs)
	
	def _iterCells(self):
		_cellAccess = self._cellAccess
		if _cellAccess == CELL_ACCESS_CHILDREN:
			for colNum, colSpan, cell in super()._iterCells():
				yield colNum, colSpan, cell
		elif _cellAccess == CELL_ACCESS_MANAGED:
			for colNum in range(1, self.columnCount + 1):
				cell = self._createCell(columnNumber=colNum) 
				yield colNum, getColumnSpanSafe(cell), cell
		else:
			raise ValueError("_cellAccess={}".format(repr(_cellAccess)))


class TextInfoDrivenFakeRow(FakeRow):
	
	CellClass = TextInfoDrivenFakeCell
	_childAccess = CHILD_ACCESS_SEQUENCE
	
	def __init__(self, *args, table=None, rowNumber=None, **kwargs):
		super().__init__(*args, table=table, rowNumber=rowNumber, **kwargs)
		self._cache = weakref.WeakKeyDictionary()
	
	def __del__(self):
		self._cache.clear()
		# TODO: Fix delayed garbage collection
		#super().__del__()
	
	def _get_children(self):
		return [cell for colNum, colSpan, cell in self._iterCells()]
		
	def _getCell(self, columnNumber, refresh=False):
		newCell = None
		if not refresh:
			# Fetch and cache the whole row as long as the last returned cell stays alive.
			oldCell, (oldColNum, colSpans, cache) = next(
				iter(self._cache.items()),
				(None, (None, {}, {}))
			)
			if oldCell:
				if not(oldColNum <= oldCell.columnNumber < oldColNum + colSpans[oldColNum]):
					# This discrepency is most likely due to an update of the document.
					self._cache.clear()
					return self._getCell(columnNumber, refresh=True)
				if oldColNum <= columnNumber < oldColNum + colSpans[oldColNum]:
					return oldCell
				del self._cache[oldCell]
			newCell = newColNum = None
			for colNum, cell in cache.items():
				if colNum <= columnNumber < colNum + colSpans[colNum]:
					newColNum, newCell = colNum, cell
					break
			if newCell:
				del cache[newColNum]
				# The previously returned cell was not in the cache
				cache[oldColNum] = oldCell
		if refresh or not newCell:
			cache = {}
			colSpans = {}
			index = []
			for colNum, colSpan, cell in self._iterCells(refresh=True):
				index.append((cell.info._startOffset, colNum, colSpan))
				if colNum <= columnNumber < colNum + colSpan:
					# Do not return until the whole row has been cached
					newColNum, newCell = colNum, cell
				else:
					# Only cache the cells that are not returned
					cache[colNum] = cell
				colSpans[colNum] = colSpan
				
		if newCell:
			# Keep the cache as long as the returned cell is alive
			self._cache[newCell] = (newColNum, colSpans, cache)
		return newCell
	
	def _iterCells(self, refresh=False):
		if not refresh:
			oldCell, (oldColNum, colSpans, cache) = next(
				iter(self._cache.items()),
				(None, (None, [], {}))
			)
			if oldCell is not None:
				for colNum in colSpans:
					cell = oldCell if colNum == oldColNum else cache[colNum]
					yield colNum, colSpans[colNum], cell
				#log.info("cells iterated from cache")
				return
		infos = self.table._iterCellsTextInfos(self.rowNumber)
		while True:
			try:
				info = next(infos, None)
			except RuntimeError:
				# The underlying call to `VirtualBuffer._iterTableCells` raises `StopIteration`
				# when calling `next` unguarded line 605.
				return
			if info is None:
				return
			cell = self._createCell(info=info)
			#log.info(f"new cell {cell!r} at {info._startOffset}")
			yield cell.columnNumber, getColumnSpanSafe(cell), cell


class FakeTableManager(TableManager, FakeObject):
	"""Table UX.
	
	Extend this class when there are no real control corresponding to the table.  
	"""
	
	RowClass = FakeRow
	_childAccess = CHILD_ACCESS_ITERATION
	
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._rows = weakref.WeakValueDictionary()
	
	def __del__(self):
		self._rows.clear()
		# TODO: Fix delayed garbage collection
		#super().__del__()
	
	_cache_firstChild = False
	
	def _get_firstChild(self):
		return self._getRow(1)

	def _get_tableID(self):
		return id(self)		
	
	def _canCreateRow(self, rowNumber):
		return 1 <= rowNumber <= self.rowCount
	
	def _createRow(self, *args, **kwargs):
		return self.RowClass(table=self, *args, **kwargs)
	
	def _getRow(self, rowNumber):
		row = self._rows.get(rowNumber)
		if row and not(rowNumber <= row.rowNumber < rowNumber + getRowSpanSafe(row)):
			# This discrepency is most likely due to an update of the document.
			row = None
		if not row and self._canCreateRow(rowNumber):
			row = self._createRow(rowNumber=rowNumber)
			if row:
				self._rows[rowNumber] = row
		# The current column number might be None eg. in a table caption
		if not row or not (row._currentCell or self._currentColumnNumber is None):
			self._rows.pop(rowNumber, None)
			return None
		return row


class StaticFakeTableManager(FakeTableManager):
	"""Sample `FakeTableManager` implementation.
	"""
	
	_cellAccess = CELL_ACCESS_MANAGED
	
	def __init__(self, *args, parent=None, headers=None, data=None, **kwargs):
		super().__init__(*args, parent=parent, **kwargs)
		self._headers = headers
		self._data = data
	
	def _get_columnCount(self):
		return max(len(row) for row in self._data)
	
	def _get_rowCount(self):
		return len(self._data)
		
	def _getCellBasicText(self, rowNumber, columnNumber):
		return self._data[rowNumber - 1][columnNumber - 1]
	
	def _getColumnHeaderText(self, columnNumber):
		return self._headers[columnNumber - 1]


def test():
	from .. import TableConfig
	t = StaticFakeTableManager(
		parent=api.getFocusObject(),
		headers=["Col A", "Col B", "Col C"],
		data=[
			["Cell A1", "Cell B1", "Cell C1"],
			["Cell A2", "Cell B2", "Cell C2"],
			["Cell A3", "Cell B3", "Cell C3"],
		],
		_tableConfig=TableConfig.get("Test StaticFakeTableManager")
	)
	t.setFocus()
