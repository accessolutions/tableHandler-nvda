# globalPlugins/tableHandler/webModule.py
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

"""Early-Access WebAccess Table Mode integration
"""

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


from collections.abc import Mapping
from functools import partial
from typing import Any
import weakref

from NVDAObjects import NVDAObject
import addonHandler
import api
from logHandler import log

from globalPlugins.webAccess.ruleHandler import Rule, SingleNodeResult
from globalPlugins.webAccess.webModuleHandler import WebModule
from globalPlugins.withSpeechMuted import speechMuted

from . import TableConfig, getTableConfig, getTableConfigKey, getTableManager
from .documents import (
	DocumentFakeCell,
	DocumentFakeRow,
	DocumentTableHandler,
	TableHandlerBmdtiScriptWrapper,
	VirtualBufferTableManager,
)
from .scriptUtils import overrides


addonHandler.initTranslation()


class TableHandlerWebModuleScriptWrapper(TableHandlerBmdtiScriptWrapper):
	
	def __init__(self, ti, script, **defaults):
		# The base class uses the default "script" arg, but it conflicts with WebAccess' actions which also
		# receives a "script" arg.
		super().__init__(ti, script, arg="script_", **defaults)


class TableHandlerWebModule(WebModule, DocumentTableHandler):
	
	# Maps Rule name to TableConfig data
	tableConfigs: Mapping[str, Mapping[str, Any]] = {}
	
	def __init__(self):
		super().__init__()
		self.tableIDs = weakref.WeakValueDictionary()
	
	def __getattribute__(self, name):
		value = super().__getattribute__(name)
		if (name.startswith("script_") or name.startswith("action_")) and not isinstance(
			value, TableHandlerBmdtiScriptWrapper
		):
			ti = self.ruleManager.nodeManager.treeInterceptor
			return TableHandlerWebModuleScriptWrapper(ti, value)
		return value
	
	def createRule(self, data):
		if data.get("name") in self.tableConfigs:
			return TableHandlerRule(self.ruleManager, data)
			rule.__class__ = getDynamicClass(
				(TableHandlerRuleMixin,) + rule.__class__.__mro__
			)
		return super().createRule(data)
	
	def getTableConfig(self, nextHandler=None, **kwargs):
		if kwargs.get("debug"):
			log.info(f">>> THWM.getTableConfig({kwargs})")
		
		key = kwargs.get("key")
		if key is None:
			key = kwargs["key"] = getTableConfigKey(**kwargs)
		
		cfg = nextHandler(**kwargs)
		
		if isinstance(key, Mapping) and "webModule" in key:
			wmDefaults = self.tableConfigs.get("")
			if wmDefaults:
				cfg.map.maps.insert(1, wmDefaults)
			ruleName = key["webModule"].get("rule")
			if ruleName:
				ruleDefaults = self.tableConfigs.get(ruleName)
				if ruleDefaults:
					cfg.map.maps.insert(1, ruleDefaults)
		
		if kwargs.get("debug"):
			log.info(f"<<< THWM.getTableConfig: {cfg}")
		return cfg
	
	def getTableConfigKey(self, nextHandler=None, **kwargs):
		if kwargs.get("debug"):
			log.info(f">>> THWM.getTableConfigKey({kwargs})")
		
		result = kwargs.get("result")
		if result:
			key = {"webModule": {"rule": result.rule.name}}
		else:
			key = nextHandler(**kwargs)
			if kwargs.get("debug"):
				log.info(f"THWM.getTableConfigKey - Retrieved from next handler: {key}")
			if not isinstance(key, Mapping):
				try:
					assert key in (None, "")
				except AssertionError:
					log.exception(f"key: {key}")
				key = {}
		key.setdefault("webModule", {})["name"] = self.name
		
		if kwargs.get("debug"):
			log.info(f"<<< THWM.getTableConfigKey: {key!r}")
		return key
	
	def getTableManager(self, nextHandler=None, **kwargs):
		if kwargs.get("debug"):
			log.info(f">>> THWM.getTableManager({kwargs})")
		
		if not self.ruleManager.isReady:
			if kwargs.get("debug"):
				log.info("THWM.getTableManager: not ready")
			return nextHandler(**kwargs)
		ti = kwargs.get("ti")
		if ti is None:
			ti = kwargs["ti"] = self.ruleManager.nodeManager.treeInterceptor
		info = kwargs.get("info")
		if info is None:
			info = kwargs["info"] = ti.selection
		result = kwargs.get("result")
		if result is None:
			for result in self.ruleManager.iterResultsAtTextInfo(info):
				if isinstance(result, TableHandlerResult):
					if kwargs.get("debug"):
						log.info(f"THWM.getTableManager: Result at position: {result}")
					break
			else:
				if kwargs.get("debug"):
					log.info("THWM.getTableManager: No result at position")
				result = None
		if result is not None:
			if kwargs.get("result") is None:
				kwargs["result"] = result
				if (
					"getTableManager" in self.__dict__
					or next(
						base for base in self.__class__.__mro__
						if "getTableManager" in base.__dict__
					) is not self.__class__
				):
					# This method is overridden
					if kwargs.get("debug"):
						log.info(f"THWM.getTableManager: Re-launch with result")
					res = self.getTableManager(nextHandler=nextHandler, **kwargs)
					if kwargs.get("debug"):
						log.info(f"<<< THWM.getTableManager: {res}")
					return res
			cls = kwargs.get("tableManagerClass")
			if cls is None:
				cls = self.getTableManagerClass(result)
				kwargs["tableManagerClass"] = cls
		if kwargs.get("cfg") is None:
			kwargs["cfg"] = getTableConfig(**kwargs)
		res = nextHandler(**kwargs)
		if result is not None and isinstance(res, WebModuleTableManager):
			res.result = result
		if kwargs.get("debug"):
			log.info(f"<<< THWM.getTableManager: {res} / {res!r}")
		return res
	
	def getTableManagerClass(self, result) -> type["TableManager"]:
		# Need to be keyword arguments here because
		# NVDAObject.__call__ passes only these to __init__.
		return partial(WebModuleTableManager, webModule=self, result=result)
	
	def getRowClass(self, result) -> type["Row"]:
		return WebModuleFakeRow
	
	def getCellClass(self, result) -> type["Cell"]:
		return WebModuleFakeCell
	
	def getRowCount(self, result, nextHandler):
		return nextHandler()
	
	def getColumnCount(self, result, nextHandler):
		return nextHandler()
	
	def getRowHeaderText(self, result, rowNumber, nextHandler):
		return nextHandler()
	
	def getColumnHeaderText(self, result, columnNumber, nextHandler):
		return nextHandler()
	
	def getCellStates(self, result, rowNumber, columnNumber, nextHandler):
		return nextHandler()
	
	def makeCellTextInfo(self, obj, position, result, rowNumber, columnNumber, nextHandler):
		return nextHandler()


class TableHandlerRule(Rule):
	
	def createResult(self, criteria, node, context, index):
		return TableHandlerResult(criteria, node, context, index)


class TableHandlerResult(SingleNodeResult):
	
	def __getattribute__(self, name):
		value = super().__getattribute__(name)
		if name.startswith("script_") and not isinstance(
			value, TableHandlerBmdtiScriptWrapper
		):
			ti = self.rule.ruleManager.nodeManager.treeInterceptor
			return TableHandlerWebModuleScriptWrapper(ti, value)
		return value
	
	@overrides(SingleNodeResult.script_moveto)
	def script_moveto(self, gesture, **kwargs):
		script = super().script_moveto
		from globalPlugins.webAccess.ruleHandler import CustomActionDispatcher
		if isinstance(script, CustomActionDispatcher):
			script = script.standardFunc.__get__(self)
		with speechMuted():
			script(gesture, **kwargs)
	
	script_moveto.enableTableModeAfter = True



class WebModuleTableManager(VirtualBufferTableManager):
	
	def __init__(self, webModule, result, *args, **kwargs):
		self.webModule = webModule
		self.result = result
		super().__init__(*args, **kwargs)
	
	def _get_RowClass(self):
		return self.webModule.getRowClass(self.result)
	
	def _get_webModule(self):
		webModule = self._webModule()
		if webModule is None:
			if self in api.getFocusAncestors():
				obj = NVDAObject.objectWithFocus()
				if obj is not None:
					api.setFocusObject(obj)
			raise Exception("This table's webModule instance no longer exists")
		return webModule
	
	def _set_webModule(self, webModule):
		self._webModule = weakref.ref(webModule)
	
	def _get_result(self):
		result = self._result()
		if result is None:
			try:
				result = self.webModule.ruleManager.getRule(
					self._ruleName, layer=self._ruleLayer
				).getResults()[self._resultIndex - 1]  # Result index is 1-based
			except Exception as e:
				if self in api.getFocusAncestors():
					obj = NVDAObject.objectWithFocus()
					if obj is not None:
						api.setFocusObject(obj)
				raise Exception("This table's result no longer exists") from e
			self._result = weakref.ref(result)
		return result
	
	def _set_result(self, result):
		rule = result.rule
		self._ruleName = rule.name
		self._ruleLayer = rule.layer
		self._resultIndex = result.index
		self._result = weakref.ref(result)
	
	def _get_rowCount(self):
		return self.webModule.getRowCount(
			self.result,
			nextHandler=lambda: super(WebModuleTableManager, self).rowCount
		)
	
	def _get_columnCount(self):
		return self.webModule.getColumnCount(
			self.result,
			nextHandler=lambda: super(WebModuleTableManager, self).columnCount
		)


class WebModuleFakeRow(DocumentFakeRow):
	
	@property
	def CellClass(self):
		return self.table.webModule.getCellClass(self.table.result)


class WebModuleFakeCell(DocumentFakeCell):
	
	def _get_states(self):
		return self.table.webModule.getCellStates(
			self.table.result,
			self.rowNumber,
			self.columnNumber,
			nextHandler=lambda: super(WebModuleFakeCell, self)._get_states()
		)
	
	def getColumnHeaderText(self):
		return self.table.webModule.getColumnHeaderText(
			self.table.result,
			self.columnNumber,
			nextHandler=lambda: super(WebModuleFakeCell, self).getColumnHeaderText()
		)

	def getRowHeaderText(self):
		return self.table.webModule.getRowHeaderText(
			self.table.result,
			self.rowNumber,
			nextHandler=lambda: super(WebModuleFakeCell, self).getRowHeaderText()
		)
	
	def makeTextInfo(self, position):
		return self.table.webModule.makeCellTextInfo(
			self,
			position,
			self.table.result,
			self.rowNumber,
			self.columnNumber,
			nextHandler=lambda: super(WebModuleFakeCell, self).makeTextInfo(position)
		)
