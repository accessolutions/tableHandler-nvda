# globalPlugins/tableHandler/fakeObjects/table.py
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

"""Fake table objects
"""

# Get ready for Python 3
from __future__ import absolute_import, division, print_function

__version__ = "2021.10.12"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

import six
import threading
import time
import weakref

import addonHandler
import api
import controlTypes
from logHandler import log
import speech
import textInfos
import textInfos.offsets
import ui

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
		super(FakeCell, self).__init__(*args, **kwargs)
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

	def _get_columnHeaderText(self):
		func = getattr(self.row, "_getColumnHeaderText", None)
		if func is not None:
			return func(self.columnNumber)
		func = getattr(self.table, "_getColumnHeaderText", None)
		if func is not None:
			return func(self.columnNumber)
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
			return super(FakeCell, self).next
		return row._getCell(self.columnNumber + 1)
	
	_cache_previous = False
	
	def _get_previous(self):
		row = self.row
		if isinstance(row, FakeRow):
			return super(FakeCell, self).previous
		return row._getCell(self.columnNumber - 1)
	
	def _get_rowNumber(self):
		return self.row.rowNumber


class TextInfoDrivenFakeCellThread(threading.Thread):
	
	POLL_INTERVAL = 100
	
	def __init__(self, cell):
		super(TextInfoDrivenFakeCellThread, self).__init__(
			name="TextInfoDrivenFakeCellThread({!r})".format(cell)
		)
		self.daemon = True
		self.cell = weakref.ref(cell)
	
	def run(self):
		while True:
			time.sleep(self.POLL_INTERVAL)
			cell = self.cell()
			if not cell:
				return
			
			def textInfoDrivenFakeCellUpdate():
				newCell = self.table._getCell(cell.rowNumber, cell.columnNumber)
				cell.info = newCell.info
				cell.row = newCell.row
			
			queueHandler.queueFunction(queueHandler.eventQueue, textInfoDrivenFakeCellUpdate)
			

class TextInfoDrivenFakeCell(FakeCell):
	
	_childAccess = CHILD_ACCESS_ITERATION
	
	def __init__(self, *args, **kwargs):
		super(TextInfoDrivenFakeCell, self).__init__(*args, **kwargs)
		#TextInfoDrivenFakeCellThread(self).start()
	
	def __del__(self):
		self.info = None
		super(TextInfoDrivenFakeCell, self).__del__()
	
	def _get_field(self):
		info = self.info
		if not info:
			return None
		field = getField(info, "controlStart", role=controlTypes.ROLE_TABLECELL)
		if field is None:
			field = getField(info, "controlStart", role=controlTypes.ROLE_TABLECOLUMNHEADER)
		if field is None:
			from pprint import pformat
			log.error(f"twf={pformat(info.getTextWithFields(), indent=4)}", stack_info=True)
		return field
	
	def _get_basicText(self):
		if self.info is None:
			return None
		return self.info.text
	
	def _get_columnHeaderText(self):
		if self.info is None:
			return None
		return self.field.get("table-columnheadertext")
	
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
	
	def _get_role(self):
		if self.info is None:
			return super(TextInfoDrivenFakeCell, self).role
		return self.field.get("role")
	
	def _get_rowNumber(self):
		if self.info is None:
			return None
		return self.field.get("table-rownumber")
	
	def _get_rowSpan(self):
		if self.info is None:
			return None
		return self.field.get("table-rowsspanned")
	
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
		super(FakeRow, self).__init__(*args, rowNumber=rowNumber, **kwargs)
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
			for colNum, colSpan, cell in super(FakeRow, self)._iterCells():
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
		super(TextInfoDrivenFakeRow, self).__init__(*args, table=table, rowNumber=rowNumber, **kwargs)
		self._cache = weakref.WeakKeyDictionary()
	
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
			if oldCell is not None:
				if oldColNum <= columnNumber < oldColNum + colSpans[oldColNum]:									
					return oldCell
				del self._cache[oldCell]
			newCell = newColNum = None
			for colNum, cell in cache.items():
				if colNum <= columnNumber < colNum + colSpans[colNum]:
					newColNum, newCell = colNum, cell
					break
			if newCell is not None:
				del cache[newColNum]
				# The previously returned cell was not in the cache
				cache[oldColNum] = oldCell
		if refresh or newCell is None:
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
			#from pprint import pformat
			#log.info(f"cells: {pformat(index, indent=4)}", stack_info=True)
				
		if newCell is not None:
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
	
# 	def __init__(self, *args, parent=None, **kwargs):
# 		super(FakeTableManager, self).__init__(*args, parent=parent, **kwargs)
	def __init__(self, *args, **kwargs):
		super(FakeTableManager, self).__init__(*args, **kwargs)
		self._rows = {}
	
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
		row = self._createRow(rowNumber=rowNumber)
		return row
		weakRow = self._rows.get(rowNumber)
		row = weakRow() if weakRow is not None else None
		if row is None and self._canCreateRow(rowNumber):
			row = self._createRow(rowNumber=rowNumber)
			if row is not None:
				self._rows[rowNumber] = weakref.ref(row)
		# The current column number might be None eg. in a table caption
		if row is None or not (row._currentCell or self._currentColumnNumber is None):
			self._rows.pop(rowNumber, None)
			return None
		return row


class StaticFakeTableManager(FakeTableManager):
	"""Sample `FakeTableManager` implementation.
	"""
	
	_cellAccess = CELL_ACCESS_MANAGED
	
	def __init__(self, *args, parent=None, headers=None, data=None, **kwargs):
		super(StaticFakeTableManager, self).__init__(*args, parent=parent, **kwargs)
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
	t = StaticFakeTableManager(
		parent=api.getFocusObject(),
		headers=["Col A", "Col B", "Col C"],
		data=[
			["Cell A1", "Cell B1", "Cell C1"],
			["Cell A2", "Cell B2", "Cell C2"],
			["Cell A3", "Cell B3", "Cell C3"],
		]
	)
	t.setFocus()
