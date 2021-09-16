# globalPlugins/tableHandler/textInfos.py
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

"""Table Handler Global Plugin
"""

# Get ready for Python 3
from __future__ import absolute_import, division, print_function

__version__ = "2021.09.09"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

import textInfos.offsets


class LaxSelectionTextInfo(textInfos.offsets.OffsetsTextInfo):
	"""An `OffsetsTextInfo` overlay that treats selection-unawareness as unselected.
	
	Allows to query for selection objects that do not implement this feature.
	"""
	
	def _get_selectionOffsets(self):
		try:
			return super(FakeObjectTextInfo, self).selectionOffsets
		except NotImplementedError:
			return 0, 0


def getField(info, command, **criteria):
	if info.isCollapsed:
		info = info.copy()
		info.expand(textInfos.UNIT_CHARACTER)
	for cmdField in reversed(info.getTextWithFields()):
		if not (
			isinstance(cmdField, textInfos.FieldCommand)
			and cmdField.command == command
		):
			continue
		field = cmdField.field
		for key, value in criteria.items():
			if key in field and field[key] != value:
				break
		else:
			return field
