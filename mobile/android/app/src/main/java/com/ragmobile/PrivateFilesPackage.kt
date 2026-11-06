package com.ragmobile

import com.facebook.react.ReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.uimanager.ViewManager

class PrivateFilesPackage : ReactPackage {
  override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(PrivateFilesModule(context))
  override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}
