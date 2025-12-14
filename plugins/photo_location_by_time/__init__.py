# -*- coding: utf-8 -*-
def classFactory(iface):
    from .photo_location_by_time import PhotoLocationByTime
    return PhotoLocationByTime(iface)
