# globalPlugins/tableHandler/__init__.py
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

"""Table Handler Global Plugin
"""

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


from functools import partial
import json
import os.path
import threading
import weakref

import addonHandler
import api
import braille
import controlTypes
from garbageHandler import TrackedObject
import globalPluginHandler
import globalVars
from logHandler import log
from treeInterceptorHandler import TreeInterceptor
import ui

from .lib import synchronized
from .coreUtils import Break, translate


addonHandler.initTranslation()


SCRIPT_CATEGORY = "TableHandler"


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	
	def __init__(self):
		super().__init__()
		initialize()
	
	def chooseNVDAObjectOverlayClasses(self, obj, clsList):  # TODO
		role = obj.role
		if role == controlTypes.ROLE_DOCUMENT:
			from .documents import TableHandlerDocument
			clsList.insert(0, TableHandlerDocument)
	
	def terminate(self):
		terminate()
	
	def event_gainFocus(self, obj, nextHandler):
		#log.info(f"event_gainFocus({obj!r}({id(obj)}))")
		from .documents import DocumentFakeCell
		focus = api.getFocusObject()
		if isinstance(focus, DocumentFakeCell):
			oldTi = focus.ti
			if isinstance(obj, DocumentFakeCell):
				if focus.ti is obj.ti:
					nextHandler()
					return
			if focus.ti.passThrough == TABLE_MODE:
				if obj.treeInterceptor is focus.ti:
					log.info(f"GP.event_gainFocus({obj!r}) - same TI but not cell")
				else:
					log.info(f"GP.event_gainFocus({obj!r}) - other TI")
		nextHandler()
	
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


def initialize():
	from .config import initialize as config_initialize
	config_initialize()
	from .gui.settings import initialize as settings_initialize
	settings_initialize()
	
	def loadCatalog():
		TableConfig.catalog
	
	thread = TableConfig._catalogLoadingThread = threading.Thread(target=loadCatalog)
	thread.daemon = True
	thread.start()


def terminate():
	from .config import initialize as config_terminate
	config_terminate()
	from .gui.settings import terminate as settings_terminate
	settings_terminate()
	
	TableConfig._cache.clear()
	TableConfig._catalog = None



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
		self = super().__new__(cls)
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


class TableConfig:
	
	DEFAULTS = {
		"defaultColumnWidthByDisplaySize": {0: 10},
		"columnWidthsByDisplaySize" : {},
		"rowHeaderColumnNumber": None,
		"columnHeaderRowNumber": None,
		"customRowHeaders": {},
		"customColumnHeaders": {},
		"markedColumnNumbers": {},
		"markedRowNumbers": {},
		"firstDataRowNumber": None,
		"firstDataColumnNumber": None
	}
	
	FILE_PATH = os.path.join(globalVars.appArgs.configPath, "tableHandler.json")
	
	_cache = weakref.WeakValueDictionary()
	_catalog = None
	_catalogLoadingThread = None
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def catalog(cls):
		cls._catalogLoadingThread.join()
		catalog = cls._catalog
		if catalog is not None:
			return catalog
		catalog = cls._catalog = [item["key"] for item in cls.read() or []]
		return catalog
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def get(cls, key, defaults=None):
		if key not in cls.catalog():
			raise LookupError(key)
		strKey = str(key)
		cfg = cls._cache.get(strKey)
		if cfg and cfg.key == key:
			return cfg
		cfg = cls._cache[strKey] = cls.load(key, defaults=defaults)
		return cfg
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def load(cls, key, defaults=None):
		for item in cls.read() or []:
			if item["key"] == key:
				if defaults is None:
					defaults = cls.DEFAULTS
				return cls(key=key, data=item["config"], defaults=defaults)
		raise LookupError(key)
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def read(cls):
		try:
			with open(cls.FILE_PATH, "r") as f:
				return json.load(f)
		except FileNotFoundError:
			return None
	
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
	
	def __init__(
		self,
		key,
		data=None,
		defaults=None,
	):
		self.key = key
		if data is not None:
			self.data = data
			# JSON only supports strings for mappings keys
			intKeyedDict = lambda map: {int(key): value for key, value in map.items()}
			for key in (
				"customColumnHeaders",
				"customRowHeaders",
				"defaultColumnWidthByDisplaySize",
				"markedColumnNumbers",
				"markedRowNumbers"
			):
				if key in data:
					data[key] = {int(key): value for key, value in data[key].items()}
			if "columnWidthsByDisplaySize" in data:
				data["columnWidthsByDisplaySize"] = {int(size): {
					int(colNum): width for colNum, width in widths.items()
				} for size, widths in data["columnWidthsByDisplaySize"].items()}
		else:
			data = self.data = {}
		if defaults is not None:
			self.defaults = defaults
		else:
			self.defaults = self.DEFAULTS
		
		self.defaultColumnWidthByDisplaySize = self["defaultColumnWidthByDisplaySize"].copy()
	
	def __contains__(self, item):
		return item in self.data or item in self.defaults
	
	def __getitem__(self, name, default=None):
		try:
			return self.data[name]
		except KeyError:
			try:
				value = self.defaults[name]
			except KeyError:
				return default
			# Copy containers to avoid accidentally impacting the defaults.
			# We might need a real deep-copy here in the future.
			if isinstance(value, dict):
				value = value.copy()
			elif isinstance(value, list):
				value = value[:]
			return value
	
	def __setitem__(self, name, value):
		self.data[name] = value
		self.save()
	
	def getColumnWidth(self, columnNumber):
		size = braille.handler.displaySize
		columnWidth = self["columnWidthsByDisplaySize"].get(size, {}).get(columnNumber)
		if columnWidth is not None:
			return columnWidth
		defaultSizes = self.defaultColumnWidthByDisplaySize
		defaultWidth = defaultSizes.get(size)
		if defaultWidth is not None:
			return defaultWidth
		# First encounter of this display size:
		# Initialize the cache for faster retrieval next time.
		defaultSizes[size] = defaultWidth = min((
			(abs(size - candidateSize), candidateWidth)
			for candidateSize, candidateWidth in defaultSizes.items()
		), key=lambda item: item[0])[1]
		return defaultWidth
	
	def setColumnWidth(self, columnNumber, width):
		if width < 0:
			return
		size = braille.handler.displaySize
		width = min(width, size)
		sizes = self["columnWidthsByDisplaySize"]
		sizes.setdefault(size, {})[columnNumber] = width
		self["columnWidthsByDisplaySize"] = sizes
		return width
	
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def save(self):
		configs = self.read() or []
		data = self.data.copy()
		key = self.key
		for item in configs:
			if item["key"] == key:
				item["config"] = data
				break
		else:
			configs.append({"key": key, "config": data})
			if self._catalog is not None:
				self._catalog.append(key)
		with open(self.FILE_PATH, "w") as f:
			json.dump(configs, f, indent=4)


class TableHandler:

	def getTableManager(self, **kwargs):
		raise NotImplementedError
	
	def getTableConfig(self, tableConfigKey="default", **kwargs):
		try:
			return TableConfig.get(tableConfigKey)
		except LookupError:
			return TableConfig(tableConfigKey)
	
	def getTableConfigKey(self, **kwargs):
		return "default"
