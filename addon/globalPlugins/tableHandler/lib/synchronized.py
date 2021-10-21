# synchronized.py
# -*- coding: utf-8 -*-

# This file is a Python utility module.
# Copyright (C) 2017-2021 Accessolutions (https://accessolutions.fr)
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

"""
This module provides functions and methods decorators to allow
their synchronized execution (non-reentrant by concurrent threads).
"""

# Keep compatible with Python 2
from __future__ import absolute_import, division, print_function

__version__ = "2021.05.27"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

import threading


def synchronized(lockHolderGetter, lockAttrName, lockCreator=lambda: threading.RLock()):
	
	def decorator(func):
		
		def wrapper(*args, **kwargs):
			holder = lockHolderGetter(func, *args, **kwargs)
			if not hasattr(holder, lockAttrName):
				lock = lockCreator()
				setattr(holder, lockAttrName, lock)
			# Get back from holder in case of concurrent creation
			lock = getattr(holder, lockAttrName)
			with lock:
				return func(*args, **kwargs)
		
		return wrapper
	
	return decorator


def function(
	lockHolderGetter=lambda func, *args, **kwargs: func,
	lockAttrName="__lock__",
	lockCreator=lambda: threading.RLock(),
):
	"""
	Decorator for synchronized execution (non-reentrant by concurrent threads)
	of a function.
	
	The :threading.RLock: is held as an attribute of the decorated function itself.
	"""
	return synchronized(
		lockHolderGetter=lockHolderGetter, lockAttrName=lockAttrName, lockCreator=lockCreator
	)


def bound(func,
	lockHolderGetter=lambda func, *args, **kwargs: args[0],
	lockAttrName="__lock__",
	lockCreator=lambda: threading.RLock(),
):
	"""
	Decorator for synchronized execution (non-reentrant by concurrent threads)
	of an instance or class method.
	
	The :threading.RLock: is held as an attribute of the instance or class
	to which the decorated function is bound and scoped to this object.
	See :synchronized:
	"""
	return function(lockHolderGetter=lambda func, *args, **kwargs: args[0])(func)
	return synchronized(
		lockHolderGetter=lockHolderGetter, lockAttrName=lockAttrName, lockCreator=lockCreator
	)


def method(func):
	"""
	Decorator for synchronized execution (non-reentrant by concurrent threads)
	of an instance or class method.
	
	The :threading.RLock: is held as an attribute of the instance or class
	to which the decorated function is bound and scoped to this function.
	See :synchronized:
	"""
	return synchronized(
		lockHolderGetter=lambda func, *args, **kwargs: args[0],
		lockAttrName=f"{func.__name__}__lock__",
	)(func)


if __name__ == '__main__':
	print("Testing...")
	
	import time
	import sys
	# Alias to current module to allow client-code-like naming
	synchronized = sys.modules[__name__]
	
	class C:
		def __init__(self):
			self.counter = 0
		
		@synchronized.method
		def inc(self):
			new_value = self.counter + 1
			time.sleep(0.01)
			self.counter = new_value
		
		@synchronized.method
		def dec(self):
			new_value = self.counter - 1
			time.sleep(0.05)
			self.counter = new_value
	
	o = C()
	
	t1 = threading.Thread(target=lambda: [o.inc() for i in range(10)])
	t2 = threading.Thread(target=lambda: [o.dec() for i in range(10)])
	
	t1.start()
	t2.start()
	
	t1.join()
	t2.join()
	
	if o.counter == 0:
		print("OK")
	else:
		print("KO")
		print("counter: %s" % o.counter)
