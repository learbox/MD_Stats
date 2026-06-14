# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main_window.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QSpacerItem, QSplitter, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, centralWidget):
        if not centralWidget.objectName():
            centralWidget.setObjectName(u"centralWidget")
        centralWidget.resize(1100, 700)
        self.rootLayout = QVBoxLayout(centralWidget)
        self.rootLayout.setSpacing(10)
        self.rootLayout.setObjectName(u"rootLayout")
        self.rootLayout.setContentsMargins(14, 14, 14, 14)
        self.topPanel = QFrame(centralWidget)
        self.topPanel.setObjectName(u"topPanel")
        self.topPanel.setFrameShape(QFrame.NoFrame)
        self.ctrlLayout = QHBoxLayout(self.topPanel)
        self.ctrlLayout.setSpacing(10)
        self.ctrlLayout.setObjectName(u"ctrlLayout")
        self.ctrlLayout.setContentsMargins(14, 6, 14, 6)
        self.btn_start = QPushButton(self.topPanel)
        self.btn_start.setObjectName(u"btn_start")

        self.ctrlLayout.addWidget(self.btn_start)

        self.btn_stop = QPushButton(self.topPanel)
        self.btn_stop.setObjectName(u"btn_stop")
        self.btn_stop.setEnabled(False)

        self.ctrlLayout.addWidget(self.btn_stop)

        self.spacerCtrl1 = QSpacerItem(20, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.ctrlLayout.addItem(self.spacerCtrl1)

        self.label_deck = QLabel(self.topPanel)
        self.label_deck.setObjectName(u"label_deck")

        self.ctrlLayout.addWidget(self.label_deck)

        self.deck_input = QLineEdit(self.topPanel)
        self.deck_input.setObjectName(u"deck_input")
        self.deck_input.setMaximumSize(QSize(160, 16777215))

        self.ctrlLayout.addWidget(self.deck_input)

        self.btn_lock_deck = QPushButton(self.topPanel)
        self.btn_lock_deck.setObjectName(u"btn_lock_deck")

        self.ctrlLayout.addWidget(self.btn_lock_deck)

        self.spacerCtrl2 = QSpacerItem(20, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.ctrlLayout.addItem(self.spacerCtrl2)

        self.btn_manual_win = QPushButton(self.topPanel)
        self.btn_manual_win.setObjectName(u"btn_manual_win")

        self.ctrlLayout.addWidget(self.btn_manual_win)

        self.btn_manual_lose = QPushButton(self.topPanel)
        self.btn_manual_lose.setObjectName(u"btn_manual_lose")

        self.ctrlLayout.addWidget(self.btn_manual_lose)

        self.btn_undo = QPushButton(self.topPanel)
        self.btn_undo.setObjectName(u"btn_undo")
        self.btn_undo.setVisible(False)

        self.ctrlLayout.addWidget(self.btn_undo)

        self.spacerCtrlStretch = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.ctrlLayout.addItem(self.spacerCtrlStretch)


        self.rootLayout.addWidget(self.topPanel)

        self.splitter = QSplitter(centralWidget)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Vertical)
        self.stats_table = QTableWidget(self.splitter)
        self.stats_table.setObjectName(u"stats_table")
        self.stats_table.setAlternatingRowColors(True)
        self.stats_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stats_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.splitter.addWidget(self.stats_table)
        self.record_table = QTableWidget(self.splitter)
        self.record_table.setObjectName(u"record_table")
        self.record_table.setAlternatingRowColors(True)
        self.record_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.splitter.addWidget(self.record_table)

        self.rootLayout.addWidget(self.splitter)

        self.bottomPanel = QFrame(centralWidget)
        self.bottomPanel.setObjectName(u"bottomPanel")
        self.bottomPanel.setFrameShape(QFrame.NoFrame)
        self.bottomLayout = QHBoxLayout(self.bottomPanel)
        self.bottomLayout.setSpacing(10)
        self.bottomLayout.setObjectName(u"bottomLayout")
        self.bottomLayout.setContentsMargins(14, 6, 14, 6)
        self.btn_reload = QToolButton(self.bottomPanel)
        self.btn_reload.setObjectName(u"btn_reload")
        self.btn_reload.setPopupMode(QToolButton.MenuButtonPopup)

        self.bottomLayout.addWidget(self.btn_reload)

        self.btn_copy = QPushButton(self.bottomPanel)
        self.btn_copy.setObjectName(u"btn_copy")

        self.bottomLayout.addWidget(self.btn_copy)

        self.btn_open_csv = QPushButton(self.bottomPanel)
        self.btn_open_csv.setObjectName(u"btn_open_csv")

        self.bottomLayout.addWidget(self.btn_open_csv)

        self.btn_settings = QPushButton(self.bottomPanel)
        self.btn_settings.setObjectName(u"btn_settings")

        self.bottomLayout.addWidget(self.btn_settings)

        self.spacerDelete = QSpacerItem(20, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.bottomLayout.addItem(self.spacerDelete)

        self.btn_delete_last = QToolButton(self.bottomPanel)
        self.btn_delete_last.setObjectName(u"btn_delete_last")
        self.btn_delete_last.setPopupMode(QToolButton.MenuButtonPopup)

        self.bottomLayout.addWidget(self.btn_delete_last)

        self.btn_float = QPushButton(self.bottomPanel)
        self.btn_float.setObjectName(u"btn_float")

        self.bottomLayout.addWidget(self.btn_float)

        self.btn_about = QPushButton(self.bottomPanel)
        self.btn_about.setObjectName(u"btn_about")

        self.bottomLayout.addWidget(self.btn_about)

        self.spacerBottomStretch = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.bottomLayout.addItem(self.spacerBottomStretch)


        self.rootLayout.addWidget(self.bottomPanel)

        self.customStatusBar = QFrame(centralWidget)
        self.customStatusBar.setObjectName(u"customStatusBar")
        self.customStatusBar.setFrameShape(QFrame.NoFrame)
        self.statusLayout = QHBoxLayout(self.customStatusBar)
        self.statusLayout.setSpacing(10)
        self.statusLayout.setObjectName(u"statusLayout")
        self.statusLayout.setContentsMargins(12, 3, 12, 3)
        self.statusMessage = QLabel(self.customStatusBar)
        self.statusMessage.setObjectName(u"statusMessage")

        self.statusLayout.addWidget(self.statusMessage)

        self.spacerStatus = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.statusLayout.addItem(self.spacerStatus)

        self.infoLabel = QLabel(self.customStatusBar)
        self.infoLabel.setObjectName(u"infoLabel")
        self.infoLabel.setAlignment(Qt.AlignRight|Qt.AlignVCenter)

        self.statusLayout.addWidget(self.infoLabel)


        self.rootLayout.addWidget(self.customStatusBar)


        self.retranslateUi(centralWidget)

        QMetaObject.connectSlotsByName(centralWidget)
    # setupUi

    def retranslateUi(self, centralWidget):
        centralWidget.setWindowTitle(QCoreApplication.translate("MainWindow", u"MD Stats", None))
        self.btn_start.setText(QCoreApplication.translate("MainWindow", u"\u542f\u52a8", None))
        self.btn_stop.setText(QCoreApplication.translate("MainWindow", u"\u505c\u6b62", None))
        self.label_deck.setText(QCoreApplication.translate("MainWindow", u"\u4f7f\u7528\u5361\u7ec4:", None))
        self.deck_input.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u8f93\u5165\u5f53\u524d\u4f7f\u7528\u7684\u5361\u7ec4\u540d\u79f0", None))
        self.btn_lock_deck.setText(QCoreApplication.translate("MainWindow", u"\u4fee\u6539\u5361\u7ec4", None))
        self.btn_manual_win.setText(QCoreApplication.translate("MainWindow", u"\u8d62\u786c\u5e01", None))
        self.btn_manual_lose.setText(QCoreApplication.translate("MainWindow", u"\u8f93\u786c\u5e01", None))
        self.btn_undo.setText(QCoreApplication.translate("MainWindow", u"\u64a4\u9500", None))
        self.btn_reload.setText(QCoreApplication.translate("MainWindow", u"\u52a0\u8f7d\u6570\u636e", None))
        self.btn_copy.setText(QCoreApplication.translate("MainWindow", u"\u590d\u5236\u7edf\u8ba1", None))
        self.btn_open_csv.setText(QCoreApplication.translate("MainWindow", u"\u6253\u5f00 data.csv \u76ee\u5f55", None))
        self.btn_settings.setText(QCoreApplication.translate("MainWindow", u"\u8bbe\u7f6e", None))
        self.btn_delete_last.setText(QCoreApplication.translate("MainWindow", u"\u5220\u9664\u6700\u540e\u8bb0\u5f55", None))
        self.btn_float.setText(QCoreApplication.translate("MainWindow", u"\u60ac\u6d6e\u7a97", None))
        self.btn_about.setText(QCoreApplication.translate("MainWindow", u"\u5173\u4e8e", None))
        self.statusMessage.setText(QCoreApplication.translate("MainWindow", u"\u5c31\u7eea \u2014 \u8bf7\u70b9\u51fb\u300a\u542f\u52a8\u300b\u5f00\u59cb", None))
        self.infoLabel.setText(QCoreApplication.translate("MainWindow", u"\u6b63\u5728\u52a0\u8f7d\u2026", None))
    # retranslateUi

