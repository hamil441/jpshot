package io.github.hamil441.jpshot

import android.Manifest
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionConfig
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.addCallback
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import androidx.core.content.IntentCompat
import androidx.webkit.WebViewAssetLoader
import java.io.File
import java.io.FileInputStream

/**
 * The main JPShot window: the JPShot web app (bundled in assets/web) in a WebView, plus native pieces
 * the web can't do itself — the floating bubble, screenshots, sharing in, camera, voice and clipboard.
 */
class MainActivity : ComponentActivity() {

    companion object {
        private const val TAG = "JPShot"
        const val HOST = "appassets.androidplatform.net"
        private const val START = "https://$HOST/assets/web/index.html"

        fun shotDir(ctx: android.content.Context) = File(ctx.cacheDir, "shots").apply { mkdirs() }
        fun shotUrl(name: String) = "https://$HOST/native/$name"
    }

    private lateinit var web: WebView
    private lateinit var speech: Speech

    @Volatile private var pendingShot: String? = null
    @Volatile private var pendingText: String? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var cameraUri: Uri? = null
    private var pendingPermission: PermissionRequest? = null
    private var askedNotifications = false

    // -- activity results -----------------------------------------------------------------------
    private val projectionLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        val data = r.data
        if (r.resultCode == RESULT_OK && data != null) {
            BubbleService.start(this, r.resultCode, data)
            toast("Bubble on. Tap it whenever you get stuck; long-press it to close.")
            moveTaskToBack(true)
        } else {
            toast("Screen capture wasn't allowed, so the bubble can't take screenshots")
        }
    }
    private val overlayLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (Settings.canDrawOverlays(this)) askProjection()
        else toast("JPShot needs “Display over other apps” to show the bubble")
    }
    private val notificationLauncher = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        askOverlayThenProjection()
    }
    private val pickMedia = registerForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        deliverFile(if (uri != null) arrayOf(uri) else null)
    }
    private val pickAny = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        deliverFile(WebChromeClient.FileChooserParams.parseResult(r.resultCode, r.data))
    }
    private val takePicture = registerForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val uri = cameraUri
        deliverFile(if (ok && uri != null) arrayOf(uri) else null)
    }
    private val micLauncher = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        val req = pendingPermission ?: return@registerForActivityResult
        pendingPermission = null
        if (granted) req.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE)) else req.deny()
    }

    // -- lifecycle ------------------------------------------------------------------------------
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WebView.setWebContentsDebuggingEnabled(true)   // chrome://inspect on a computer, for debugging
        speech = Speech(this) { js("window.__jpshotSpeechDone && window.__jpshotSpeechDone()") }

        val loader = WebViewAssetLoader.Builder()
            .setDomain(HOST)
            .addPathHandler("/assets/web/vendor/kuromoji/dict/", GzipAssets())   // must come before /assets/
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .addPathHandler("/native/", ShotFiles())
            .build()

        web = WebView(this)
        setContentView(web)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            @Suppress("DEPRECATION")
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = false
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_ALWAYS_ALLOW   // AnkiConnect is http://127.0.0.1
            allowFileAccess = false
        }
        web.addJavascriptInterface(Bridge(), "JPShotAndroid")
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                loader.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (url.host == HOST) return false
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, url))
                } catch (e: Exception) {
                    toast("No app can open that link")
                }
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                notifyWeb()
            }
        }
        web.webChromeClient = Chrome()

        onBackPressedDispatcher.addCallback(this) {
            if (web.canGoBack()) web.goBack() else moveTaskToBack(true)
        }

        if (savedInstanceState == null) web.loadUrl(START) else web.restoreState(savedInstanceState)
        handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onDestroy() {
        speech.shutdown()
        web.destroy()
        super.onDestroy()
    }

    // -- screenshots and shares coming in --------------------------------------------------------
    private fun handleIntent(intent: Intent?) {
        when (intent?.action) {
            BubbleService.ACTION_SHOT -> intent.getStringExtra("file")?.let { offerShot(it) }
            Intent.ACTION_SEND -> {
                val uri = IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)
                if (uri != null) {
                    copyToShots(uri, "shared")?.let { offerShot(it) } ?: toast("Couldn't open the shared image")
                } else {
                    intent.getStringExtra(Intent.EXTRA_TEXT)?.let { pendingText = it; notifyWeb() }
                }
            }
        }
    }

    private fun offerShot(name: String) {
        pendingShot = shotUrl(name)
        notifyWeb()
    }

    /** Tell the web app something is waiting (it also checks by itself when it starts). */
    private fun notifyWeb() {
        if (pendingShot != null || pendingText != null) js("window.jpshotNativeInbox && window.jpshotNativeInbox()")
    }

    private fun js(code: String) {
        runOnUiThread { if (::web.isInitialized) web.evaluateJavascript(code, null) }
    }

    private fun copyToShots(uri: Uri, prefix: String): String? = try {
        val name = "$prefix-${System.currentTimeMillis()}.img"
        contentResolver.openInputStream(uri)?.use { input ->
            File(shotDir(this), name).outputStream().use { input.copyTo(it) }
        } ?: throw IllegalStateException("no data")
        cleanOldShots(keep = name)
        name
    } catch (e: Exception) {
        Log.w(TAG, "copy $uri failed", e)
        null
    }

    private fun cleanOldShots(keep: String) {
        shotDir(this).listFiles()?.filter { it.name != keep && it.lastModified() < System.currentTimeMillis() - 10 * 60_000 }
            ?.forEach { it.delete() }
    }

    /** The tokenizer dictionary is bundled as *.gz.bin (the build would un-gzip *.gz); serve it as *.gz. */
    private inner class GzipAssets : WebViewAssetLoader.PathHandler {
        override fun handle(path: String): WebResourceResponse? = try {
            val stream = assets.open("web/vendor/kuromoji/dict/${path.substringAfterLast('/')}.bin")
            WebResourceResponse("application/octet-stream", null, stream)
        } catch (e: Exception) {
            null
        }
    }

    /** Serves files from cache/shots at https://appassets.androidplatform.net/native/<name>. */
    private inner class ShotFiles : WebViewAssetLoader.PathHandler {
        override fun handle(path: String): WebResourceResponse? {
            val f = File(shotDir(this@MainActivity), path.substringAfterLast('/'))
            if (!f.isFile) return null
            val bytes = f.readBytes()
            val mime = when {
                bytes.size > 3 && bytes[0] == 0x89.toByte() && bytes[1] == 'P'.code.toByte() -> "image/png"
                bytes.size > 3 && bytes[0] == 'R'.code.toByte() && bytes[1] == 'I'.code.toByte() -> "image/webp"
                else -> "image/jpeg"
            }
            return WebResourceResponse(mime, null, FileInputStream(f))
        }
    }

    // -- bubble -----------------------------------------------------------------------------------
    private fun startBubbleFlow() {
        if (Build.VERSION.SDK_INT >= 33 && !askedNotifications &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            askedNotifications = true
            notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            return
        }
        askOverlayThenProjection()
    }

    private fun askOverlayThenProjection() {
        if (!Settings.canDrawOverlays(this)) {
            toast("Turn on “Allow display over other apps” for JPShot, then come back")
            overlayLauncher.launch(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            return
        }
        askProjection()
    }

    private fun askProjection() {
        val mpm = getSystemService(MediaProjectionManager::class.java)
        val intent = if (Build.VERSION.SDK_INT >= 34) {
            mpm.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay())   // whole screen
        } else {
            mpm.createScreenCaptureIntent()
        }
        projectionLauncher.launch(intent)
    }

    // -- file inputs (Camera / Screenshot buttons) and microphone ----------------------------------
    private fun deliverFile(result: Array<Uri>?) {
        val cb = fileCallback ?: return
        fileCallback = null
        cb.onReceiveValue(result)
    }

    private inner class Chrome : WebChromeClient() {
        override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
            fileCallback?.onReceiveValue(null)
            fileCallback = callback
            try {
                if (params.isCaptureEnabled) {
                    val f = File(shotDir(this@MainActivity), "camera-${System.currentTimeMillis()}.jpg")
                    val uri = FileProvider.getUriForFile(this@MainActivity, "$packageName.files", f)
                    cameraUri = uri
                    takePicture.launch(uri)
                } else if (params.acceptTypes.all { it.isBlank() || it.startsWith("image/") }) {
                    pickMedia.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                } else {
                    pickAny.launch(params.createIntent())
                }
            } catch (e: Exception) {
                Log.w(TAG, "file chooser failed", e)
                fileCallback = null
                callback.onReceiveValue(null)
                toast("Couldn't open the picker: ${e.message}")
            }
            return true
        }

        override fun onPermissionRequest(request: PermissionRequest) {
            runOnUiThread {
                if (PermissionRequest.RESOURCE_AUDIO_CAPTURE in request.resources) {
                    if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                        request.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
                    } else {
                        pendingPermission = request
                        micLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    }
                } else {
                    request.deny()
                }
            }
        }
    }

    // -- the bridge the web app calls (window.JPShotAndroid) -------------------------------------
    private inner class Bridge {
        @JavascriptInterface fun takeShot(): String = (pendingShot ?: "").also { pendingShot = null }
        @JavascriptInterface fun takeText(): String = (pendingText ?: "").also { pendingText = null }
        @JavascriptInterface fun startBubble() = runOnUiThread { startBubbleFlow() }
        @JavascriptInterface fun stopBubble() = runOnUiThread { BubbleService.stop(this@MainActivity) }
        @JavascriptInterface fun bubbleRunning(): Boolean = BubbleService.running
        @JavascriptInterface fun hasJapaneseVoice(): Boolean = speech.ready
        @JavascriptInterface fun speak(text: String, rate: Float): Boolean = speech.speak(text, rate)
        @JavascriptInterface fun stopSpeaking() = speech.stop()

        @JavascriptInterface fun clipboardText(): String {
            val cm = getSystemService(ClipboardManager::class.java)
            val item = cm.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0) ?: return ""
            return item.coerceToText(this@MainActivity)?.toString() ?: ""
        }

        @JavascriptInterface fun clipboardImage(): String {
            val cm = getSystemService(ClipboardManager::class.java)
            val clip = cm.primaryClip ?: return ""
            val desc = clip.description
            val isImage = (0 until desc.mimeTypeCount).any { desc.getMimeType(it).startsWith("image/") }
            val uri = clip.takeIf { it.itemCount > 0 }?.getItemAt(0)?.uri ?: return ""
            if (!isImage && contentResolver.getType(uri)?.startsWith("image/") != true) return ""
            return copyToShots(uri, "clip")?.let { shotUrl(it) } ?: ""
        }
    }

    private fun toast(msg: String) = runOnUiThread { Toast.makeText(this, msg, Toast.LENGTH_LONG).show() }
}
