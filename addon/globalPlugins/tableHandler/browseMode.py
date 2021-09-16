# globalPlugins/tableHandler/browseMode.py
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

import six
import weakref

import addonHandler
import api
from baseObject import AutoPropertyObject
import browseMode
import config
import controlTypes
from logHandler import log
import queueHandler
import speech
import textInfos
import textInfos.offsets
from treeInterceptorHandler import TreeInterceptor
import ui

from . import getTableManager
from .fakeObjects import FakeObject
from .utils import ScriptWrapper, catchAll, getDynamicClass, getObjLogInfo


try:
	REASON_CARET = controlTypes.OutputReason.CARET
	REASON_ONLYCACHE = controlTypes.OutputReason.ONLYCACHE
except AttributeError:
	# NVDA < 2021.1
	REASON_CARET = controlTypes.REASON_CARET
	REASON_ONLYCACHE = controlTypes.REASON_ONLYCACHE


addonHandler.initTranslation()


SCRIPT_CATEGORY = "TableHandler"



class TableMode(object):
	"""Used to represent Table Mode as an alternative value of `TreeInterceptor.passThrough`
	
	See `TABLE_MODE`.
	"""
	
	def __bool__(self):
		# Mostly considered as Browse Mode
		return False
	
	def __repr__(self):
		return "<TableMode>"


TABLE_MODE = TableMode()


def reportPassThrough(treeInterceptor, onlyIfChanged=True):
	if treeInterceptor.passThrough == TABLE_MODE:
		if browseMode.reportPassThrough.last is not treeInterceptor.passThrough:
			# Translators: Announced when switching to Table Mode
			speech.speakMessage(_("Table Mode"))
		browseMode.reportPassThrough.last = treeInterceptor.passThrough
		return
	browseMode.reportPassThrough(treeInterceptor, onlyIfChanged=onlyIfChanged)


class TableHandlerDocument(AutoPropertyObject):
	"""Integrate Table UX into a document.
	
	This class is intended to be used as an overlay to an `NVDAObject` with role document.
	"""
	
	def _get_treeInterceptorClass(self):
		# Might raise NotImplementedError on purpose.
		superCls = super(TableHandlerDocument, self).treeInterceptorClass
		if not issubclass(
			superCls,
			browseMode.BrowseModeDocumentTreeInterceptor
		):
			return superCls
		return getDynamicClass((TableHandlerTreeInterceptor, superCls))


class TableHandlerTreeInterceptor(browseMode.BrowseModeDocumentTreeInterceptor):
	"""Integrate Table UX into a `BrowseModeDocumentTreeInterceptor`.
	""" 
	
	def __init__(self, rootNVDAObject):
		super(TableHandlerTreeInterceptor, self).__init__(rootNVDAObject)
		
		self.autoTableMode = False
		self._currentTable = None		
		
	def __contains__(self, obj):
		if self.passThrough == TABLE_MODE:
			if isinstance(obj, FakeObject):
				return getattr(obj, "treeInterceptor", None) is self
		else:
			return super(TableHandlerTreeInterceptor, self).__contains__(obj)
	
	def _set_passThrough(self, state):
		if self._passThrough == state:
			return
		if state == TABLE_MODE:
			table = self._currentTable
			if table is None:
				table = self._currentTable = getTableManager(
					info=self.selection,
					setPosition=True,
					force=True
				)
			if table is None:
				raise Exception("No table at current position")
			self._passThrough = state
			queueHandler.queueFunction(queueHandler.eventQueue, table.setFocus)
			return
		if self.passThrough == TABLE_MODE:
			self._passThrough = None
			api.setFocusObject(self._currentTable.parent)
# 			if state:
# 				log.error("oops! FOCUS MODE", stack_info=True)
# 			else:
# 				# Switch from Table Mode to Browse Mode
# 				obj = api.getFocusObject()
# 				self._focusLastFocusableObject()
# 				if api.getFocusObject() is obj:
# 					# Focus has not moved
# 					obj = NVDAObject.objectWithFocus()
# 					if obj.treeInterceptor is self:
# 						log.info("back to real focus")
# 						api.setFocusObject(obj)
# 						log.info(f"back to real focus: {api.getFocusObject()}")
# 					else:
# 						args=(
# 							obj.event_windowHandle,
# 							obj.event_objectID,
# 							obj.event_childID
# 						)
# 						log.info(f"{args}")
# 						obj = IAccessible.getNVDAObjectFromEvent(*args)
# 						log.info(f"redeemed: {obj}")
# 						if obj and obj.treeInterceptor is self:
# 							api.setFocusObject(obj)
# 							log.info("back to redeemed")
# 						else:
# 							log.info("back to root")
# 							api.setFocusObject(self.rootNVDAObject)
# 				else:
# 					log.info("did move")
		super(TableHandlerTreeInterceptor, self)._set_passThrough(state)
# 		if self.passThrough != TABLE_MODE and isinstance(api.getFocusObject(), FakeObject):
# 			log.error("Mismatch!", stack_info=True)
	
# 	def _set_selection(self, info, reason=REASON_CARET):
# 		if self.passThrough != TABLE_MODE and isinstance(api.getFocusObject(), FakeObject):
# 			log.error("Mismatch!", stack_info=True)
# 		if self.isReady:
# 			prevTable = self._currentTable
# 			table = self._currentTable = self._getTableManagerAt(info, setPosition=True)
# 			if self.passThrough == TABLE_MODE:
# 				self.passThrough = False
# 				reportPassThrough(self)
# 			elif table is not None and table is not prevTable:
# 				info.updateSelection()
# 				self.passThrough = TABLE_MODE
# 				reportPassThrough(self)
# 				return
# 		super(TableHandlerTreeInterceptor, self)._set_selection(info, reason=reason)
# 		if self.passThrough != TABLE_MODE and isinstance(api.getFocusObject(), FakeObject):
# 			log.error("Mismatch!", stack_info=True)
	
	@catchAll(log)
	def getAlternativeScript(self, gesture, func):
		func = super(TableHandlerTreeInterceptor, self).getAlternativeScript(gesture, func)
		if func is None:
			return func
		disableTableModeBefore = getattr(func, "disableTableModeBefore", False)
		restoreTableModeAfter = getattr(func, "restoreTableModeAfter", False)
		restoreTableModeAfterIfBrowseMode = getattr(func, "restoreTableModeAfterIfBrowseMode", False)
		
		if not (
			disableTableModeBefore
			or restoreTableModeAfter
			or restoreTableModeAfterIfBrowseMode
		):
			return func
		
		def override(gesture, script):
			passThroughBefore = self.passThrough
			tableModeBefore = passThroughBefore == TABLE_MODE
			if tableModeBefore and disableTableModeBefore:
				self.passThrough = False
			if tableModeBefore and not (restoreTableModeAfter or restoreTableModeAfterIfBrowseMode):
				before = self.selection.copy()
			script(gesture)
			if False and tableModeBefore and not self.passThrough and not (
				restoreTableModeAfter or restoreTableModeAfterIfBrowseMode
			):
				after = self.selection.copy()
				if (
					before.compareEndPoints(after, "startToStart") == 0
					and before.compareEndPoints(after, "endToEnd") == 0
				):
					log.info("No movement, restoring TABLE_MODE")
					self.passThrough = TABLE_MODE
			if False and tableModeBefore and (restoreTableModeAfter or (
				not self.passThrough and restoreTableModeAfterIfBrowseMode
			)):
				log.info("Restoring TABLE_MODE")
				self.passThrough = TABLE_MODE
			if self.passThrough != passThroughBefore:
				reportPassThrough(self)
		
		return ScriptWrapper(func, override)
	
	def getBrailleRegions(self, review=False):
		if self.passThrough == TABLE_MODE:
			if self._currentTable is not None:
				cell = self._currentTable._currentCell
				if cell is not None:
					return cell.getBrailleRegions(review=review)
				# TODO: Handle braille reporting of empty tables
		return super(TableHandlerTreeInterceptor, self).getBrailleRegions(review=review)
	
	@catchAll(log)
	def getScript(self, gesture):
		if self.passThrough == TABLE_MODE:
			table = self._currentTable
			if table is not None:
				cell = table._currentCell
				if cell is not None:
					func = cell.getScript(gesture)
					if func is not None:
						return func
				row = table._currentRow
				if row is not None:
					func = row.getScript(gesture)
					if func is not None:
						return func
				func = table.getScript(gesture)
				if func is not None:
					return func
		func = super(TableHandlerTreeInterceptor, self).getScript(gesture)
		if func is not None:
			func = ScriptWrapper(
				func,
				disableTableModeBefore=getattr(func, "disableTableModeBefore", True)
			)
		return func
	
	def makeTextInfo(self, position):
		if isinstance(position, FakeObject):
			return position.makeTextInfo(position)
		return super(TableHandlerTreeInterceptor, self).makeTextInfo(position)
	
	def shouldPassThrough(self, obj, reason=None):
		if isinstance(obj, FakeObject):
			return False
		return super(TableHandlerTreeInterceptor, self).shouldPassThrough(obj, reason=reason)
	
	def _focusLastFocusableObject(self, activatePosition=False):
		"""Used when auto focus focusable elements is disabled to sync the focus
		to the browse mode cursor.
		When auto focus focusable elements is disabled, NVDA doesn't focus elements
		as the user moves the browse mode cursor. However, there are some cases
		where the user always wants to interact with the focus; e.g. if they press
		the applications key to open the context menu. In these cases, this method
		is called first to sync the focus to the browse mode cursor.
		"""
		obj = self.currentFocusableNVDAObject
		log.info(f"currentFocusableNVDAObject={getObjLogInfo(obj)}")
		if obj!=self.rootNVDAObject and self._shouldSetFocusToObj(obj) and obj!= api.getFocusObject():
			obj.setFocus()
			if api.getFocusObject() is not obj:
				api.setFocusObject(obj)
			# We might be about to activate or pass through a key which will cause
			# this object to change (e.g. checking a check box). However, we won't
			# actually get the focus event until after the change has occurred.
			# Therefore, we must cache properties for speech before the change occurs.
			speech.speakObject(obj, REASON_ONLYCACHE)
			self._objPendingFocusBeforeActivate = obj
		if activatePosition:
			# Make sure we activate the object at the caret, which is not necessarily focusable.
			self._activatePosition()
	
	def _shouldSetFocusToObj(self, obj):
		if isinstance(obj, FakeObject):
			log.warning("wut?", stack_info=True)
			return False
		return super(TableHandlerTreeInterceptor, self)._shouldSetFocusToObj(obj)
	
	def _shouldIgnoreFocus(self, obj):
		if isinstance(obj, FakeObject):
			log.warning("wut?", stack_info=True)
			return False
		return super(TableHandlerTreeInterceptor, self)._shouldIgnoreFocus(obj)
	
	def _getTableCellCoordsIncludingLayoutTables(self, info):
		"""
		Fetches information about the deepest table cell at the given position.
		Derived from `DocumentWithTableNavigation._getTableCellAt` to never exclude layout tables.
		@param info:  the position where the table cell should be looked for.
		@type info: L{textInfos.TextInfo}
		@returns: a tuple of table ID, is layout, row number, column number, row span, and column span.
		@rtype: tuple
		@raises: LookupError if there is no table cell at this position.
		"""
		if info.isCollapsed:
			info = info.copy()
			info.expand(textInfos.UNIT_CHARACTER)
		fields=list(info.getTextWithFields())
		# If layout tables should not be reported, we should First record the ID of all layout tables so that we can skip them when searching for the deepest table
		layoutIDs=set()
		if not config.conf["documentFormatting"]["includeLayoutTables"]:
			for field in fields:
				if isinstance(field, textInfos.FieldCommand) and field.command == "controlStart" and field.field.get('table-layout'):
					tableID=field.field.get('table-id')
					if tableID is not None:
						layoutIDs.add(tableID)
		for field in reversed(fields):
			if not (isinstance(field, textInfos.FieldCommand) and field.command == "controlStart"):
				# Not a control field.
				continue
			attrs = field.field
			tableID=attrs.get('table-id')
# 			if tableID is None or tableID in layoutIDs:
			if tableID is None:
				continue
			if "table-columnnumber" in attrs and not attrs.get('table-layout'):
				break
		else:
			raise LookupError("Not in a table cell")
		return (attrs["table-id"],
			tableID in layoutIDs,
			attrs["table-rownumber"], attrs["table-columnnumber"],
			attrs.get("table-rowsspanned", 1), attrs.get("table-columnsspanned", 1))
	
# 	def _getTableManager(self, info, setPosition=False, includeLayoutTables=False, force=False):
# 		table = getTableManager(info, force=force)
		
# 		func = self._getTableCellCoordsIncludingLayoutTables
# 		try:
# 			tableID, isLayout, rowNum, colNum, rowSpan, colSpan = func(info)
# 		except LookupError:
# 			if setPosition:
# 				# No table at the position we are moving to.
# 				# Let's forget the eventual suspended 
# 				self.suspendedTableModeTableID = None
# 			return None
# 		tableMgr = self._tableManagers.get(tableID)
# 		if (
# 			tableMgr is None
# 			and (includeLayoutTables or not isLayout)
# 			and (force or self.autoTableMode)
# 		):
# 			tableMgr = VBufFakeTableManager(
# 				#parent=self.rootNVDAObject,
# 				tableID=tableID,
# 				treeInterceptor=self,
# 				startPos=info,
# 			)
# 		if table:
# 			if setPosition:
# 				table._currentRowNumber = rowNum
# 				table._currentColumnNumber = colNum
# 			if tableID is not None:
# 				self._tableManagers[tableID] = tableMgr
# 		return tableMgr
	
# 	def _quickNavScript(self, gesture, itemType, direction, errorMessage, readUnit):
# 		log.info("_quickNavScript")
# 		return super(TableHandlerTreeInterceptor, self)._quickNavScript(gesture, itemType, direction, errorMessage, readUnit)
	
# 	def event_treeInterceptor_gainFocus(self):
# 		log.warning(f">>> event_treeInterceptor_gainFocus!! pre {self.passThrough} / {self._currentTable} / {self._getTableManagerAt(self.selection)}")
# 		super(TableHandlerTreeInterceptor, self).event_treeInterceptor_gainFocus()
# 		log.warning(f">>> event_treeInterceptor_gainFocus!! mid {self.passThrough} / {self._currentTable} / {self._getTableManagerAt(self.selection)}")
# 		self.selection = self.selection
# 		log.warning(f">>> event_treeInterceptor_gainFocus!! post {self.passThrough} / {self._currentTable} / {self._getTableManagerAt(self.selection)}")
		
# 		if self.passThrough is False and self._currentTable is None and self._getTableManagerAt(self.selection):
# 			log.error("Restored!")
# 			self.passThrough = TABLE_MODE
# 		log.warning(f"<<< event_treeInterceptor_gainFocus!! {self.passThrough} / {self._currentTable} / {self._getTableManagerAt(self.selection)}")

	
	def event_gainFocus(self, obj, nextHandler):
#		log.info(f"TableHandlerTreeInterceptor.event_gainFocus({obj!r}, {nextHandler!r})")
		if isinstance(obj, FakeObject):
			nextHandler()
			return
		super(TableHandlerTreeInterceptor, self).event_gainFocus(obj, nextHandler)
	
	def script_disablePassThrough(self, gesture):
#		log.info("script_disablePassThrough")
		if self.passThrough == TABLE_MODE:
			self.passThrough = False
			reportPassThrough(self)
			return
		super(TableHandlerTreeInterceptor, self).script_disablePassThrough(gesture)
	
	script_disablePassThrough.ignoreTreeInterceptorPassThrough = True

