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

# Get ready for Python 3
from __future__ import absolute_import, division, print_function

__version__ = "2021.09.30"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

import weakref

import addonHandler
import api
from logHandler import log
import queueHandler
from treeInterceptorHandler import TreeInterceptor

from globalPlugins.webAccess.ruleHandler import Result, Rule
from globalPlugins.webAccess.webModuleHandler import WebModule
from globalPlugins.withSpeechMuted import speechMuted

from . import TableConfig, registerTableHandler
from .coreUtils import catchAll
from .fakeObjects import FakeObject
from .documents import DocumentTableHandler, TableHandlerTreeInterceptorScriptWrapper


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
		registerTableHandler(weakref.ref(self))
	
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
	
	def getTableConfig(self, ti=None, tableConfigKey=None, **kwargs):
		defaults = None
		if tableConfigKey and tableConfigKey.get("WebModule") == self.name:
			rule = tableConfigKey.get("rule")
			if rule:
				defaults = self.tableConfigs.get(rule)
		tableCfg = super(TableHandlerWebModule, self).getTableConfig(
			ti=None, tableConfigKey=tableConfigKey, **kwargs)
		if not tableCfg:
			if defaults:
				tableCfg = TableConfig(key=tableConfigKey)
		if not tableCfg:
			return None
		if tableConfigKey:
			if tableConfigKey != tableCfg.key:
				# TODO: Copy config instead of re-keying
				tableCfg.key = tableConfigKey
		if defaults:
			tableCfg.defaults = defaults
		return tableCfg
	
	def getTableConfigKey(self, ti=None, result=None, **kwargs):
		key = ti.getTableConfigKey(result=result, **kwargs)
		if not isinstance(key, dict):
			assert key == "default"
			key = {}
		key["handler"] = "WebAccess"
		key["webModule"] = self.name
		if result:
			key["rule"] = result.rule.name
		return key
	
	def getTableManager(
		self,
		info=None,
		result=None,
		tableConfigKey=None,
		tableConfig=None,
		**kwargs
	):
		ti = self.ruleManager.nodeManager.treeInterceptor
		try:
			if info.obj.webAccess.webModule is not self:
				return None
		except AttributeError:
			return None
		if not result:
			for result in self.ruleManager.iterResultsAtTextInfo(info):
				if result.name in self.tableConfigs:
					break
			else:
				result=None
		if not tableConfig:
			if not tableConfigKey:
				tableConfigKey = self.getTableConfigKey(
					ti=ti, info=info, result=result, **kwargs
				)
			tableConfig = self.getTableConfig(
				ti=ti,
				info=info,
				result=result,
				tableConfigKey=tableConfigKey,
				**kwargs
			)
		return ti.getTableManager(
			info=info,
			result=result,
			tableConfigKey=tableConfigKey,
			tableConfig=tableConfig,
			**kwargs
		)


class TableHandlerRule(Rule):
	
	def createResult(self, node, context, index):
		return TableHandlerResult(self, node, context, index)


class TableHandlerResult(Result):
	
	def __getattribute__(self, name):
		value = super(TableHandlerResult, self).__getattribute__(name)
		if name.startswith("script_") and not isinstance(
			value, TableHandlerTreeInterceptorScriptWrapper
		):
			ti = self.rule.ruleManager.nodeManager.treeInterceptor
			return TableHandlerWebModuleScriptWrapper(ti, value)
		return value
	
	def script_moveto(self, gesture, **kwargs):
		with speechMuted():
			super(TableHandlerResult, self).script_moveto(gesture, **kwargs)
	
	script_moveto.__dict__.update(Result.script_moveto.__dict__)
	script_moveto.enableTableModeAfter = True
