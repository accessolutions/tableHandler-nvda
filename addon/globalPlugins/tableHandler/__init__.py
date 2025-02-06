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
import sys
import threading
from typing import Any, Callable
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
from .lib.nestedChainMap import NestedChainMap
from .coreUtils import translate


if sys.version_info[1] < 9:
    from typing import Mapping, Sequence, Set
else:
    from collections.abc import Mapping, Sequence, Set


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
		#log.info("script_toggleTableMode")
		from .documents import TABLE_MODE, DocumentFakeCell, reportPassThrough
		focus = api.getFocusObject()
		if isinstance(focus, DocumentFakeCell):
			ti = focus.table.ti
			if ti.passThrough == TABLE_MODE:
				#log.info("script_toggleTableMode - cancelling table mode")
				ti.passThrough = False
				reportPassThrough(ti)
				return
		info = api.getReviewPosition()
		table = getTableManager(info=info, setPosition=True, force=False)
		if not table:
			#log.info("script_toggleTableMode - Not in a table cell")
			# Use translation from NVDA core
			ui.message(translate("Not in a table cell"))
			return
		ti = table.ti
		ti._currentTable = table
		#log.info("setting table mode")
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
	#kwargs.setdefault("debug", True)
	if kwargs.get("debug"):
		log.info(f">>> getTableConfig({kwargs})")
	res = TableHandlerDispatcher("getTableConfig", **kwargs)
	if kwargs.get("debug"):
		log.info(f"<<< getTableConfig: {res}")
	return res


def getTableConfigKey(**kwargs):
	#kwargs.setdefault("debug", True)
	if kwargs.get("debug"):
		log.info(f">>> getTableConfigKey({kwargs})")
	res = TableHandlerDispatcher("getTableConfigKey", **kwargs)
	if kwargs.get("debug"):
		log.info(f"<<< getTableConfigKey: {res!r}")
	return res


def getTableManager(**kwargs):
	#kwargs.setdefault("debug", True)
	if kwargs.get("debug"):
		log.info(f">>> getTableManager({kwargs})")
	res = TableHandlerDispatcher("getTableManager", **kwargs)
	if kwargs.get("debug"):
		log.info(f"<<< getTableManager: {res!r}")
	return res


def setDefaultTableKwargs(kwargs):
		info = kwargs.get("info")
		if info is None:
			info = kwargs["info"] = api.getReviewPosition()
		obj = kwargs.get("obj")
		if obj is None:
			if info is not None:
				candidate = info.obj
				if isinstance(candidate, TreeInterceptor):
					obj = kwargs["obj"] = candidate.rootNVDAObject
				else:
					obj = kwargs["obj"] = candidate
			else:
				obj = kwargs["obj"] = api.getFocusObject()
		ti = kwargs.get("ti")
		if ti is None:
			from .documents import DocumentFakeObject, TableHandlerBmdti
			if isinstance(obj, DocumentFakeObject):
				ti = kwargs["ti"] = obj.ti
			elif isinstance(info.obj, TableHandlerBmdti):
				ti = kwargs["ti"] = info.obj
			else:
				candidate = obj.treeInterceptor
				if isinstance(candidate, TableHandlerBmdti):
					ti = kwargs["ti"] = candidate
		


class TableHandlerDispatcher(TrackedObject):
	
	def __new__(cls, funcName, **kwargs):
		setDefaultTableKwargs(kwargs)
		self = super().__new__(cls)
		self._gen = self.gen(funcName, **kwargs)
		try:
			return self.next(**kwargs)
		finally:
			del self._gen
		
	def gen(self, funcName, **kwargs):
		for plugin in globalPluginHandler.runningPlugins:
			func = getattr(plugin, funcName, None)
			if func:
				yield func
		obj = kwargs["obj"]
		appModule = obj.appModule
		func = getattr(appModule, funcName, None)
		if func:
			yield func
		ti = kwargs.get("ti")
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
			else:
				log.info(f"TI has no {funcName} ({ti.__class__.__mro__})")
		func = getattr(obj, funcName, None)
		if func:
			yield func
		yield getattr(TableHandler(), funcName)
	
	def next(self, **kwargs):
		func = next(self._gen, None)
		if func is None:
			raise Exception("Handlers exausted")
		return func(**kwargs, nextHandler=self.next)


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
		"firstDataColumnNumber": None,
	}
	
	# JSON only supports strings for mappings keys.
	# Int keys are automatically changed to strings upon saving.
	INT_KEY_MAPPINGS = (
		"columnWidthsByDisplaySize",
		"customColumnHeaders",
		"customRowHeaders",
		"defaultColumnWidthByDisplaySize",
		"markedColumnNumbers",
		"markedRowNumbers",
	)
	
	FILE_PATH = os.path.join(globalVars.appArgs.configPath, "tableHandler.json")
	
	KeyType = Mapping|str
	DataType = Mapping[str, Any]
	if sys.version_info[1] >= 8:
		from typing import TypedDict
		DataFileEntryType = TypedDict("DataFileEntryType", {"key": KeyType, "config": DataType})
	else:
		DataFileEntryType = Mapping[str, KeyType|DataType]
	DataFileType = Sequence[DataFileEntryType]
	
	_cache: Mapping[KeyType, "TableConfig"] = weakref.WeakValueDictionary()
	_catalog: Sequence[KeyType] = None
	_catalogLoadingThread: threading.Thread = None
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def catalog(cls, refresh=False) -> Set[KeyType]:
		cls._catalogLoadingThread.join()
		if not refresh:
			catalog = cls._catalog
			if catalog is not None:
				return catalog
		catalog = cls._catalog = [item["key"] for item in cls.read() or []]
		return catalog
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def get(cls, key, createIfMissing=True):
		strKey = str(key)
		cfg = cls._cache.get(strKey)
		if cfg:
			return cfg
		missing = key not in cls.catalog()
		if missing:
			if not createIfMissing:
				raise LookupError(key)
			cfg = cls(key)
		else:
			cfg = cls.load(key)
		if key != "":
			cfg.map.maps.extend(cls.get("").map.maps)
		else:
			cfg.map.maps.append(cls.DEFAULTS)
		cls._cache[strKey] = cfg
		return cfg
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def load(cls, key) -> "TableConfig":
		for item in cls.read() or []:
			if item["key"] == key:
				return cls(key=key, data=item["config"])
		raise LookupError(key)
	
	@classmethod
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def read(cls) -> DataFileType:
		try:
			with open(cls.FILE_PATH, "r") as f:
				data: DataFileType = json.load(f)
		except FileNotFoundError:
			return None
		for item in data:
			item["config"] = cls.restoreIntKeys(item["config"])
		return data
	
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
	def restoreIntKeys(cls, data: Mapping[str, Any]) -> Mapping[str, Any]:
		"""Restore integer keys changed to strings when marshaled to JSON
		"""
		def restored(obj):
			if not isinstance(obj, Mapping):
				return obj
			return {int(k): restored(v) for k, v in obj.items()}
		
		for key in cls.INT_KEY_MAPPINGS:
			if key in data:
				data[key] = restored(data[key])
		return data
	
	def __init__(self, key, data=None):
		self.key = key
		self.map = NestedChainMap(data if data is not None else {})
	
	def __repr__(self):
		return f"<{type(self).__name__}: key={self.key}, data={self.map.maps}>"
	
	def __delitem__(self, key):
		del self.map[key]
	
	def __getitem__(self, key, default=None):
		return self.map.get(key, default=default)
	
	def __setitem__(self, name, value):
		self.map[name] = value
		self.save()
	
	def getColumnWidth(self, columnNumber):
		size = braille.handler.displaySize
		columnWidth = self["columnWidthsByDisplaySize"].get(size, {}).get(columnNumber)
		if columnWidth is not None:
			return columnWidth
		defaultWidth = self["defaultColumnWidthByDisplaySize"].get(size)
		if defaultWidth is not None:
			return defaultWidth
		defaultSizes = self.map.maps[-1]["defaultColumnWidthByDisplaySize"]
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
		sizes = self["columnWidthsByDisplaySize"].setdefault(size, {})[columnNumber] = width
		self.save()
		return width
	
	@synchronized.function(lockHolderGetter=lambda func, *args, **kwargs: TableConfig)
	def save(self):
		configs = self.read() or []
		key = self.key
		for item in configs:
			if item["key"] == key:
				item["config"] = self.map.maps[0]
				break
		else:
			configs.append({"key": key, "config": self.map.maps[0]})
			self._catalog.append(key)
		tmpPath = f"{self.FILE_PATH}.tmp"  # Avoid erasing the config file if something goes wrong
		try:
			with open(tmpPath, "w") as f:
				json.dump(configs, f, indent=4)
			os.replace(tmpPath, self.FILE_PATH)
		except Exception:
			log.exception()


class TableHandler:

	def getTableManager(self, **kwargs):
		#raise NotImplementedError
		return None
	
	def getTableConfig(self, key=None, createIfMissing=True, **kwargs):
		if key is None:
			kwargs.pop("nextHandler", None)
			key = getTableConfigKey(**kwargs)
		return TableConfig.get(key, createIfMissing=createIfMissing)
	
	def getTableConfigKey(self, **kwargs):
		return ""
