# globalPlugins/tableHandler/gui/menu.py
# -*- coding: utf-8 -*-

# This file is part of Table Handler for NVDA.
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

"""Table Handler contextual menu"""

__author__ = "Julien Cochuyt <j.cochuyt@accessolutions.fr>"
__license__ = "GPL"

 
import wx

import addonHandler
addonHandler.initTranslation()
import controlTypes
import gui
import ui

from ..behaviors import Cell, TableManager
from ..scriptUtils import getScriptGestureMenuHint
from ..tableUtils import getColumnHeaderTextSafe, getRowHeaderTextSafe

def show():
	gui.mainFrame.prePopup()
	wx.CallAfter(Menu().Show)
	gui.mainFrame.postPopup()



class Menu(wx.Menu):
	
	def __init__(self):
		super().__init__()
		
		prevFocus = gui.mainFrame.prevFocus
		if isinstance(prevFocus, Cell):
			cell = prevFocus
			cfg = cell.table._tableConfig
			rowNum = cell.rowNumber
			colNum = cell.columnNumber
			
			sub = wx.Menu()
			
			colHeaRowNum = cfg["columnHeaderRowNumber"]
			if cell.role == controlTypes.ROLE_TABLECOLUMNHEADER:
				# Translators: An entry in the context menu Table Mode > Column Headers
				label = _("Use the default column headers of this table")
			else:
				# Translators: An entry in the context menu Table Mode > Column Headers
				label = _("Use this row as column headers")
			hint = getScriptGestureMenuHint(TableManager, TableManager.script_setColumnHeader)
			if hint:
				label += "\t{}".format(hint)
			item = sub.AppendCheckItem(wx.ID_ANY, label)
			self.Bind(wx.EVT_MENU, self.onSetColHeaderRowNumber, item)
			if colHeaRowNum == rowNum or (
				colHeaRowNum == None and cell.role == controlTypes.ROLE_TABLECOLUMNHEADER
			):
				item.Check()
			
			if colNum in cfg["customColumnHeaders"]:
				# Translators: An entry in the context menu Table Mode > Column Headers
				label = _("&Customized: {}").format(cfg["customColumnHeaders"][colNum])
			else:
				# Translators: An entry in the context menu Table Mode > Column Headers
				label = _("&Customize the header of this column")
			item = sub.AppendCheckItem(wx.ID_ANY, label)
			self.Bind(wx.EVT_MENU, self.onCustomizeColHeader, item)
			if colNum in cfg["customColumnHeaders"]:
				item.Check()
			
			# Translators: An entry in the Table Mode context menu
			self.AppendSubMenu(sub, _("Column Headers"))
			
			
			sub = wx.Menu()
			
			rowHeaColNum = cfg["rowHeaderColumnNumber"]
			if cell.role == controlTypes.ROLE_TABLEROWHEADER:
				# Translators: An entry in the context menu Table Mode > Row Headers
				label = _("Use the default row headers of this table")
			else:
				# Translators: An entry in the context menu Table Mode > Row Headers
				label = _("Use this column as row headers")
			hint = getScriptGestureMenuHint(TableManager, TableManager.script_setRowHeader)
			if hint:
				label += "\t{}".format(hint)
			item = sub.AppendCheckItem(wx.ID_ANY, label)
			self.Bind(wx.EVT_MENU, self.onSetRowHeaderColNumber, item)
			if rowHeaColNum == colNum or (
				rowHeaColNum == None and cell.role == controlTypes.ROLE_TABLEROWHEADER
			):
				item.Check()
			
			if rowNum in cfg["customRowHeaders"]:
				# Translators: An entry in the context menu Table Mode > Row Headers
				label = _("&Customized: {}").format(cfg["customRowHeaders"][rowNum])
			else:
				# Translators: An entry in the context menu Table Mode > Row Headers
				label = _("&Customize the header of this row")
			item = sub.AppendCheckItem(wx.ID_ANY, label)
			self.Bind(wx.EVT_MENU, self.onCustomizeRowHeader, item)
			if rowNum in cfg["customRowHeaders"]:
				item.Check()
			
			# Translators: An entry in the Table Mode context menu
			self.AppendSubMenu(sub, _("Row Headers"))
			
			sub = wx.Menu()
			
			if rowHeaColNum != colNum:
				items = {}
				
				# Translators: An entry in the context menu Table Mode > Marked Columns
				items[True] = item = sub.AppendRadioItem(wx.ID_ANY, _("Marked with &announce"))
				self.Bind(wx.EVT_MENU, self.onToggleMarkedCol_WithAnnounce, item)
				
				# Translators: An entry in the context menu Table Mode > Marked Columns
				items[False] = item = sub.AppendRadioItem(wx.ID_ANY, _("Marked with&out announce"))
				self.Bind(wx.EVT_MENU, self.onToggleMarkedCol_WithoutAnnounce, item)
				
				# Translators: An entry in the context menu Table Mode > Marked Columns
				items[None] = item = sub.AppendRadioItem(wx.ID_ANY, _("&Not marked"))
				self.Bind(wx.EVT_MENU, self.onToggleMarkedCol_Unmarked, item)
				
				items[cfg["markedColumnNumbers"].get(colNum)].Check()
			
			# Translators: An entry in the Table Mode context menu
			label = _("Marked Columns")
			hint = getScriptGestureMenuHint(TableManager, TableManager.script_toggleMarkedColumn)
			if hint:
				label += "\t{}".format(hint)
			
			item = self.AppendSubMenu(sub, label)
			if rowHeaColNum == colNum:
				self.Enable(item.Id, False)
			
			sub = wx.Menu()
			
			if colHeaRowNum != rowNum:
				items = {}
				
				# Translators: An entry in the context menu Table Mode > Marked Rows
				items[True] = item = sub.AppendRadioItem(wx.ID_ANY, _("Marked with &announce"))
				self.Bind(wx.EVT_MENU, self.onToggleMarkedRow_WithAnnounce, item)
				
				# Translators: An entry in the context menu Table Mode > Marked Rows
				items[False] = item = sub.AppendRadioItem(wx.ID_ANY, _("Marked with&out announce"))
				self.Bind(wx.EVT_MENU, self.onToggleMarkedRow_WithoutAnnounce, item)
				
				# Translators: An entry in the context menu Table Mode > Marked Rows
				items[None] = item = sub.AppendRadioItem(wx.ID_ANY, _("&Not marked"))
				self.Bind(wx.EVT_MENU, self.onToggleMarkedRow_Unmarked, item)
				
				items[cfg["markedRowNumbers"].get(rowNum)].Check()
			
			# Translators: An entry in the Table Mode context menu
			label = _("Marked Rows")
			hint = getScriptGestureMenuHint(TableManager, TableManager.script_toggleMarkedRow)
			if hint:
				label += "\t{}".format(hint)
			
			item = self.AppendSubMenu(sub, label)
			if colHeaRowNum == rowNum:
				self.Enable(item.Id, False)
		
		item = self.Append(
			wx.ID_ANY,
			# Translators: An item in NVDA's Preferences menu
			_("Table Mode Preferences..."),
			# Translators: The contextual help for an item in NVDA's Preferences menu
			_("Table Mode Preferences")
		)
		self.Bind(wx.EVT_MENU, self.onPreferences, item)
	
	def Show(self):
		gui.mainFrame.prePopup()
		gui.mainFrame.PopupMenu(self)
		gui.mainFrame.postPopup()
	
	def onSetColHeaderRowNumber(self, evt):
		cell = gui.mainFrame.prevFocus
		cfg = cell.table._tableConfig
		heaNum = cfg["columnHeaderRowNumber"]
		if cell.role == controlTypes.ROLE_TABLECOLUMNHEADER:
			if heaNum == False:
				cfg["columnHeaderRowNumber"] = None
				headerText = getColumnHeaderTextSafe(cell)
				# Translators: Announced when customizing column headers
				ui.message(_("Column header reset to default: {}").format(headerText))
			else:
				cfg["columnHeaderRowNumber"] = False
				# Translators: Announced when customizing column headers
				ui.message(_("Column header disabled"))
			return
		num = cell.rowNumber
		if heaNum == num:
			cfg["columnHeaderRowNumber"] = None
			headerText = getColumnHeaderTextSafe(cell)
			# Translators: Announced when customizing column headers
			ui.message(_("Column header reset to default: {}").format(headerText))
		else:
			cfg["columnHeaderRowNumber"] = num
			# Translators: Announced when customizing column headers
			ui.message(_("Row set as column header"))
	
	def onSetRowHeaderColNumber(self, evt):
		cell = gui.mainFrame.prevFocus
		cfg = cell.table._tableConfig
		heaNum = cfg["rowHeaderColumnNumber"]
		if cell.role == controlTypes.ROLE_TABLEROWHEADER:
			if heaNum == False:
				cfg["rowHeaderColumnNumber"] = None
				headerText = getRowHeaderTextSafe(cell)
				# Translators: Announced when customizing row headers
				ui.message(_("Row header reset to default: {}").format(headerText))
			else:
				cfg["rowHeaderColumnNumber"] = False
				# Translators: Announced when customizing row headers
				ui.message(_("Row header disabled"))
			return
		num = cell.columnNumber
		if heaNum == num:
			cfg["rowHeaderColumnNumber"] = None
			headerText = getRowHeaderTextSafe(cell)
			# Translators: Announced when customizing row headers
			ui.message(_("Row header reset to default: {}").format(headerText))
		else:
			cfg["rowHeaderColumnNumber"] = num
			# Translators: Announced when customizing row headers
			ui.message(_("Column set as row header"))
	
	def onCustomizeColHeader(self, evt):
		cell = gui.mainFrame.prevFocus
		cfg = cell.table._tableConfig
		customHeaders = cfg["customColumnHeaders"].copy()
		num = cell.columnNumber
		if num in customHeaders:
			del customHeaders[num]
			cfg["customColumnHeaders"] = customHeaders
			return
		dlg = wx.TextEntryDialog(
			gui.mainFrame,
			# Translators: A prompt to enter a value
			message=_("Enter a custom header for this column")
		)
		from logHandler import log
		if dlg.ShowModal() == wx.ID_OK:
			customHeaders[num] = dlg.Value
			cfg["customColumnHeaders"] = customHeaders
			log.info(f"new cfg: {cfg.data}")
			cfg.save()
		else:
			log.info(f"unchanged")
	
	def onCustomizeRowHeader(self, evt):
		cell = gui.mainFrame.prevFocus
		cfg = cell.table._tableConfig
		customHeaders = cfg["customRowHeaders"].copy()
		num = cell.rowNumber
		if num in customHeaders:
			del customHeaders[num]
			cfg["customRowHeaders"] = customHeaders
			return
		dlg = wx.TextEntryDialog(
			gui.mainFrame,
			# Translators: A prompt to enter a value
			message=_("Enter a custom header for this row")
		)
		if dlg.ShowModal() == wx.ID_OK:
			customHeaders[num] = dlg.Value
			cfg["customRowHeaders"] = customHeaders
			cfg.save()
	
	def onToggleMarkedCol_WithAnnounce(self, evt):
		cell = gui.mainFrame.prevFocus
		cfg = cell.table._tableConfig
		marked = cfg["markedColumnNumbers"].copy()
		num = cell.columnNumber
		marked[num] = True
		cfg["markedColumnNumbers"] = marked
	
	def onToggleMarkedCol_WithoutAnnounce(self, evt):
		cell = gui.mainFrame.prevFocus
		cfg = cell.table._tableConfig
		marked = cfg["markedColumnNumbers"].copy()
		num = cell.columnNumber
		marked[num] = False
		cfg["markedColumnNumbers"] = marked
	
	def onToggleMarkedCol_Unmarked(self, evt):
		cell = gui.mainFrame.prevFocus
		cfg = cell.table._tableConfig
		marked = cfg["markedColumnNumbers"].copy()
		num = cell.columnNumber
		marked.pop(num, None)
		cfg["markedColumnNumbers"] = marked
	
	def onToggleMarkedRow_WithAnnounce(self, evt):
		cell = gui.mainFrame.prevFocus
		cfg = cell.table._tableConfig
		marked = cfg["markedRowNumbers"].copy()
		num = cell.rowNumber
		marked[num] = True
		cfg["markedRowNumbers"] = marked
	
	def onToggleMarkedRow_WithoutAnnounce(self, evt):
		cell = gui.mainFrame.prevFocus
		cfg = cell.table._tableConfig
		marked = cfg["markedRowNumbers"].copy()
		num = cell.rowNumber
		marked[num] = False
		cfg["markedRowNumbers"] = marked
	
	def onToggleMarkedRow_Unmarked(self, evt):
		cell = gui.mainFrame.prevFocus
		cfg = cell.table._tableConfig
		marked = cfg["markedRowNumbers"].copy()
		num = cell.rowNumber
		marked.pop(num, None)
		cfg["markedRowNumbers"] = marked
	
	def onPreferences(self, evt):
		from gui.settingsDialogs import NVDASettingsDialog 
		from .settings import TableHandlerSettingsPanel
		gui.mainFrame._popupSettingsDialog(NVDASettingsDialog, TableHandlerSettingsPanel)
