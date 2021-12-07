# globalPlugins/tableHandler/webModule.py
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

"""Early-Access WebAccess Table Mode integration
"""

# Keep compatible with Python 2
from __future__ import absolute_import, division, print_function

__version__ = "2021.12.07"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

import weakref

import addonHandler
from logHandler import log
from treeInterceptorHandler import TreeInterceptor

from globalPlugins.webAccess.ruleHandler import Result, Rule
from globalPlugins.webAccess.webModuleHandler import WebModule
from globalPlugins.withSpeechMuted import speechMuted

from . import TableConfig, getTableConfig, getTableConfigKey, getTableManager
from .coreUtils import Break
from .documents import DocumentTableHandler, DocumentTableManager, TableHandlerTreeInterceptorScriptWrapper
from .scriptUtils import overrides


addonHandler.initTranslation()


class TableHandlerWebModuleScriptWrapper(TableHandlerTreeInterceptorScriptWrapper):
	
	def __init__(self, ti, script, **defaults):
		super(TableHandlerWebModuleScriptWrapper, self).__init__(ti, script, **defaults)
		self.arg = "script_"
	
	def override(self, gesture, *args, script_=None, **kwargs):
		# The base class uses the default "script" arg, but it conflicts with WebAccess' actions which also
		# receive a "script" arg.
		script = lambda *args_, **kwargs_: script_(gesture, *args, **kwargs)
		super(TableHandlerWebModuleScriptWrapper, self).override(gesture, script=script)


class TableHandlerWebModule(WebModule, DocumentTableHandler):
	
	def __init__(self):
		super(TableHandlerWebModule, self).__init__()
		self.tableConfigs = weakref.WeakValueDictionary()
		self.tableIDs = weakref.WeakValueDictionary()
	
	def __getattribute__(self, name):
		value = super(TableHandlerWebModule, self).__getattribute__(name)
		if (name.startswith("script_") or name.startswith("action_")) and not isinstance(
			value, TableHandlerTreeInterceptorScriptWrapper
		):
			ti = self.ruleManager.nodeManager.treeInterceptor
			return TableHandlerWebModuleScriptWrapper(ti, value)
		return value
	
	def createRule(self, data):
		if data.get("name") in self.tableConfigs:
			return TableHandlerRule(self.ruleManager, data)
		return super(TableHandlerWebModule, self).createRule(data)
	
	def getTableConfig(self, nextHandler=None, **kwargs):
		tableCfg = nextHandler(**kwargs)
		tableConfigKey = kwargs["tableConfigKey"]
		wmKeyPart = tableConfigKey.get("webModule") if isinstance(tableConfigKey, dict) else None
		data = None
		defaults = None
		if not tableCfg and wmKeyPart:
			templateKey = tableConfigKey.copy()
			templateKey.pop("webModule")
			if not templateKey:
				templateKey = "default"
			templateKwargs = kwargs.copy()
			tamplateKwargs["tableConfigKey"] = templateKey
			templateCfg = getTableConfig(**templateKwargs)
			if templateCfg:
				data = templateCfg.data
				defaults = templateCfg.defaults
		ruleDefaults = None
		if wmKeyPart:
			name = wmKeyPart.get("name")
			if not name or name == self.name:
				rule = wmKeyPart.get("rule")
				if rule:
					ruleDefaults = self.tableConfigs.get(rule)
					if defaults is not None:
						defaults.update(ruleDefaults)
		if (
			(not tableCfg and (data is not None or defaults is not None))
			or (tableCfg and tableCfg.key != tableConfigKey)
		):
			tableCfg = TableConfig(tableConfigKey, data=data, defaults=defaults)
		elif tableCfg and ruleDefaults is not None:
			tableCfg.defaults.update(ruleDefaults)
		return tableCfg
	
	def getTableConfigKey(self, nextHandler=None, **kwargs):
		key = nextHandler(**kwargs)
		if not isinstance(key, dict):
			assert key == "default"
			key = {}
		key["webModule"] = webModule = { "name": self.name }
		result = kwargs.get("result")
		if result:
			webModule["rule"] = result.rule.name
		#log.info(f"getTableConfigKey: {key!r}")
		return key
	
	def getTableManager(self, nextHandler=None, **kwargs):
		if kwargs.get("debug"):
			log.info(f"WM.getTableManager({kwargs})")
		ti = kwargs.get("ti")
		if not ti:
			if not self.ruleManager.isReady:
				return nextHandler(**kwargs)
			kwargs["ti"] = ti = self.ruleManager.nodeManager.treeInterceptor
		info = kwargs.get("info")
		result = kwargs.get("result")
		if not result:
			tableCellCoords = kwargs.get("tableCellCoords")
			try:
				if not tableCellCoords:
					if not info:
						kwargs["info"] = info = ti.selection
					try:
						tableCellCoords = ti._getTableCellCoordsIncludingLayoutTables(info)
					except LookupError:
						if kwargs.get("debug"):
							log.exception()
						raise Break
				kwargs["tableCellCoords"] = tableCellCoords
				tableID, isLayout, rowNum, colNum, rowSpan, colSpan = tableCellCoords
				result = self.tableIDs.get(tableID)
				if result:
					kwargs["result"] = result
			except Break:
				pass
		if not result:
			for result in self.ruleManager.iterResultsAtTextInfo(info):
				if result.name in self.tableConfigs:
					kwargs["result"] = result
					break
			else:
				result = None
		if result:
			cls = kwargs.get("tableClass")
			if not cls:
				cls = getattr(result, "TableClass", None)
			if not cls:
				cls = getattr(result.rule, "TableClass", None)
			if not cls:
				cls = getattr(self, "TableClass", None)
			if cls:
				kwargs["tableClass"] = cls
		if not kwargs.get("tableConfig"):
			if not kwargs.get("tableConfigKey"):
				kwargs["tableConfigKey"]  = tableConfigKey = getTableConfigKey(**kwargs)
			tableConfig = getTableConfig(**kwargs)
		res = nextHandler(**kwargs)
		return res


class RuleTable(DocumentTableManager):
	
	def _get_rowCount(self):
		webModule = self.ti.webAccess.webModule
		if hasattr(webModule, "getTableRowCount"):
			result = webModule.tableIDs.get(self.tableID)
			return webModule.getTableRowCount(
				self,
				nextHandler=lambda: super(RuleTable, self).rowCount,
				result=result
			)
		return super(RuleTable, self).rowCount


class TableHandlerRule(Rule):
	
	TableClass = RuleTable
	
	def createResult(self, node, context, index):
		result = TableHandlerResult(self, node, context, index)
		try:
			info = result.getTextInfo()
			#table = getTableManager(info=info, debug=True)
			table = getTableManager(info=info)
			if table:
				self.ruleManager.webModule.tableIDs[table.tableID] = result
				table.__dict__.setdefault("_trackingInfo", []).append("createResult")
			else:
				log.warning("No table found for result {!r} at {!r}".format(result.name, info.bookmark))
		except Exception:
			log.exception()
		return result


class TableHandlerResult(Result):
	
	def __getattribute__(self, name):
		value = super(TableHandlerResult, self).__getattribute__(name)
		if name.startswith("script_") and not isinstance(
			value, TableHandlerTreeInterceptorScriptWrapper
		):
			ti = self.rule.ruleManager.nodeManager.treeInterceptor
			return TableHandlerWebModuleScriptWrapper(ti, value)
		return value
	
	@overrides(Result.script_moveto)
	def script_moveto(self, gesture, **kwargs):
		with speechMuted():
			super(TableHandlerResult, self).script_moveto(gesture, **kwargs)
	
	script_moveto.enableTableModeAfter = True
