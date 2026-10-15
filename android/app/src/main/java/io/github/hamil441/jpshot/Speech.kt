package io.github.hamil441.jpshot

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale

/** The phone's own Japanese text-to-speech (Android WebView has no speechSynthesis). */
class Speech(context: Context, private val onDone: () -> Unit) : TextToSpeech.OnInitListener {
    private val main = Handler(Looper.getMainLooper())
    private val tts = TextToSpeech(context.applicationContext, this)

    @Volatile var ready = false
        private set

    override fun onInit(status: Int) {
        if (status != TextToSpeech.SUCCESS) return
        val r = tts.setLanguage(Locale.JAPAN)
        ready = r != TextToSpeech.LANG_MISSING_DATA && r != TextToSpeech.LANG_NOT_SUPPORTED
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) {
                main.post { onDone() }
            }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) {
                main.post { onDone() }
            }
        })
    }

    fun speak(text: String, rate: Float): Boolean {
        if (!ready) return false
        tts.setSpeechRate(rate)
        return tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "jpshot-${System.nanoTime()}") == TextToSpeech.SUCCESS
    }

    fun stop() {
        if (ready) tts.stop()
    }

    fun shutdown() = tts.shutdown()
}
