# globalPlugins/tableHander/gui/settings.py
# -*- coding: utf-8 -*-

# This file is part of Table Handler for NVDA.
# Copyright (C) 2020-2024 Accessolutions (http://accessolutions.fr)
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

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"


import wx

import addonHandler
import config
import gui
from gui import guiHelper
from gui.settingsDialogs import SettingsDialog, SettingsPanel
from logHandler import log

from ..brailleUtils import brailleCellsDecimalStringToUnicode


addonHandler.initTranslation()


def initialize():
	gui.NVDASettingsDialog.categoryClasses.append(TableHandlerSettingsPanel)


def terminate():
	gui.NVDASettingsDialog.categoryClasses.remove(TableHandlerSettingsPanel)


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
		super().onOk(evt)
	
	def onCancel(self,evt):
		self.panel.onDiscard()
		self.panel.Destroy()
		super().onCancel(evt)


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
		return super().isValid()
	
	def makeSettings(self, settingsSizer):
		sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		item = self.quickNav = sHelper.addItem(
			# Translators: The label for a settings in the Table Mode settings panel
			wx.CheckBox(self, label=_(
				"Single letter &quick navigation between tables "
				"activates Table Mode"
			))
		)
		item.Value = config.conf["tableHandler"]["enableOnQuickNav"]
		item = self.brlDblClick = sHelper.addItem(
			# Translators: The label for a settings in the Table Mode settings panel
			wx.CheckBox(self, label=_(
				"&Double-click on braille routing cursor"
				" to activate controls within table cells"
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
		config.conf["tableHandler"]["enableOnQuickNav"] = self.quickNav.GetValue()
		config.conf["tableHandler"]["brailleRoutingDoubleClickToActivate"] = self.brlDblClick.GetValue()
		config.conf["tableHandler"]["brailleColumnSeparator"] = self.brlColSep.Value
		config.conf["tableHandler"]["brailleColumnSeparatorActivateToSetWidth"] = self.brlColSepActivate.Value
		config.conf["tableHandler"]["brailleSetColumnWidthWithRouting"] = self.brlColWidthRouting.Value
		from ..config import handleConfigChange
		handleConfigChange()
