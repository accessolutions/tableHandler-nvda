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

# Keep compatible with Python 2
from __future__ import absolute_import, division, print_function

__version__ = "2021.10.20"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

from functools import partial
import os.path
import weakref

import addonHandler
import api
import controlTypes
import errno
import globalPluginHandler
import globalVars
from logHandler import log
from treeInterceptorHandler import TreeInterceptor
import ui

from .lib import synchronized
from .coreUtils import Break, translate

try:
	import json
except ImportError:
	# NVDA version < 2017.3
	from .lib import json

try:
	from garbageHandler import TrackedObject
except ImportError:
	# NVDA version < 2020.3
	TrackedObject = object


addonHandler.initTranslation()


SCRIPT_CATEGORY = "TableHandler"


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	
	def chooseNVDAObjectOverlayClasses(self, obj, clsList):  # TODO
		role = obj.role
		if role == controlTypes.ROLE_DOCUMENT:
			from .documents import TableHandlerDocument
			clsList.insert(0, TableHandlerDocument)
	
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


def getTableConfig(**kwargs):
	if kwargs.get("debug"):
		log.info(f">>> getTableConfig({kwargs})")
	res = TableHandlerDispatcher("getTableConfig", None, **kwargs)
	if kwargs.get("debug"):
		log.info(f"<<< getTableConfig: {(res.key if res else None)!r}")
	return res


def getTableConfigKey(**kwargs):
	if kwargs.get("debug"):
		log.info(f">>> getTableConfigKey({kwargs})")
	res = TableHandlerDispatcher("getTableConfigKey", None, **kwargs)
	if kwargs.get("debug"):
		log.info(f"<<< getTableConfigKey: {res!r}")
	return res


def getTableManager(**kwargs):
	if kwargs.get("debug"):
		log.info(f">>> getTableManager({kwargs})")
	res = TableHandlerDispatcher("getTableManager", None, **kwargs)
	if kwargs.get("debug"):
		log.info(f"<<< getTableManager: {(res._tableConfig.key if res else None)!r}")
	return res


class TableHandlerDispatcher(TrackedObject):
	
	def __new__(cls, funcName, default, **kwargs):
		self = super(cls, cls).__new__(cls)
		self._gen = self.gen(funcName, **kwargs)
		try:
			return self.next(default, **kwargs)
		finally:
			del self._gen
		
	def gen(self, funcName, **kwargs):
		for plugin in globalPluginHandler.runningPlugins:
			func = getattr(plugin, funcName, None)
			if func:
				yield func
		obj = kwargs.get("obj")
		ti = kwargs.get("ti")
		if not obj:
			info = kwargs.get("info")
			if info:
				obj = info.obj
				if isinstance(obj, TreeInterceptor):
					if not ti:
						ti = obj
					obj = obj.rootNVDAObject
		if not obj:
			obj = api.getFocusObject()
		if obj:
			appModule = obj.appModule
			func = getattr(appModule, funcName, None)
			if func:
				yield func
		if not ti:
			from .documents import DocumentFakeObject
			if isinstance(obj, DocumentFakeObject):
				ti = obj.ti
			else:
				ti = obj.treeInterceptor
		if ti:
			webAccess = getattr(ti, "webAccess", None)
			if webAccess:
				webModule = webAccess.webModule
				if webModule:
					func = getattr(webModule, funcName, None)
					if func:
						yield func
			func = getattr(ti, funcName, None)
			if func:
				yield func
		func = getattr(obj, funcName, None)
		if func:
			yield func
	
	def next(self, default, **kwargs):
		func = next(self._gen, None)
		if not func:
			return default
		return func(**kwargs, nextHandler=partial(self.next, default))


class TableConfig(object):
	
	DEFAULTS = {
		"defaultColumnWidth" : 10,
		"columnWidths" : {},
		"columnHeaderRowNumber": None,
		"rowHeaderColumnNumber": None
	}
	
	FILE_PATH = os.path.join(globalVars.appArgs.configPath, "tableHandler.json")
	
	_catalog = None
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def catalog(cls):
		catalog = cls._catalog
		if catalog is not None:
			return catalog
		catalog = cls._catalog = [item["key"] for item in cls.read() or []]
		return catalog
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def remove(cls, key):
		configs = cls.read() or []
		for index, item in enumerate(configs):
			if item["key"] == key:
				del configs[index]
				cls._catalog.remove(key)
				break
		else:
			raise LookupError(key)
		with open(self.FILE_PATH, "w") as f:
			json.dump(configs, f, indent=4)
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def load(cls, key):
		for item in cls.read() or []:
			if item["key"] == key:
				return cls(key=key, data=item["config"])
		raise LookupError(key)
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def read(cls):
		try:
			with open(cls.FILE_PATH, "r") as f:
				return json.load(f)
		except EnvironmentError as e:
			if e.errno != errno.ENOENT:
				raise
	
	def __init__(
		self,
		key,
		data=None,
		defaults=None,
	):
		self.key = key
		if data is not None:
			self.data = data
		else:
			data = self.data = {}
		if defaults is not None:
			self.defaults = defaults
		else:
			self.defaults = self.DEFAULTS
	
	def __contains__(self, item):
		return item in self.data or item in self.defaults
	
	def __getitem__(self, name, default=None):
		return self.data.get(name, self.defaults.get(name, default))
	
	def __setitem__(self, name, value):
		self.data[name] = value
		self.save()
	
	def getColumnWidth(self, rowNumber, columnNumber):
		columnWidths = self["columnWidths"]
		try:
			if isinstance(columnWidths, (list, tuple)):
				return columnWidths[columnNumber - 1]
			elif isinstance(columnWidths, dict):
				return columnWidths[columnNumber]
			elif columnWidths:
				raise ValueError("Unexpected columnWidths={!r}".format(columnWidths))
		except LookupError:
			pass
		return self["defaultColumnWidth"]
	
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def save(self):
		configs = self.read() or []
		key = self.key
		for item in configs:
			if item["key"] == key:
				item["config"] = self.data
				break
		else:
			configs.append({"key": key, "config": self.data})
			if self._catalog is not None:
				self._catalog.append(key)
		with open(self.FILE_PATH, "w") as f:
			json.dump(configs, f, indent=4)


class TableHandler(object):

	def getTableManager(self, **kwargs):
		raise NotImplementedError
	
	def getTableConfig(self, tableConfigKey="default", **kwargs):
		try:
			return TableConfig.load(tableConfigKey)
		except LookupError:
			return TableConfig(tableConfigKey)
	
	def getTableConfigKey(self, **kwargs):
		return "default"
