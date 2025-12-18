# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import QDateTime, Qt, QVariant
from qgis.PyQt.QtWidgets import QInputDialog, QFileDialog
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from qgis.core import (
    QgsProject, QgsFeature, QgsGeometry, QgsPointXY,
    QgsVectorLayer, QgsField,
    QgsMarkerSymbol,
    QgsRasterMarkerSymbolLayer,
    QgsProperty,
    QgsSymbolLayer,
    QgsUnitTypes
)

from datetime import datetime, timezone, timedelta
from PIL import Image
from PIL.ExifTags import TAGS
from pathlib import Path
import os

# -------------------------------------------------------------------------------
# *** Bloc obligatoire pour plugin rédigé dans une langue autre que l'anglais ***
# *** 英語以外の言語で書かれたプラグインの必須ブロック ***
# -------------------------------------------------------------------------------
# 🌍 Localisation robuste — langue réellement utilisée par QGIS
#    - charge le QM correspondant à la langue QGIS si disponible
#    - fallback anglais si présent
#    - sinon : fonctionnement en langue source du plugin
# -------------------------------------------------------------------------
from qgis.core import QgsApplication, Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from pathlib import Path

settings = QSettings()
plugin_dir = Path(__file__).resolve().parent
plugin_name = Path(__file__).resolve().parent.name
i18n_dir = plugin_dir / "i18n"

translator = QTranslator()
loaded = False
# # ----------------------------------------------------------------------
# #  TRADUCTION — fonction unique
# # ----------------------------------------------------------------------
# TR_CONTEXT = "PhotoLocationByTime"
#
# def tr(text: str) -> str:
#     """
#     Fonction de traduction globale SAFE pour pylupdate
#     """
#     return QCoreApplication.translate(TR_CONTEXT, text)
# ----------------------------------------------------------------------
# LOGGING CENTRALISÉ
# ----------------------------------------------------------------------
LOG_TAG = "PluginTranslator"

def qgis_log(msg: str, level: str = "INFO"):
    lvl = {
        "TRACE": Qgis.Info,
        "DEBUG": Qgis.Info,
        "INFO": Qgis.Info,
        "WARNING": Qgis.Warning,
        "ERROR": Qgis.Critical,
    }.get(level.upper(), Qgis.Info)

    QgsMessageLog.logMessage(msg, LOG_TAG, lvl)
# -------------------------------------------------------------------------
# 1️⃣ Langue réellement utilisée par QGIS
# -------------------------------------------------------------------------
locale_full = QgsApplication.locale() or settings.value("locale/userLocale", "")
lang = locale_full.split("_")[0].lower() if locale_full else ""

qgis_log(f"[i18n] ローカルQGISが検出されました : {locale_full}", "DEBUG")
qgis_log(f"[i18n] QGIS言語が検出されました : {lang or '未定'}", "DEBUG")

# -------------------------------------------------------------------------
# 2️⃣ Chargement QM
# -------------------------------------------------------------------------
def load_qm(code: str) -> bool:
    qm = i18n_dir / f"{plugin_name}_{code}.qm"
    if qm.exists() and translator.load(str(qm)):
        qgis_log(f"[i18n] QM chargé : {qm.name}", "DEBUG")
        return True
    return False
# -------------------------------------------------------------------------
# 3️⃣ Logique de sélection (sans hypothèse sur la langue source)
# Traduire les chaines dans votre langue
# -------------------------------------------------------------------------
if lang and load_qm(lang):
    loaded = True
    qgis_log(f"[i18n] QGIS言語の翻訳が可能 : {lang}", "INFO")
elif load_qm("en"):
    loaded = True
    qgis_log(
        "[i18n] QGIS 言語翻訳が見つかりません → 英語にフォールバックします",
        "WARNING"
    )
else:
    qgis_log(
        "[i18n] 互換性のあるQMが見つかりません → ソース言語のプラグイン関数",
        "INFO"
    )
# -------------------------------------------------------------------------
# 4️⃣ Installation du translator
# -------------------------------------------------------------------------
if loaded:
    QCoreApplication.installTranslator(translator)
# -------------------------------------------------------------------------------
# *** Fin du bloc obligatoire pour plugin rédigé dans une langue autre que l'anglais ***
# -------------------------------------------------------------------------------


class PhotoLocationByTime:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.action = None
        self.TR_CONTEXT = self.__class__.__name__

    def tr(self, text: str) -> str:
        from qgis.PyQt.QtCore import QCoreApplication
        return QCoreApplication.translate(self.TR_CONTEXT, text)

    def initGui(self):
        icon_path = self.plugin_dir / "icon.png"
        self.action = QAction(
            QIcon(str(icon_path)),
            self.tr("写真位置推定"),
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Photo Location By Time", self.action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("&Photo Location By Time", self.action)

    def run(self):
        try:
            self.process_photos()
        except Exception as e:
            self.iface.messageBar().pushCritical("PhotoLocationByTime", str(e))

    def process_photos(self):
        # 1) GPX レイヤ選択
        layers = [l for l in QgsProject.instance().mapLayers().values()
                  if l.type() == l.VectorLayer]
        layer_names = [l.name() for l in layers]

        layer_name, ok = QInputDialog.getItem(
            self.iface.mainWindow(),
            self.tr("GPXレイヤ選択"),
            self.tr("GPXポイントレイヤを選択:"),
            layer_names,
            0,
            False
        )
        if not ok:
            raise RuntimeError(self.tr("GPXレイヤが選択されていません。"))

        gpx_layer = layers[layer_names.index(layer_name)]

        # 2) time フィールド
        time_field = None
        for f in gpx_layer.fields():
            if f.name().lower() in ["time", "timestamp", "t"]:
                time_field = f.name()
                break
        if not time_field:
            raise RuntimeError(self.tr("GPXレイヤに time フィールドが見つかりません。"))

        # 3) GPX 時刻＋位置
        gpx_points = []
        for f in gpx_layer.getFeatures():
            qdt = f[time_field]
            if isinstance(qdt, QDateTime):
                iso = qdt.toString(Qt.ISODate)
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                gpx_points.append((dt, f.geometry().asPoint()))

        gpx_points.sort(key=lambda x: x[0])
        if len(gpx_points) < 2:
            raise RuntimeError(self.tr("GPXポイントが不足しています。"))

        # 4) 写真フォルダ
        photo_dir = QFileDialog.getExistingDirectory(
            self.iface.mainWindow(),
            self.tr("写真フォルダを選択")
        )
        if not photo_dir:
            raise RuntimeError(self.tr("写真フォルダが選択されていません。"))

        # 5) 写真ポイントレイヤ
        vl = QgsVectorLayer(
            f"Point?crs={gpx_layer.crs().authid()}",
            "PhotoPoints",
            "memory"
        )
        pr = vl.dataProvider()
        pr.addAttributes([
            QgsField("fullpath", QVariant.String),
            QgsField("filename", QVariant.String),
            QgsField("exif_time", QVariant.DateTime),
        ])
        vl.updateFields()

        # 6) EXIF 時刻
        def get_photo_time(path):
            try:
                img = Image.open(path)
                exif = img._getexif()
                if not exif:
                    return None
                for tag, value in exif.items():
                    if TAGS.get(tag) == "DateTimeOriginal":
                        dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        dt -= timedelta(hours=9)
                        return dt.replace(tzinfo=timezone.utc)
            except:
                return None
            return None

        # 7) 補間
        def interpolate_position(photo_time):
            for i in range(len(gpx_points) - 1):
                t1, p1 = gpx_points[i]
                t2, p2 = gpx_points[i + 1]
                if t1 <= photo_time <= t2:
                    r = (photo_time - t1).total_seconds() / (t2 - t1).total_seconds()
                    return QgsPointXY(
                        p1.x() + (p2.x() - p1.x()) * r,
                        p1.y() + (p2.y() - p1.y()) * r
                    )
            return None

        # 8) 写真処理
        for file in os.listdir(photo_dir):
            if not file.lower().endswith((".jpg", ".jpeg")):
                continue

            fpath = os.path.join(photo_dir, file)
            ptime = get_photo_time(fpath)
            if not ptime:
                continue

            pos = interpolate_position(ptime)
            if not pos:
                continue

            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(pos))
            feat.setAttributes([
                fpath,
                file,
                QDateTime.fromSecsSinceEpoch(
                    int((ptime + timedelta(hours=9)).timestamp())
                )
            ])
            pr.addFeature(feat)

        vl.updateExtents()
        QgsProject.instance().addMapLayer(vl)

        # 9) 🔴 ラスタ画像マーカー設定
        symbol = QgsMarkerSymbol.createSimple({})
        
        raster_layer = QgsRasterMarkerSymbolLayer()
        raster_layer.setSize(10)  # ← 幅・高さ(m)
        #raster_layer.setSizeUnit(QgsUnitTypes.RenderMapUnits)  # ← 地図上の単位
        raster_layer.setSizeUnit(QgsUnitTypes.RenderMetersInMapUnits) # ← 縮尺済みメートル
        
        raster_layer.setDataDefinedProperty(
            QgsSymbolLayer.PropertyName,
            QgsProperty.fromField("fullpath")
        )

        symbol.changeSymbolLayer(0, raster_layer)
        vl.renderer().setSymbol(symbol)
        vl.triggerRepaint()
