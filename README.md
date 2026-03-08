# photo_location_by_time
写真の時間とGPXの時間を突合して、写真の位置を推定するプラグイン
![image.gif](https://github.com/koukita/photo_location_by_time/blob/main/image/Photo_GPX.gif)

# 必要なライブラリ
このプラグインでは、画像処理を行うためのPythonライブラリ「Pillow」が必要です。
QGISをインストールすると同時にインストールされているはずなので、通常は特に気にする必要はありません。
プラグインインストール時に「Pillow」に関するエラーが表示された場合には、Windowsの場合はOSGeo4wshellでPillowをインストールしてください。

# 更新情報
1.0.0　公開
1.1.0　写真レイヤのシンボルをラスタ画像マーカーに設定する
