[app]
title = Sound Booster
package.name = boost
package.domain = org.new200013
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0.0
requirements = python3,kivy,pyjnius,android,numpy
orientation = portrait
fullscreen = 0
android.api = 33
android.minapi = 24
android.arch = arm64-v8a, armeabi-v7a
android.permissions = RECORD_AUDIO,MODIFY_AUDIO_SETTINGS,POST_NOTIFICATIONS,WAKE_LOCK,FOREGROUND_SERVICE,FOREGROUND_SERVICE_MEDIA_PROJECTION,FOREGROUND_SERVICE_MICROPHONE,INTERNET
android.extra_manifest_application_arguments = android:usesCleartextTraffic="true"
android.accept_sdk_license = True
android.allow_backup = True
