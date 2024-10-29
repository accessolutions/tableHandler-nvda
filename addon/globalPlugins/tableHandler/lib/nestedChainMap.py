# nestedChainMap.py
# -*- coding: utf-8 -*-

# This file is a Python utility module.
# Copyright (C) 2017-2024 Accessolutions (https://accessolutions.fr)
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

"""NestedChainMaP - A ChainMap that also chains its Mapping values

Run this bare module for basic testing.
"""

__version__ = "2024.10.04"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

from collections import ChainMap
from collections.abc import Mapping


class NestedChainMap(ChainMap):
	"""A ChainMap that also chains its Mapping values
	"""
	
	def __init__(self, *maps):
		super().__init__(*maps)
		self.containerLink = (None, None)
		self.virtual = False
	
	def __delitem__(self, key):
		self._fetchUpdateFromContainer()
		super().__delitem__(key)
	
	def __delitem__(self, key):
		self._fetchUpdateFromContainer()
		super().__delitem__(key)
	
	def __getitem__(self, key):
		self._fetchUpdateFromContainer()
		return self._nested(key, super().__getitem__(key))
	
	def __setitem__(self, key, value):
		self._fetchUpdateFromContainer()
		if isinstance(value, self.__class__):
			cnt, cntKey = value.containerLink
			if cnt is self and cntKey == key:
				value = value.maps[0]
		super().__setitem__(key, value)
		self._pushUpdateToContainer()
	
	def clear(self):
		self._fetchUpdateFromContainer()
		shouldPush = bool(self.maps[0])
		super().clear()
		if shouldPush:
			self._pushUpdateToContainer()
	
	def dump(self):
		"""Same as dict(self) for a regular ChainMap.
		"""		
		return {
			key: value.dump() if isinstance(value, NestedChainMap) else value
			for key, value in self.items()
		}
	
	def items(self):
		self._fetchUpdateFromContainer()
		for key, value in super().items():
			yield key, self._nested(key, value)
	
	def pop(self, *args):
		self._fetchUpdateFromContainer()
		super().pop(*args)
	
	def popitem(self):
		self._fetchUpdateFromContainer()
		key, value = super().popitem()
		return key, self._nested(key, value)
	
	def values(self):
		for key, value in self.items():
			yield value
	
	def _fetchUpdateFromContainer(self):
		"""Resynchronize this instance to its emitting container, if any.
		"""
		if not self.virtual:
			return
		cnt, cntKey = self.containerLink
		if cntKey in cnt.maps[0]:
			cntValue = cnt[cntKey]
			if not isinstance(cntValue, Mapping):
				raise Exception("Container as been assigned a non-mapping value")
			self.maps[0] = cntValue
			self.virtual = False
	
	def _nested(self, key, value):
		"""Convert the given value to a NestedChainMap if it is a Mapping.
		"""
		if not isinstance(value, Mapping) or len(self.maps) < 2:
			return value
		parents = []
		for parent in self.parents.maps:
			value = parent.get(key)
			if not isinstance(value, Mapping):
				break
			parents.append(value)
		virtual = {}
		first = self.maps[0].get(key, virtual)
		value = self.__class__(first, *parents)
		value.containerLink = (self, key)
		if first is virtual:
			value.virtual = True
		return value
	
	def _pushUpdateToContainer(self):
		if not self.virtual:
			return
		cnt, cntKey = self.containerLink
		cnt[cntKey] = self.maps[0]
		self.virtual = False


if __name__ == "__main__":
	if not __debug__:
		print("Please disable runtime optimization so that assert statements can be evaluated.")
		import sys
		sys.exit(2)
	from pprint import pformat
	maps = (
		{
			"a": "0a",
			"b": {
				"a": "0ba",
				"b": {
					"a": "0bba"
				}
			}
		},
		{
			"a": "1a",
			"b": {
				"a": "1ba",
				"b": {
					"a": "1bba",
					"b": "1bbb",
					"c": "1bbc",
				},
				"c": "1bc"
			},
			"c": "1c"
		}
	)
	ncm = NestedChainMap(*maps)
	ncm["b"]["b"]["b"] = "0bbb"
	
	expected = {
		"a": "0a",
		"b": {
			"a": "0ba",
			"b": {
				"a": "0bba",
				"b": "0bbb"
			}
		}
	}
	assert maps[0] == expected, f"""
Test:          maps[0]
Expected:      {pformat(expected)}
Actual result: {pformat(maps[0])}
"""
	
	expected = {
		"a": "0a",
		"b": {
			"a": "0ba",
			"b": {
				"a": "0bba",
				"b": "0bbb",
				"c": "1bbc"
			},
			"c": "1bc"
		},
		"c": "1c"
	}
	res = ncm.dump()
	assert res == expected, f"""
Test:           dump
Expected:       {pformat(expected)}
Actual result: {pformat(res)}
"""
	
	ncm.parents["b"]["b"]["b"] = "1bbb*"
	expected = {
			"a": "1a",
			"b": {
				"a": "1ba",
				"b": {
					"a": "1bba",
					"b": "1bbb*",
					"c": "1bbc",
				},
				"c": "1bc"
			},
			"c": "1c"
		}
	assert maps[1] == expected, f"""
Test:           parents
Expected:       {pformat(expected)}
Actual result: {pformat(res)}
"""
	
	combined = NestedChainMap(
		NestedChainMap(
			{"a": "00a", "b": {"a": "00ba"}},
			{"a": "01a", "b": {"a": "01ba", "b": "01bb"}},
		),
		NestedChainMap(
			{"a": "10a", "b": {"a": "10a"}},
			{"a": "11a", "b": {"a": "11ba", "b": "01bb", "c": "01bc"}},
		),
	)
	combined["b"]["b"] = "00bb"
	
	expected = {"a": "00a", "b": {"a": "00ba", "b": "00bb"}}
	assert combined.maps[0].maps[0] == expected, f"""
Test:           combined.maps[0].maps[0]
Expected:       {pformat(expected)}
Actual result: {pformat(res)}
"""

	expected = {"a": "01a", "b": {"a": "01ba", "b": "01bb"}}
	assert combined.maps[0].maps[1] == expected, f"""
Test:           combined.maps[0].maps[1]
Expected:       {pformat(expected)}
Actual result: {pformat(res)}
"""
	
	expected = {
		"a": "00a",
		"b": {
			"a": "00ba",
			"b": "00bb",
			"c": "01bc",
		}
	}
	assert combined.dump() == expected, f"""
Test:           combined dump
Expected:       {pformat(expected)}
Actual result: {pformat(res)}
"""
	
	combined.parents["a"] = "10a*"
	
	expected = {"a": "10a*", "b": {"a": "10a"}}
	assert combined.maps[1].maps[0] == expected, f"""
Test:           combined parents
Expected:       {pformat(expected)}
Actual result: {pformat(res)}
"""
	
	print("OK")
