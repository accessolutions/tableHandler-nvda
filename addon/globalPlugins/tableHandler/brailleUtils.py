# globalPlugins/tableHandler/brailleUtils.py
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

"""Braille utilities
"""

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


import sys

import braille
from logHandler import log


class TabularBrailleBuffer(braille.BrailleBuffer):
	
	def __init__(self):
		super().__init__(handler=braille.handler)
	
	def bufferPosToRegionPos(self, bufferPos):
		# Reverse the logic to allow routing to the end of an extended or windowed region
		# while actually clicking a blank empty cell.
		for region, start, end in reversed(tuple(self.regionsWithPositions)):
			if start <= bufferPos:
				regionPos = bufferPos - start
				regionLastPos = end - start - 1
				if regionPos > regionLastPos:
					regionPos = regionLastPos
				return region, regionPos
		raise LookupError("No such position")
	
	def onRegionUpdatedBeforePadding(self, region):
		pass
	
	def onRegionUpdatedAfterPadding(self, region):
		pass
	
	def routeTo(self, windowPos):
		# Do not apply the usual windowEndPos check to allow to allow routing to the end
		# of an extended or windowed region while actually clicking a blank empty cell.
		pos = self.windowStartPos + windowPos
		region, pos = self.bufferPosToRegionPos(pos)
		region.routeTo(pos)
	
	def update(self):
		self.rawText = ""
		self.brailleCells = []
		self.cursorPos = None
		start = 0
		for region in self.visibleRegions:
			region.update()
			self.onRegionUpdatedBeforePadding(region)
			cells = region.brailleCells
			width = region.width
			if width is not None:
				if len(cells) > width:
					rawEnd = region.brailleToRawPos[width]
					region.rawText = region.rawText[:rawEnd]
					del region.rawToBraillePos[rawEnd:]
					del cells[width:]
					del region.brailleToRawPos[width:]
				extra = width - len(cells)
				if extra > 0:
					region.brailleCells += (0,) * extra
					region.rawText += " " * extra
					region.brailleToRawPos += (region.brailleToRawPos[-1],) * extra
					region.rawToBraillePos += (region.rawToBraillePos[-1],) * extra
			self.onRegionUpdatedAfterPadding(region)
			self.rawText += region.rawText
			self.brailleCells.extend(region.brailleCells)
			if region.brailleCursorPos is not None:
				self.cursorPos = start + region.brailleCursorPos
			start += len(cells)


def brailleCellDecimalStringToInteger(dec):
	res = 0
	if dec == "0":
		return 0
	for c in dec:
		if c not in "12345678":
			raise ValueError(dec)
		p = 1 << (int(c) - 1)
		if res & p:
			raise ValueError(dec)
		res |= p
	return res


def brailleCellsDecimalStringToIntegers(decs):
	res = []
	l = decs.split("-")
	for index, dec in enumerate(l):
		try:
			res.append(brailleCellDecimalStringToInteger(dec))
		except ValueError as e:
			if sys.version_info[0] == 3:
				raise ValueError(decs) from e
			else:
				raise ValueError(decs)
	return res


def brailleCellsDecimalStringToUnicode(decs):
	return brailleCellsIntegersToUnicode(brailleCellsDecimalStringToIntegers(decs))


def brailleCellIntegerToUnicode(value):
	if not(0 <= value <= 255):
		raise ValueError(value)
	return chr(0x2800 + value)


def brailleCellsIntegersToUnicode(ints):
	try:
		return "".join((brailleCellIntegerToUnicode(value) for value in ints))
	except ValueError as e:
		if sys.version_info[0] == 3:
			raise ValueError(decs) from e
		else:
			raise ValueError(decs)
