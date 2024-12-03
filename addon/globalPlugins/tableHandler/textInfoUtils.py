# globalPlugins/tableHandler/textInfoUtils.py
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

"""TextInfo utilities
"""

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


from typing import Optional
import sys

import textInfos.offsets


if sys.version_info[1] < 9:
    from typing import Mapping, Sequence
else:
    from collections.abc import Mapping, Sequence


class LaxSelectionTextInfo(textInfos.offsets.OffsetsTextInfo):
	"""An `OffsetsTextInfo` overlay that treats selection-unawareness as unselected.
	
	Allows to query for selection objects that do not implement this feature.
	"""
	
	def _get_selectionOffsets(self):
		try:
			return super().selectionOffsets
		except NotImplementedError:
			return 0, 0


class StaticTextInfo(LaxSelectionTextInfo):
	"""A `LaxSelectionTextInfo` presenting the text and fields provided at initialization.
	
	Allows to present richly formatted forged content.
	"""
	
	# Text is already provided as Python str.
	encoding = None
	
	def __init__(self, obj, position, textWithFields: textInfos.TextInfo.TextWithFieldsT):
		nestingLevel = 0
		offset = 0
		lineOffsets = self._lineOffsets = []
		for textOrField in textWithFields:
			if isinstance(textOrField, textInfos.FieldCommand):
				field = textOrField
				if field.command == "controlStart":
					nestingLevel += 1
				elif field.command == "controlEnd":
					nestingLevel -= 1
					if nestingLevel < 0:
						raise ValueError("textWithFields contains unmatched controlEnd")
				continue
			assert isinstance(textOrField, str)
			text = textOrField
			chunks = text.split("\n")
			while len(chunks) > 1:
				chunk = chunks.pop(0)
				offset += len(chunk)
				lineOffset.append(chunk)
			offset += len(chunks[0])
		lineOffsets.append(offset)		
		if nestingLevel > 0:
			raise ValueError("textWithFields contains unmatched controlStart")
		self._textWithFields: textInfos.TextInfo.TextWithFieldsT = textWithFields
		super().__init__(obj, position)
	
	def copy(self):
		return self.__class__(self.obj, self.bookmark, self._textWithFields)
	
	def getTextWithFields(self, formatConfig: Optional[Mapping] = None) -> textInfos.TextInfo.TextWithFieldsT:
		start = self._startOffset
		end = self._endOffset
		if start == end:
			return []
		return self._getFieldsInRange(start, end)
	
	def _getFieldsInRange(self, start: int, end: int) -> textInfos.TextInfo.TextWithFieldsT:
		twf: textInfos.TextInfo.TextWithFieldsT = []
		offset = 0
		inRange = False
		unclosedControlStartIndexes = []
		rangeStartIndex = rangeEndIndex = None
		for textOrField in self._textWithFields:
			if isinstance(textOrField, textInfos.FieldCommand):
				field = textOrField
				if field.command == "controlStart":
					unclosedControlStartIndexes.append(len(twf))
					if rangeEndIndex is not None:
						continue
				elif field.command == "controlEnd":
					controlStartIndex = unclosedControlStartIndexes.pop()
					if rangeStartIndex is None:
						del twf[controlStartIndex]
						continue
					if rangeEndIndex is not None and controlStartIndex >= rangeEndIndex:
						continue
				elif field.command == "formatChange" and rangeEndIndex is not None:
					continue
				twf.append(field)
				continue
			assert isinstance(textOrField, str)
			if rangeEndIndex is not None:
				continue
			text = textOrField
			chunkStart = max(0, start - offset)
			chunkEnd = max(0, end - offset)
			chunk = text[chunkStart:chunkEnd]
			if chunk:
				if rangeStartIndex is None:
					rangeStartIndex = len(twf)
				twf.append(chunk)
			offset += len(text)
			if end not in (None, -1) and offset >= end:
				rangeEndIndex = len(twf)
		return twf
	
	def _getLineOffsets(self, offset):
		start = end = 0
		for candidate in self._lineOffsets:
			if candidate <= offset:
				start = candidate
			elif candidate > offset:
				end = candidate
				break
		else:
			# Mimic the behavior of OffsetsTextInfo when offset exceeds
			# the story length.
			end = self._lineOffsets[-1]
		return start, end
	
	def _getTextRange(self, start, end):
		return "".join(
			textOrField
			for textOrField in self._getFieldsInRange(start, end)
			if isinstance(textOrField, str)
		)
	
	def _getStoryText(self):
		return "".join(
			textOrField
			for textOrField in self._textWithFields
			if isinstance(textOrField, str)
		)

	def _getStoryLength(self):
		return sum(
			len(textOrField)
			for textOrField in self._textWithFields
			if isinstance(textOrField, str)
		)


class WindowedProxyTextInfo(textInfos.offsets.OffsetsTextInfo):
	
	def __init__(self, obj, position, proxied=None, **containerCriteria):
		self.proxied = proxied
		self.containerCriteria = containerCriteria
		super().__init__(obj, position)
		if position == textInfos.POSITION_ALL:
			self._startOffset = 0
			self._endOffset = self._convertFromProxiedOffset(proxied._endOffset)
		else:
			self._startOffset = self._endOffset = 0
	
	def activate(self):
		info = self.proxied.copy()
		info._startOffset, info._endOffset = self._convertToProxiedOffsets(
			self._startOffset, self._endOffset
		)
		return info.activate()
	
	def copy(self):
		return type(self)(
			self.obj,
			self.basePosition,
			proxied=self.proxied,
			**self.containerCriteria
		)
	
	def _convertFromProxiedOffset(self, offset):
		startOffset = self.proxied._startOffset
		endOffset = self.proxied._endOffset + (1 if self.proxied.allowMoveToOffsetPastEnd else 0)
		return max(0, min(offset, endOffset) - startOffset)
	
	def _convertFromProxiedOffsets(self, *offsets):
		return tuple((self._convertFromProxiedOffset(offset) for offset in offsets))
	
	def _convertToProxiedOffset(self, offset):
		startOffset = self.proxied._startOffset
		endOffset = self.proxied._endOffset + (1 if self.proxied.allowMoveToOffsetPastEnd else 0)
		offset += startOffset
		return max(startOffset, min(endOffset, offset))
	
	def _convertToProxiedOffsets(self, *offsets):
		return tuple((self._convertToProxiedOffset(offset) for offset in offsets))
	
	def _get_boundingRects(self):
		info = self.proxied.copy()
		info._startOffset, info._endOffset = self._convertToProxiedOffsets(
			self._startOffset, self._endOffset
		)
		return info.boundingRects
	
	def _getCaretOffset(self):
		return self._convertFromProxiedOffset(self.proxied._getCaretOffset())
	
	def _setCaretOffset(self, offset):
		return self.proxied._setCaretOffset(self._convertToProxiedOffset(offset))
	
	def _getSelectionOffsets(self):
		return self._convertFromProxiedOffsets(*self.proxied.__getSelectionOffsets())
	
	def _setSelectionOffsets(self, start, end):
		return self.proxied._setSelectionOffsets(*self._convertToProxiedOffsets(start, end))
	
	def _getStoryLength(self):
		return len(self._getStoryText())
	
	def _getStoryText(self):
		return self._getTextRange(*self._convertFromProxiedOffsets(
			self.proxied._startOffset, self.proxied._endOffset
		))
	
	def _getTextRange(self, start, end):
		return self.proxied._getTextRange(*self._convertToProxiedOffsets(start, end))
	
	def _getFormatFieldAndOffsets(self, offset, formatConfig, calculateOffsets=True):
		formatField, (startOffset, endOffset) = self.proxied._getFormatFieldAndOffsets(
			self._convertToProxiedOffset(offset),
			formatConfig,
			calculateOffsets=calculateOffsets
		)
		return formatField, self._convertFromProxiedOffsets(startOffset, endOffset)
	
	def _calculateUniscribeOffsets(self, lineText, unit, relOffset):
		return self.proxied._calculateUniscribeOffsets(lineText, unit, relOffset)
	
	def _getCharacterOffsets(self, offset):
		return self._convertFromProxiedOffsets(
			*self.proxied._getCharacterOffsets(self._convertToProxiedOffset(offset))
		)
	
	def _getWordOffsets(self,offset):
		return self._convertFromProxiedOffsets(
			*self.proxied._getWordOffsets(self._convertToProxiedOffset(offset))
		)
	
	def _getLineNumFromOffset(self, offset):
		# TODO: Check that line numbers are indeed relative to the document, not to the position
		curNum = self.proxied._getLineNumFromOffset(self._convertToProxiedOffset(offset))
		if curNum is None:
			return None
		startNum = self.proxied._getLineNumFromOffset(self._convertToProxiedOffset(0))
		return curNum - startNum
	
	def _getLineOffsets(self, offset):
		return self._convertFromProxiedOffsets(
			*self.proxied._getLineOffsets(self._convertToProxiedOffset(offset))
		)
	
	def _getParagraphOffsets(self, offset):
		return self._convertFromProxiedOffsets(
			*self.proxied._getParagraphOffsets(self._convertToProxiedOffset(offset))
		)
	
	def _getReadingChunkOffsets(self, offset):
		return self._convertFromProxiedOffsets(
			*self.proxied._getReadingChunkOffsets(self._convertToProxiedOffset(offset))
		)
	
	def _getBoundingRectFromOffset(self, offset):
		return self.proxied._getBoundingRectFromOffset(self._convertToProxiedOffset(offset))
	
	def _getPointFromOffset(self, offset):
		return self.proxied._getPointFromOffset(self._convertToProxiedOffset(offset))
	
	def _getOffsetFromPoint(self, x, y):
		return self._convertFromProxiedOffsets(*self.proxied._getOffsetFromPoint(x, y))
	
	def _getNVDAObjectFromOffset(self, offset):
		obj = self.proxied._getNVDAObjectFromOffset(self._convertToProxiedOffset(offset))
		if obj is self.proxied.obj:
			return self.obj
		return obj
	
	def _getOffsetsFromNVDAObject(self, obj):
		if obj is self.obj:
			obj = self.proxied.obj
		return self._convertFromProxiedOffsets(*self.proxied._getOffsetsFromNVDAObject(obj))
	
	def _get_NVDAObjectAtStart(self):
		info = self.proxied.copy()
		info._startOffset, info._endOffset = self._convertToProxiedOffsets(
			self._startOffset, self._endOffset
		)
		obj = info.NVDAObjectAtStart
		if obj is self.proxied.obj:
			return self.obj
		return obj
	
	def _getUnitOffsets(self, unit, offset):
		return self._convertFromProxiedOffsets(
			*self.proxied._getUnitOffsets(unit, self._convertToProxiedOffset(offset))
		)
	
	def _get_pointAtStart(self):
		info = self.proxied.copy()
		info._startOffset, info._endOffset = self._convertToProxiedOffsets(
			self._startOffset, self._endOffset
		)
		return info.pointAtStart
	
	def getTextWithFields(self, formatConfig=None):
		return list(self.iterTextWithFields(formatConfig=formatConfig))
	
	def iterTextWithFields(self, formatConfig=None):
		info = self.proxied.copy()
		info._startOffset, info._endOffset = self._convertToProxiedOffsets(
			self._startOffset, self._endOffset
		)
		found = not self.containerCriteria
		level = 0
		for textOrField in info.getTextWithFields(formatConfig=formatConfig):
			if isinstance(textOrField, textInfos.FieldCommand):
				field = textOrField
				if field.command == "controlStart":
					field = field.field
					if not found:
						for key, value in self.containerCriteria.items():
							if key in field and field[key] != value:
								break
						else:
							found = True
						continue
					level += 1
				elif found and field.command == "controlEnd":
					level -= 1
					if level < 0:
						continue
			if not found:
				continue
			yield textOrField
	
	def _lineNumFromOffset(self, offset):
		# Defined in `NVDAObjects.IAccessible.IA2TextTextInfo` and oddly referenced in
		# `textInfos.offsets.OffsetsTextInfo.unitIndex` which in turn is not referenced
		# anywhere in NVDA core at least as of 2021.2.
		return -1
	
	def _getFirstVisibleOffset(self):
		info = self.proxied.copy()
		info._startOffset, info._endOffset = self._convertToProxiedOffsets(
			self._startOffset, self._endOffset
		)
		return self._convertFromProxiedOffset(info._getFirstVisibleOffset())
	
	def _getLastVisibleOffset(self):
		info = self.proxied.copy()
		info._startOffset, info._endOffset = self._convertToProxiedOffsets(
			self._startOffset, self._endOffset
		)
		return self._convertFromProxiedOffset(info._getLastVisibleOffset())


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
