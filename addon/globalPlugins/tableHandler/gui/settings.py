# globalPlugins/tableHander/gui/settings.py
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

"""Table Handler GUI."""

# Keep compatible with Python 2
from __future__ import absolute_import, division, print_function

__version__ = "2021.11.12"
__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"


import wx

import addonHandler
import config
import gui
from logHandler import log

from ..brailleUtils import brailleCellsDecimalStringToUnicode
from ..nvdaVersion import nvdaVersion

try:
	from gui import SettingsDialog, SettingsPanel
except ImportError:
	from ..backports.nvda_2018_2.gui_settingsDialogs import SettingsDialog, SettingsPanel
try:
	import guiHelper
except ImportError:
	from ..backports.nvda_2016_4 import gui_guiHelper as guiHelper


addonHandler.initTranslation()


def initialize():
	if nvdaVersion >= (2018, 2):
		gui.NVDASettingsDialog.categoryClasses.append(TableHandlerSettingsPanel)
	else:
		sysTrayIcon = gui.mainFrame.sysTrayIcon
		preferencesMenu = sysTrayIcon.preferencesMenu
		global _tableHandlerMenuItem
		_tableHandlerMenuItem = preferencesMenu.Append(
			wx.ID_ANY,
			# Translators: An item in NVDA's Preferences menu
			_("&Table Mode..."),
			# Translators: The contextual help for an item in NVDA's Preferences menu
			_("Table Mode Preferences")
		)
		sysTrayIcon.Bind(
			wx.EVT_MENU,
			lambda evt: gui.mainFrame._popupSettingsDialog(TableHandlerSettingsDialog),
			_tableHandlerMenuItem
		)


def terminate():
	if nvdaVersion >= (2018, 2):
		gui.NVDASettingsDialog.categoryClasses.remove(TableHandlerSettingsPanel)
	else:
		global _tableHandlerMenuItem
		gui.mainFrame.sysTrayIcon.preferencesMenu.Remove(_tableHandlerMenuItem.id)
		_tableHandlerMenuItem.Destroy()
		_tableHandlerMenuItem = None



class TableHandlerSettingsDialog(SettingsDialog):
	
	panel = None
	# Translators: The title of a dialog
	title = _("Table Mode Preferences")
	
	def makeSettings(self, settingsSizer):
		panel = self.panel = TableHandlerSettingsPanel(self)
		settingsSizer.Add(
			panel,
			flag=wx.EXPAND | wx.ALL,
			proportion=1,
			border=guiHelper.SPACE_BETWEEN_ASSOCIATED_CONTROL_HORIZONTAL
		)
	
	def postInit(self):
		self.Layout()
		self.panel.SetFocus()
	
	def _doSave(self):
		if self.panel.isValid() is False:
			raise ValueError("Validation for %s blocked saving settings" % self.panel.__class__.__name__)
		self.panel.onSave()
		self.panel.postSave()
	
	def onOk(self,evt):
		try:
			self._doSave()
		except ValueError:
			log.debugWarning("", exc_info=True)
			return
		self.panel.Destroy()
		super(TableHandlerSettingsDialog, self).onOk(evt)
	
	def onCancel(self,evt):
		self.panel.onDiscard()
		self.panel.Destroy()
		super(TableHandlerSettingsDialog, self).onCancel(evt)


class TableHandlerSettingsPanel(SettingsPanel):
	# Translators: The label for a category in the settings dialog
	title = _("Table Mode")
	
	def isValid(self):
		try:
			brailleCellsDecimalStringToUnicode(self.brlColSep.Value)
		except Exception:
			log.info(
				"Error validating brailleColumnSeparator={!r}".format(self.brlColSep.Value),
				exc_info=True
			)
			return False
		return super(TableHandlerSettingsPanel, self).isValid()
	
	def makeSettings(self, settingsSizer):
		sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		item = self.brlDblClick = sHelper.addItem(
			# Translators: The label for a settings in the Table Mode settings panel
			wx.CheckBox(self, label=_(
				"&Double-click on braille routing cursor"
				" to activate controls within table cells."
			))
		)
		item.Value = config.conf["tableHandler"]["brailleRoutingDoubleClickToActivate"]
		item = self.brlColSep = sHelper.addLabeledControl(
			# Translators: The label for a settings in the Table Mode settings panel
			_(
				"Braille dots to display as column &separator."
				" (eg. \"0-4568-0\"):"),
			wx.TextCtrl
		)
		item.Value = config.conf["tableHandler"]["brailleColumnSeparator"]
		item = self.brlColSepActivate = sHelper.addItem(
			# Translators: The label for a settings in the Table Mode settings panel
			wx.CheckBox(self, label=_(
				"Activate a braille column separator to begin customization of the column width"
			))
		)
		item.Value = config.conf["tableHandler"]["brailleColumnSeparatorActivateToSetWidth"]
		item = self.brlColWidthRouting = sHelper.addItem(
			# Translators: The label for a settings in the Table Mode settings panel
			wx.CheckBox(self, label=_(
				"When customizing the &width of a column in braille, "
				"clicking on a routing cursor sets the desired width, "
				"instead of ending the customization"
			))
		)
		item.Value = config.conf["tableHandler"]["brailleSetColumnWidthWithRouting"]
	
	def onSave(self):
		config.conf["tableHandler"]["brailleRoutingDoubleClickToActivate"] = self.brlDblClick.GetValue()
		config.conf["tableHandler"]["brailleColumnSeparator"] = self.brlColSep.Value
		config.conf["tableHandler"]["brailleColumnSeparatorActivateToSetWidth"] = self.brlColSepActivate.Value
		config.conf["tableHandler"]["brailleSetColumnWidthWithRouting"] = self.brlColWidthRouting.Value
		from ..config import handleConfigChange
		handleConfigChange()
