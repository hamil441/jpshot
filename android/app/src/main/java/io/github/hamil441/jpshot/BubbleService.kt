package io.github.hamil441.jpshot

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.DisplayMetrics
import android.util.Log
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.ImageView
import android.widget.Toast
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.IntentCompat
import java.io.File
import java.io.FileOutputStream
import kotlin.math.abs

/**
 * The floating bubble. Holds the screen-capture session (MediaProjection) for as long as the bubble is
 * on; tapping the bubble hides it, grabs the next screen frame, saves it and opens JPShot with it.
 * Drag to move (it snaps to the nearest edge); long-press to close.
 */
class BubbleService : Service() {

    companion object {
        private const val TAG = "JPShotBubble"
        const val ACTION_SHOT = "io.github.hamil441.jpshot.SHOT"
        private const val ACTION_STOP = "io.github.hamil441.jpshot.STOP_BUBBLE"
        private const val CHANNEL = "bubble"
        private const val NOTIFICATION_ID = 7

        @Volatile var running = false
            private set

        fun start(ctx: Context, resultCode: Int, data: Intent) {
            val i = Intent(ctx, BubbleService::class.java).putExtra("code", resultCode).putExtra("data", data)
            ctx.startForegroundService(i)
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, BubbleService::class.java))
        }
    }

    private lateinit var wm: WindowManager
    private val main = Handler(Looper.getMainLooper())
    private var bubble: ImageView? = null
    private var params: WindowManager.LayoutParams? = null

    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private var thread: HandlerThread? = null
    private var bg: Handler? = null
    private var width = 0
    private var height = 0

    // touched only on the capture thread
    private var latest: Image? = null
    private var frames = 0L
    private var wantNext = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        wm = getSystemService(WindowManager::class.java)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        startInForeground()
        if (projection == null) {
            val code = intent?.getIntExtra("code", 0) ?: 0
            val data = intent?.let { IntentCompat.getParcelableExtra(it, "data", Intent::class.java) }
            if (data == null) {
                stopSelf()
                return START_NOT_STICKY
            }
            try {
                val mpm = getSystemService(MediaProjectionManager::class.java)
                val p = mpm.getMediaProjection(code, data) ?: throw IllegalStateException("no projection")
                p.registerCallback(object : MediaProjection.Callback() {
                    override fun onStop() {
                        main.post { stopSelf() }
                    }
                }, main)
                projection = p
                thread = HandlerThread("jpshot-capture").also { it.start() }
                bg = Handler(thread!!.looper)
                createDisplay()
                showBubble()
                running = true
                Log.i(TAG, "bubble on, capturing ${width}x$height")
            } catch (e: Exception) {
                Log.e(TAG, "couldn't start screen capture", e)
                toast("Couldn't start screen capture: ${e.message}")
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        running = false
        bubble?.let { runCatching { wm.removeView(it) } }
        bubble = null
        runCatching { display?.release() }
        runCatching { projection?.stop() }
        val b = bg
        val t = thread
        if (b != null && t != null) {
            b.post {
                latest?.close()
                latest = null
                runCatching { reader?.close() }
                t.quitSafely()
            }
        }
        super.onDestroy()
    }

    // -- notification (required while capturing the screen) -------------------------------------
    private fun startInForeground() {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "Capture bubble", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Shown while the JPShot bubble is on"
                setShowBadge(false)
            })
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stop = PendingIntent.getService(this, 1, Intent(this, BubbleService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("JPShot bubble is on")
            .setContentText("Tap the bubble to read the screen · long-press it to close")
            .setContentIntent(open)
            .addAction(0, "Turn off", stop)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
        ServiceCompat.startForeground(this, NOTIFICATION_ID, n,
            if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION else 0)
    }

    // -- screen capture ------------------------------------------------------------------------
    private fun screenSize(): Triple<Int, Int, Int> {
        val dpi = resources.displayMetrics.densityDpi
        return if (Build.VERSION.SDK_INT >= 30) {
            val b = wm.maximumWindowMetrics.bounds
            Triple(b.width(), b.height(), dpi)
        } else {
            val dm = DisplayMetrics()
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getRealMetrics(dm)
            Triple(dm.widthPixels, dm.heightPixels, dpi)
        }
    }

    /** (Re)create the frame reader at the current screen size; the virtual display is created once. */
    private fun createDisplay() {
        val (w, h, dpi) = screenSize()
        width = w
        height = h
        val old = reader
        val r = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 3)
        r.setOnImageAvailableListener({ onFrame(it) }, bg)
        reader = r
        val d = display
        if (d == null) {
            display = projection!!.createVirtualDisplay("jpshot", w, h, dpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, r.surface, null, bg)
        } else {
            d.resize(w, h, dpi)
            d.surface = r.surface
        }
        if (old != null) bg?.post {
            latest?.close()
            latest = null
            runCatching { old.close() }
        }
    }

    /** Keep only the newest frame; if a capture is waiting for a fresh frame, use this one. */
    private fun onFrame(r: ImageReader) {
        val img = try {
            r.acquireLatestImage()
        } catch (e: Exception) {
            null
        } ?: return
        if (r !== reader) {
            img.close()
            return
        }
        latest?.close()
        latest = img
        frames++
        if (wantNext) {
            wantNext = false
            deliverLatest()
        }
    }

    private fun capture() {
        val (w, h, _) = screenSize()
        if (w != width || h != height) createDisplay()   // rotated since the bubble started
        val b = bubble ?: return
        b.visibility = View.INVISIBLE
        val handler = bg ?: return
        handler.post {
            val before = frames
            // give the screen time to redraw without the bubble, then use the newest frame
            handler.postDelayed({
                if (frames > before && latest != null) deliverLatest() else wantNext = true
            }, 220)
            handler.postDelayed({
                if (wantNext) {
                    wantNext = false
                    if (latest != null) deliverLatest() else main.post {
                        bubble?.visibility = View.VISIBLE
                        toast("Couldn't grab the screen. Try again")
                    }
                }
            }, 1500)
        }
    }

    /** On the capture thread: save the newest frame and open JPShot with it. */
    private fun deliverLatest() {
        val img = latest ?: return
        latest = null
        val name = try {
            val bmp = toBitmap(img)
            val dir = MainActivity.shotDir(this)
            dir.listFiles()?.filter { it.name.startsWith("bubble-") }?.forEach { it.delete() }
            val fileName = "bubble-${System.currentTimeMillis()}.jpg"
            FileOutputStream(File(dir, fileName)).use { bmp.compress(Bitmap.CompressFormat.JPEG, 92, it) }
            bmp.recycle()
            fileName
        } catch (e: Exception) {
            Log.e(TAG, "saving the screenshot failed", e)
            null
        } finally {
            img.close()
        }
        main.post {
            bubble?.visibility = View.VISIBLE
            if (name == null) {
                toast("Couldn't save the screenshot")
                return@post
            }
            val open = Intent(this, MainActivity::class.java)
                .setAction(ACTION_SHOT)
                .putExtra("file", name)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            startActivity(open)
        }
    }

    private fun toBitmap(img: Image): Bitmap {
        val plane = img.planes[0]
        val pixelStride = plane.pixelStride
        val rowPadding = plane.rowStride - pixelStride * img.width
        val padded = Bitmap.createBitmap(img.width + rowPadding / pixelStride, img.height, Bitmap.Config.ARGB_8888)
        padded.copyPixelsFromBuffer(plane.buffer)
        if (rowPadding == 0) return padded
        val exact = Bitmap.createBitmap(padded, 0, 0, img.width, img.height)
        padded.recycle()
        return exact
    }

    // -- the bubble view -------------------------------------------------------------------------
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    @SuppressLint("ClickableViewAccessibility")
    private fun showBubble() {
        val size = dp(56)
        val prefs = getSharedPreferences("bubble", MODE_PRIVATE)
        val (w, h, _) = screenSize()
        val p = WindowManager.LayoutParams(
            size, size,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = prefs.getInt("x", w - size - dp(4)).coerceIn(0, w - size)
            y = prefs.getInt("y", h / 3).coerceIn(0, h - size)
        }
        val v = ImageView(this).apply {
            setImageResource(R.drawable.bubble)
            contentDescription = "JPShot: read the screen"
            alpha = 0.92f
        }
        val slop = ViewConfiguration.get(this).scaledTouchSlop
        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0
        var dragging = false
        var longFired = false
        val longPress = Runnable {
            longFired = true
            vibrate()
            toast("Bubble closed. Turn it on again from JPShot.")
            stopSelf()
        }
        v.setOnTouchListener { _, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX; downY = e.rawY; startX = p.x; startY = p.y
                    dragging = false; longFired = false
                    main.postDelayed(longPress, 700)
                    v.alpha = 1f
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!dragging && (abs(dx) > slop || abs(dy) > slop)) {
                        dragging = true
                        main.removeCallbacks(longPress)
                    }
                    if (dragging) {
                        p.x = (startX + dx).toInt()
                        p.y = (startY + dy).toInt()
                        runCatching { wm.updateViewLayout(v, p) }
                    }
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    main.removeCallbacks(longPress)
                    v.alpha = 0.92f
                    if (longFired) return@setOnTouchListener true
                    if (dragging) {
                        val (sw, sh, _) = screenSize()
                        p.x = if (p.x + size / 2 < sw / 2) 0 else sw - size     // snap to the nearest edge
                        p.y = p.y.coerceIn(0, sh - size)
                        runCatching { wm.updateViewLayout(v, p) }
                        prefs.edit().putInt("x", p.x).putInt("y", p.y).apply()
                    } else if (e.actionMasked == MotionEvent.ACTION_UP) {
                        capture()
                    }
                }
            }
            true
        }
        wm.addView(v, p)
        bubble = v
        params = p
    }

    private fun vibrate() {
        val vib = getSystemService(Vibrator::class.java) ?: return
        if (Build.VERSION.SDK_INT >= 26) vib.vibrate(VibrationEffect.createOneShot(30, VibrationEffect.DEFAULT_AMPLITUDE))
    }

    private fun toast(msg: String) = main.post { Toast.makeText(this, msg, Toast.LENGTH_LONG).show() }
}
