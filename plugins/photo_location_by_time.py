# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import QDateTime, Qt, QVariant
from qgis.PyQt.QtWidgets import QAction, QInputDialog, QFileDialog
from qgis.core import (
    QgsProject, QgsFeature, QgsGeometry, QgsPointXY,
    QgsVectorLayer, QgsField
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from datetime import datetime, timezone, timedelta
from PIL import Image
from PIL.ExifTags import TAGS
import os

class PhotoLocationByTime:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        icon = QIcon(icon_path)

        # 親を self.iface.mainWindow() に渡すかどうかで書き方を変える
        self.action = QAction(icon, "写真位置推定", self.iface.mainWindow())

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
        layers = [l for l in QgsProject.instance().mapLayers().values() if l.type() == l.VectorLayer]
        layer_names = [l.name() for l in layers]
        current_layer_name = self.iface.activeLayer().name() if self.iface.activeLayer() else ""

        layer_name, ok = QInputDialog.getItem(
            None, "GPXレイヤ選択", "GPXポイントレイヤを選択:",
            layer_names,
            layer_names.index(current_layer_name) if current_layer_name in layer_names else 0,
            False
        )
        if not ok:
            raise RuntimeError("GPXレイヤが選択されていません。")

        gpx_layer = layers[layer_names.index(layer_name)]

        # 2) GPX の time フィールド取得
        time_field = None
        for f in gpx_layer.fields():
            if f.name().lower() in ["time", "timestamp", "t"]:
                time_field = f.name()
                break
        if not time_field:
            raise RuntimeError("GPXレイヤに time フィールドが見つかりません。")

        # 3) GPX 時刻 + 位置を抽出 → UTC aware datetime に変換
        gpx_points = []
        for f in gpx_layer.getFeatures():
            qdt = f[time_field]
            if isinstance(qdt, QDateTime):
                iso = qdt.toString(Qt.ISODate)
                try:
                    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                except:
                    continue
                gpx_points.append((dt, f.geometry().asPoint()))
        gpx_points.sort(key=lambda x: x[0])
        if len(gpx_points) < 2:
            raise RuntimeError(f"有効な GPX 時刻ポイントが 2 以上必要です（現在 {len(gpx_points)} 個）")

        # 4) 写真フォルダ選択
        photo_dir = QFileDialog.getExistingDirectory(None, "写真フォルダを選択")
        if not photo_dir:
            raise RuntimeError("写真フォルダが選択されていません。")

        # 5) 写真ポイント用レイヤ作成
        vl = QgsVectorLayer(f"Point?crs={gpx_layer.crs().authid()}", "PhotoPoints", "memory")
        pr = vl.dataProvider()
        pr.addAttributes([
            QgsField("filepath", QVariant.String),
            QgsField("filename", QVariant.String),
            QgsField("exif_time", QVariant.DateTime),
        ])
        vl.updateFields()

        # 6) 写真 EXIF 時刻取得
        def get_photo_time(path):
            try:
                img = Image.open(path)
                exif = img._getexif()
                if not exif:
                    return None
                for tag, value in exif.items():
                    tag_name = TAGS.get(tag, tag)
                    if tag_name == "DateTimeOriginal":
                        dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        dt_utc = dt - timedelta(hours=9)
                        return dt_utc.replace(tzinfo=timezone.utc)
            except:
                return None
            return None

        # 7) 時刻補間
        def interpolate_position(photo_time):
            if photo_time <= gpx_points[0][0]:
                return gpx_points[0][1]
            if photo_time >= gpx_points[-1][0]:
                return gpx_points[-1][1]
            for i in range(len(gpx_points)-1):
                t1, p1 = gpx_points[i]
                t2, p2 = gpx_points[i+1]
                if t1 <= photo_time <= t2:
                    ratio = (photo_time - t1).total_seconds() / (t2 - t1).total_seconds()
                    x = p1.x() + (p2.x() - p1.x()) * ratio
                    y = p1.y() + (p2.y() - p1.y()) * ratio
                    return QgsPointXY(x, y)
            return None

        # 8) 写真処理
        for file in os.listdir(photo_dir):
            if not file.lower().endswith((".jpg", ".jpeg")):
                continue
            fpath = os.path.join(photo_dir, file)
            ptime = get_photo_time(fpath)
            if not ptime:
                continue

            ptime_jst = ptime + timedelta(hours=9)

            pos = interpolate_position(ptime)
            if not pos:
                continue
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(pos))

            qdt = QDateTime(ptime_jst.year, ptime_jst.month, ptime_jst.day,
                            ptime_jst.hour, ptime_jst.minute, ptime_jst.second)
            feat.setAttributes([fpath, file, qdt])
            pr.addFeature(feat)

        vl.updateExtents()
        QgsProject.instance().addMapLayer(vl)
