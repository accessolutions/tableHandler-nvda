# globalPlugins/tableHandler/tableUtils.py
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

"""Table utilities
"""

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


from logHandler import log


def getColumnHeaderTextSafe(cell):
	try:
		return cell.columnHeaderText
	except NotImplementedError:
		return None


def getColumnSpanSafe(cell):
	try:
		span = cell.columnSpan
		if span is None:
			span = 1
		elif span < 1:
			log.error("cell={}, role={}, columnSpan={}".format(repr(cell), cell.role, span))
			span = 1
	except NotImplementedError:
		span = 1
	except Exception:
		log.exception("cell={}".format(repr(cell)))
		span = 1
	return span


def getRowHeaderTextSafe(cell):
	try:
		return cell.rowHeaderText
	except NotImplementedError:
		return None


def getRowSpanSafe(cell):
	try:
		span = cell.rowSpan
		if span < 1:
			log.error("cell={}, role={}, rowSpan={}".format(repr(cell), cell.role, span))
			span = 1
	except NotImplementedError:
		span = 1
	except Exception:
		log.exception("cell={}".format(repr(cell)))
		span = 1
	return span


def iterVirtualBufferTableCellsSafe(vbuf, tableID, startPos=None, direction="next", row=None, column=None):
	# This method has been seen to sometimes skip the first column when no row was specified
	# `VirtualBuffer._iterTableCells` raises `StopIteration` when calling `next` unguarded line 605.
	try:
		for item in vbuf._iterTableCells(
			tableID, startPos=startPos, direction=direction, row=row, column=column
		):
			yield item
	except StopIteration:
		return
