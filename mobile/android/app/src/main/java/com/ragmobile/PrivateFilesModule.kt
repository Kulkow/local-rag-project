package com.ragmobile

import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import java.io.File
import java.util.UUID
import java.util.concurrent.Executors

/** UUIDs and cleanup limited to the app's private photo cache. */
class PrivateFilesModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private val executor = Executors.newSingleThreadExecutor()
  private val directory: File get() = File(context.cacheDir, "rag-photos").apply { mkdirs() }

  override fun getName() = "PrivateFiles"

  @ReactMethod
  fun newId(promise: Promise) { promise.resolve(UUID.randomUUID().toString()) }

  @ReactMethod
  fun clearPhotos(promise: Promise) {
    executor.execute {
      try {
        directory.listFiles()?.forEach { if (!it.delete()) error("Cannot remove cached photo") }
        promise.resolve(null)
      } catch (error: Exception) { promise.reject("cache_cleanup", "Не удалось удалить временные снимки", error) }
    }
  }

  override fun invalidate() {
    executor.shutdown()
    super.invalidate()
  }
}
