# globalPlugins/tableHandler/braille.py
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

"""Braille utilities
"""

# Get ready for Python 3
from __future__ import absolute_import, division, print_function

__version__ = "2021.09.09"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

import braille
from logHandler import log


class TabularBrailleBuffer(braille.BrailleBuffer):
	
	def __init__(self):
		super(TabularBrailleBuffer, self).__init__(handler=braille.handler)
	
	def update(self):
		self.rawText = ""
		self.brailleCells = []
		self.cursorPos = None
		start = 0
		for region in self.visibleRegions:
			region.update()
			cells = region.brailleCells
			width = region.width
#			log.info(f"@@@ >>> rawText={region.rawText}, width={width}, len={len(region.rawText)}/{len(region.brailleCells)}")
			if width is not None:
				if len(cells) > width:
					rawEnd = region.brailleToRawPos[width]
					region.rawText = region.rawText[:rawEnd]
					del region.rawToBraillePos[rawEnd:]
					del cells[width:]
					del region.brailleToRawPos[width:]
				while len(cells) < width:
					region.brailleToRawPos.append(len(region.rawText))
					region.rawToBraillePos.append(len(cells))
					cells.append(0)
					region.rawText += " "
#			log.info(f"@@@ <<< rawText={region.rawText}, width={width}, len={len(region.rawText)}/{len(region.brailleCells)}")
			self.rawText += region.rawText
			self.brailleCells.extend(cells)
			if region.brailleCursorPos is not None:
				self.cursorPos = start + region.brailleCursorPos
			start += len(cells)
