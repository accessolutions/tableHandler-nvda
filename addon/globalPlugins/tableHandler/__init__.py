# globalPlugins/tableHandler/__init__.py
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

__version__ = "2021.09.28"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

import six
import weakref

import addonHandler
import api
import controlTypes
import globalPluginHandler
from logHandler import log
import ui

from .coreUtils import translate


addonHandler.initTranslation()


SCRIPT_CATEGORY = "TableHandler"


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	
	def __init__(self):
		super(GlobalPlugin, self).__init__()
		initialize()
	
	def chooseNVDAObjectOverlayClasses(self, obj, clsList):  # TODO
		role = obj.role
		if role == controlTypes.ROLE_DOCUMENT:
			from .documents import TableHandlerDocument
			clsList.insert(0, TableHandlerDocument)
	
	def terminate(self):
		terminate()
	
	def script_toggleTableMode(self, gesture):
		from .documents import TABLE_MODE, DocumentFakeCell, reportPassThrough
		focus = api.getFocusObject()
		if isinstance(focus, DocumentFakeCell):
			ti = focus.table.ti
			if ti.passThrough == TABLE_MODE:
				ti.passThrough = False
				reportPassThrough(ti)
				return
		info = api.getReviewPosition()
		table = getTableManager(info=info, setPosition=True, force=False)
		if not table:
			# Use translation from NVDA core
			ui.message(translate("Not in a table cell"))
			return
		#ti = table.treeInterceptor
		ti = table.ti
		ti._currentTable = table
		ti.passThrough = TABLE_MODE
		reportPassThrough(ti)
			
	
	script_toggleTableMode.ignoreTreeInterceptorPassThrough = True
	# Translators: The description of a command.
	script_toggleTableMode.__doc__ = "Toggle table mode."
	
	__gestures = {
		"kb:nvda+control+shift+space": "toggleTableMode"
	}


_handlers = ["Table handler not initialized"]


def initialize():
# 	global _handlers
# 	from .documents import DocumentTableHandler
# 	_handlers[:] = [DocumentTableHandler()]
	_handlers[:] = []


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
	
	def __init__(
		self,
		key,
		defaultColumnWidth=10,
		columnWidths=None,
		columnHeaderRowNumber=None,
		rowHeaderColumnNumber=None
	):
		self.key = key
		self.defaultColumnWidth = defaultColumnWidth
		if columnWidths is not None:
			self.columnWidths = columnWidths
		else:
			self.columnWidths = {}
		self.columnHeaderRowNumber = columnHeaderRowNumber
		self.rowHeaderColumnNumber = rowHeaderColumnNumber
	
	def getColumnWidth(self, rowNumber, columnNumber):
		columnWidths = self.columnWidths
		try:
			if isinstance(columnWidths, (list, tuple)):
				return columnWidths[columnNumber - 1]
			else:
				return columnWidths[columnNumber]
		except (AttributeError, LookupError):
			pass
		return self.defaultColumnWidth


class TableHandler(object):

	def getTableManager(self, **kwargs):
		raise NotImplementedError
	
	def getTableConfig(self, key="default", **kwargs):
		return TableConfig(key)
	
	def getTableConfigKey(self, **kwargs):
		return "default"
