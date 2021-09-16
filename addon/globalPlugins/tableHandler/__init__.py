# globalPlugins/tableHandler.py
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

__version__ = "2021.09.09"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

import six
import weakref

from NVDAObjects import DynamicNVDAObjectType, IAccessible, NVDAObject, UIA
import addonHandler
import api
from baseObject import AutoPropertyObject, ScriptableObject
import braille
import brailleInput
import browseMode
import compoundDocuments
import config
import controlTypes
import eventHandler
import globalPluginHandler
import inputCore
from keyboardHandler import KeyboardInputGesture
from logHandler import log
import oleacc
import queueHandler
import scriptHandler
import speech
import textInfos
import textInfos.offsets
from treeInterceptorHandler import TreeInterceptor
import ui
import vision


try:
	REASON_CARET = controlTypes.OutputReason.CARET
	REASON_ONLYCACHE = controlTypes.OutputReason.ONLYCACHE
except AttributeError:
	# NVDA < 2021.1
	REASON_CARET = controlTypes.REASON_CARET
	REASON_ONLYCACHE = controlTypes.REASON_ONLYCACHE


# addonHandler.initTranslation()


SCRIPT_CATEGORY = "TableHandler"


# def _setFocusObject(obj):
# 	from .utils import getObjLogInfo
# 	
# 	log.info(f">>> api.setFocusObject({getObjLogInfo(obj)})")
# 	res = _setFocusObject.super(obj)
# 	import globalVars
# 	log.info(f"<<< api.setFocusObject: {getObjLogInfo(globalVars.focusObject)})")
# 
# _setFocusObject.super = api.setFocusObject
# api.setFocusObject = _setFocusObject


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	
	def __init__(self):
		super(GlobalPlugin, self).__init__()
		initialize()
	
	def chooseNVDAObjectOverlayClasses(self, obj, clsList):  # TODO
		role = obj.role
		if role == controlTypes.ROLE_DOCUMENT:
			from .browseMode import TableHandlerDocument
			clsList.insert(0, TableHandlerDocument)
	
	def terminate(self):
		terminate()
	
	def script_toggleTableMode(self, gesture):
		from .fakeObjects.table import TextInfoDrivenFakeCell
		from .browseMode import TABLE_MODE, reportPassThrough
		focus = api.getFocusObject()
		ti = focus.treeInterceptor if focus else None
		if ti.passThrough == TABLE_MODE:
# 			if ti._currentTable is not None:
# 				ti._tableManagers.pop(ti._currentTable.tableID, None)
			ti.passThrough = False
			reportPassThrough(ti)
			return
		info = api.getReviewPosition()
		table = getTableManager(info=info, setPosition=True, force=True)
		if table:
			ti = table.treeInterceptor
			table.setFocus()
			return
		# Translators: Reported when attempting to switch to table mode
		ui.message(_("No suitable table found"))
			
	
	script_toggleTableMode.ignoreTreeInterceptorPassThrough = True
	# Translators: The description of a command.
	script_toggleTableMode.__doc__ = "Toggle table mode."
	
	__gestures = {
		"kb:nvda+control+shift+space": "toggleTableMode"
	}


_handlers = ["Table handler not initialized"]


def initialize():
	global _handlers
	from .virtualBuffers import VBufTableHandler
	_handlers[:] = [VBufTableHandler()]


def terminate():
	_handlers = ["Table handler terminated"]


def registerTableHandler(handler):
	_handlers.insert(0, handler)


def getTableManager(**kwargs):
	table = None
	for index, handler in enumerate(_handlers.copy()):
		if isinstance(handler, weakref.ReferenceType):
			handler = handler()
			if not handler:
				del _handlers[index]
				continue
		try:
			table = handler.getTableManager(**kwargs)
		except Exception:
			log.exception("handler={!r}, kwargs={!r}".format(handler, kwargs))
			continue
		if table:
			return table


class TableConfig(object):
	
	def __init__(self, defaultColumnWidth=10, columnsWidths=None):
		self.defaultColumnWidth = defaultColumnWidth
		if columnsWidths is not None:
			self.columnsWidths = columnsWidths
		else:
			self.columnsWidths = {}
	
	def getColumnWidth(self, rowNumber, columnNumber):
		columnsWidths = self.columnsWidths
		try:
			if isinstance(columnsWidths, (list, tuple)):
				return columnsWidths[columnNumber - 1]
			else:
				return columnsWidths[columnNumber]
		except (AttributeError, LookupError):
			pass
		return self.defaultColumnWidth


class TableHandler(object):

	def getTableManager(self, **kwargs):
		raise NotImplementedError
	
	def getTableConfig(self, **kwargs):
		return TableConfig()
