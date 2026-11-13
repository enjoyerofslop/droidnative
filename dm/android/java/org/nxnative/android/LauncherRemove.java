// The Remove game row of a game's settings screen (Launcher.java), and the same from a game the installed app has no host for: deletes the game's files from the phone
// after saying what goes and how much space it frees, and keeps its save. Removal.java finds and deletes the files; this file is the row and the dialogs, with
// LauncherSaves' row, progress dialog and busy flag, so a removal and a save's copy never run at once (nor Play during either). Never while the game runs: its host
// reads those files and writes its pipeline cache back, so the player is asked to close it first, and the game is looked for again just before anything goes.
//   A game app (a game packed as an app of its own, GameStart.java) has no folder in this app: it is removed as any app is, by uninstalling it (docs/android.md).
package org.nxnative.android;

import android.app.AlertDialog;
import android.content.DialogInterface;
import android.util.Log;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

final class LauncherRemove {
    final Launcher l;
    LauncherRemove(Launcher l) { this.l = l; }
    LauncherSaves s() { return l.saves; }

    View rows(final Launcher.Game g) {
        LinearLayout box = new LinearLayout(l); box.setOrientation(LinearLayout.VERTICAL);
        TextView h = l.caps("Remove"); h.setPadding(0, l.px(18), 0, l.px(6)); box.addView(h);
        box.addView(s().row("Remove game", "Deletes the game from this phone to free its space. Its save stays, for when you install it again.", "Remove…",
            new Runnable() { public void run() { ask(g); } }));
        return box;
    }

    // The game closed first when it runs (after asking), then its files added up off the UI thread (a game's shaders are tens of thousands of files), then the prompt
    void ask(final Launcher.Game g) {
        if (s().busy) return;
        s().whenClosed(g, "remove it", new Runnable() { public void run() {
            s().working("Adding up what " + g.name + " takes…", new Runnable() { public void run() {
                final Removal r = new Removal(g.dir, l.internal, g.id);
                s().then(new Runnable() { public void run() { confirm(g, r); } });
            } });
        } });
    }

    void confirm(final Launcher.Game g, final Removal r) {
        final boolean saved = s().hasSave(g.id);
        StringBuilder m = new StringBuilder(g.name).append("'s code, shaders and game data are deleted from this phone, freeing ").append(Removal.size(r.bytes())).append('.');
        if (r.romfs != null && r.romfsThere) m.append(" That includes its game data ").append(Removal.where(r.romfs)).append('.');
        else if (r.romfs != null) m.append("\n\nIts game data was copied to ").append(r.romfs.getParent()).append(", which can't be seen now (the SD card taken out?), so it stays there: delete it yourself.");
        m.append("\n\n").append(saved ? "Its save stays on this phone, and is there again when you install the game again." : "It has no save on this phone to keep.");
        m.append("\n\nThis can't be undone: to play it again, install it again from your computer.");
        AlertDialog.Builder b = new AlertDialog.Builder(l, LauncherSaves.DIALOG).setTitle("Remove " + g.name + "?").setMessage(m)
            .setPositiveButton("Remove", new DialogInterface.OnClickListener() { public void onClick(DialogInterface d, int w) { remove(g, r, saved); } })
            .setNegativeButton("Cancel", null);
        if (saved) b.setNeutralButton("Export save first", new DialogInterface.OnClickListener() { public void onClick(DialogInterface d, int w) { s().export(g); } });
        b.show();
    }

    void remove(final Launcher.Game g, final Removal r, final boolean saved) {
        String running = l.runningGame();
        if (running != null && running.equalsIgnoreCase(g.id)) { s().info("Nothing removed", g.name + " is running: close it, then try again."); return; }   // started from the computer meanwhile
        s().working("Removing " + g.name + "…", new Runnable() { public void run() {
            final Removal.Tally t = r.remove();
            Log.i(Launcher.TAG, "launcher: removed " + g.id + " (" + g.dir + (r.romfs != null ? ", " + r.romfs : "") + ", cache/" + r.id + "): " + t.freed + " bytes freed"
                + (t.left > 0 ? ", " + t.left + " files or folders left, first " + t.leftAt : "") + "; the save stays");
            s().then(new Runnable() { public void run() {
                l.showGames();
                if (t.left == 0) l.toast(g.name + " removed: " + Removal.size(t.freed) + " freed." + (saved ? " Its save stays." : ""));
                else s().info("Some files stayed", g.name + " is off the games list and " + Removal.size(t.freed) + " is freed, but some of its files couldn't be deleted, such as "
                    + t.leftAt + ". Delete them from a computer with adb shell rm -r.");
            } });
        } });
    }
}
