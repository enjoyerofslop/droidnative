package org.nxnative.android;

import android.app.NativeActivity;
import android.os.Bundle;
import android.view.View;

// The game's activity: android.app.NativeActivity (the manifest's android.app.lib_name loads nxloader) that also takes the
// system bars off the screen. Theme.NoTitleBar.Fullscreen hides the status bar only, so on a phone with three-button navigation
// (or the gesture bar) Menu, Home and Back sat over the game's own picture and touch controls. Immersive-sticky hides both; the
// bars come back for a swipe from the edge and slide away again, and the touch controls' insets (Gamepad.onApplyWindowInsets)
// then see the whole screen.
public class GameActivity extends NativeActivity {
    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        immersive();
    }
    @Override public void onWindowFocusChanged(boolean has) {
        super.onWindowFocusChanged(has);
        if (has) immersive();   // the bars return when the app loses focus (the keyboard, a dialog); take them back on return
    }
    void immersive() {
        int f = View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
              | View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION;
        getWindow().getDecorView().setSystemUiVisibility(f);
    }
}
