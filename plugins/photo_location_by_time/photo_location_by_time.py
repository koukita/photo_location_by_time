# -*- coding: utf-8 -*-
from pathlib import Path
import os
from datetime import datetime, timezone, timedelta

from qgis.PyQt.QtCore import (
    QDateTime,
    Qt,
    QMetaType,
    QSettings,
    QTranslator,
    QCoreApplication,
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QInputDialog, QFileDialog

from qgis.core import (
    QgsApplication,
    Qgis,
    QgsMessageLog,
    QgsProject,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsField,
    QgsMarkerSymbol,
    QgsRasterMarkerSymbolLayer,
    QgsProperty,
    QgsSymbolLayer,
    QgsUnitTypes,
)

from PIL import Image
from PIL.ExifTags import TAGS

# -------------------------------------------------------------------------
# ログ
# -------------------------------------------------------------------------
LOG_TAG = "PhotoLocationByTime"

def qgis_log(msg, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, LOG_TAG, level)

# -------------------------------------------------------------------------
# i18n
# -------------------------------------------------------------------------
plugin_dir = Path(__file__).resolve().parent
plugin_name = plugin_dir.name
i18n_dir = plugin_dir / "i18n"

settings = QSettings()
locale_full = QgsApplication.locale() or settings.value("locale/userLocale", "")
lang = locale_full.split("_")[0].lower() if locale_full else ""

translator = QTranslator()
qm = i18n_dir / f"{plugin_name}_{lang}.qm"
if qm.exists() and translator.load(str(qm)):
    QCoreApplication.installTranslator(translator)

# -------------------------------------------------------------------------
# メインクラス
# -------------------------------------------------------------------------
class PhotoLocationByTime:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.action = None
        self.TR_CONTEXT = self.__class__.__name__

    def tr(self, text):
        return QCoreApplication.translate(self.TR_CONTEXT, text)

    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    def run(self):
        try:
            self.process_photos()
        except Exception as e:
            self.iface.messageBar().pushCritical(
                "PhotoLocationByTime",
                str(e)
            )
            qgis_log(str(e), Qgis.Critical)

    # ------------------------------------------------------------
    def process_photos(self):
        # 1) GPXレイヤ選択
        layers = [
            l for l in QgsProject.instance().mapLayers().values()
            if l.type() == l.VectorLayer
        ]
        layer_names = [l.name() for l in layers]

        name, ok = QInputDialog.getItem(
            self.iface.mainWindow(),
            self.tr("GPXレイヤ選択"),
            self.tr("GPXポイントレイヤを選択:"),
            layer_names,
            0,
            False
        )
        if not ok:
            raise RuntimeError(self.tr("GPXレイヤが選択されていません。"))

        gpx_layer = layers[layer_names.index(name)]

        # 2) time フィールド
        time_field = None
        for f in gpx_layer.fields():
            if f.name().lower() in ("time", "timestamp", "t"):
                time_field = f.name()
                break
        if not time_field:
            raise RuntimeError(self.tr("GPXレイヤに time フィールドがありません。"))

        # 3) GPX時刻（UTC tz-aware）
        gpx_points = []
        for f in gpx_layer.getFeatures():
            val = f[time_field]

            if isinstance(val, QDateTime):
                dt = val.toPyDateTime()
            elif isinstance(val, str):
                try:
                    dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                except Exception:
                    qgis_log(f"GPX時刻解析失敗: {val}", Qgis.Warning)
                    continue
            else:
                continue

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

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
            QgsField("fullpath", QMetaType.Type.QString),
            QgsField("filename", QMetaType.Type.QString),
            QgsField("exif_time", QMetaType.Type.QDateTime),
            QgsField("direction", QMetaType.Type.Double),  # ★ 撮影方向
        ])
        vl.updateFields()

        # 6) Exif 時刻
        def get_photo_time(path):
            try:
                img = Image.open(path)
                exif = img._getexif()
                if not exif:
                    return None
                for tag_id, value in exif.items():
                    if TAGS.get(tag_id) == "DateTimeOriginal":
                        dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        return (dt - timedelta(hours=9)).replace(tzinfo=timezone.utc)
            except Exception as e:
                qgis_log(f"EXIF時刻取得失敗 {path}: {e}", Qgis.Warning)
            return None

        # 7) Exif 撮影方向（GPSImgDirection）
        def get_photo_direction(path):
            try:
                img = Image.open(path)
                exif = img._getexif()
                if not exif:
                    return None

                for tag_id, value in exif.items():
                    if TAGS.get(tag_id) == "GPSInfo":
                        gps = value
                        # GPSImgDirection = 17
                        if 17 in gps:
                            v = gps[17]
                            if isinstance(v, tuple):
                                return float(v[0]) / float(v[1])
                            return float(v)
            except Exception as e:
                qgis_log(f"撮影方向取得失敗 {path}: {e}", Qgis.Warning)

            return None

        # 8) 補間
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

        # 9) 写真処理
        created = 0
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

            direction = get_photo_direction(fpath)

            feat = QgsFeature(vl.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(pos))
            feat.setAttributes([
                fpath,
                file,
                QDateTime.fromSecsSinceEpoch(int(ptime.timestamp())),
                direction,
            ])
            pr.addFeature(feat)
            created += 1

        if created == 0:
            raise RuntimeError(self.tr("写真ポイントが1件も作成されませんでした。"))

        vl.updateExtents()
        QgsProject.instance().addMapLayer(vl)

        # 10) ラスタ画像マーカー
        symbol = QgsMarkerSymbol.createSimple({})
        raster = QgsRasterMarkerSymbolLayer()
        raster.setSize(10)
        raster.setSizeUnit(QgsUnitTypes.RenderMetersInMapUnits)
        raster.setDataDefinedProperty(
            QgsSymbolLayer.PropertyName,
            QgsProperty.fromField("fullpath")
        )
        symbol.changeSymbolLayer(0, raster)
        vl.renderer().setSymbol(symbol)
        vl.triggerRepaint()

        qgis_log(f"作成された写真ポイント数: {created}", Qgis.Info)
