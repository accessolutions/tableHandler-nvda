# globalPlugins/tableHander/gui/filter.py
# -*- coding: utf-8 -*-

# This file is part of Table Handlerfor NVDA.
# Copyright (C) 2020-2021 Accessolutions (http://accessolutions.fr)
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

"""Table Filter GUI."""

# Keep compatible with Python 2
from __future__ import absolute_import, division, print_function

__version__ = "2021.12.02"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"


import wx

import api
import addonHandler
import config
from core import callLater
from eventHandler import queueEvent
import gui
from logHandler import log

from ..brailleUtils import brailleCellsDecimalStringToUnicode
from ..nvdaVersion import nvdaVersion
from ..coreUtils import translate, wx_CallAfter

try:
	from gui import SettingsDialog, SettingsPanel
except ImportError:
	from ..backports.nvda_2018_2.gui_settingsDialogs import SettingsDialog, SettingsPanel
try:
	import guiHelper
except ImportError:
	from ..backports.nvda_2016_4 import gui_guiHelper as guiHelper


addonHandler.initTranslation()


@wx_CallAfter
def show(table):
	gui.mainFrame.prePopup()
	FilterDialog(table).ShowModal()
	gui.mainFrame.postPopup()


class FilterDialog(wx.Dialog):
	
	def __init__(self, table):
		# Translators: Table Filter Dialog title
		super().__init__(gui.mainFrame, title=_("Filter"))

		self.table = table

		mainSizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		item = self.text = sHelper.addLabeledControl(
			# Translators: Table filter Dialog prompt text
			_("Review only the table rows containing this text:"),
			wx.TextCtrl
		)
		item.Value = table.filterText or ""
		
		item = self.caseSensitive = sHelper.addItem(
			# Translators: The label for a settings in the Table Mode settings panel
			wx.CheckBox(self, label=translate("Case &sensitive"))
		)
		item.Value = caseSensitive if table.filterCaseSensitive is not None else False
		
		sHelper.addDialogDismissButtons(self.CreateButtonSizer(wx.OK | wx.CANCEL))
		mainSizer.Add(sHelper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		self.Bind(wx.EVT_BUTTON,self.onOk, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON,self.onCancel, id=wx.ID_CANCEL)
		mainSizer.Fit(self)
		self.SetSizer(mainSizer)
		self.CentreOnScreen()
		self.text.SetFocus()

	def onOk(self, evt):
		table = self.table
		text = self.text.Value
		caseSensitive = self.caseSensitive.Value
		callLater(
			100,
			table._onTableFilterChange,
			text=text,
			caseSensitive=caseSensitive
		)
		self.Destroy()

	def onCancel(self, evt):
		self.Destroy()
