// The Save rows of a game's settings screen (Launcher.java): Export save writes the game's save as a ZIP, Import save takes one from a ZIP or a folder, Earlier
// saves puts back a save kept before an import or by Back up saves. Through Android's file picker (the Storage Access Framework), so the player picks where a save
// goes or comes from (Downloads, a cloud drive, an SD card) and the app needs no storage permission. Saves.java finds the save and swaps it in; this file is the
// screens and the copying to and from the picker.
//   Import: a ZIP is copied to the cache first (ZipFile reads its central directory, which a stream can't), a folder walked through DocumentsContract; either is
//   staged in internal files/import-staging/, Saves.find looks for saves there, the player picks one when there are several and confirms what it is. The game's
//   save is then copied to <external files>/backups/<time>-<title ID>/ (a backup as Back up saves writes one, so the desktop app's backup copies it too) and the new
//   one swapped in. Never while the game runs: its host would commit its own save over the new one, so the player is asked to close it first.
package org.nxnative.android;

import android.app.AlertDialog;
import android.content.ContentResolver;
import android.content.DialogInterface;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;
import android.provider.DocumentsContract.Document;
import android.provider.OpenableColumns;
import android.system.Os;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.text.DateFormat;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;

final class LauncherSaves {
    static final int EXPORT = 21, IMPORT_FILE = 22, IMPORT_FOLDER = 23;
    static final int DIALOG = android.R.style.Theme_DeviceDefault_Dialog_Alert;
    static final String PREF = "save_for";   // the game a picker was opened for: the launcher may be recreated while the picker is up
    // the user namespace alone (the host's guest names, plat_android.c xname): a file's security.selinux names this app's own categories, which an import from
    // another phone or app must not carry
    static final Saves.Xattrs XA = new Saves.Xattrs() {
        public void read(File f, String rel, StringBuilder tsv) {
            try { for (String n : Os.listxattr(f.getPath())) if (n.startsWith("user.")) tsv.append(rel).append('\t').append(n).append('\t').append(Launcher.hex(Os.getxattr(f.getPath(), n))).append('\n'); }
            catch (Exception e) { /* a file system without xattrs */ }
        }
        public void apply(File root, String top, File tsv) { Launcher.applyXattrs(root, top, Launcher.readXattrs(tsv)); }
    };
    final Launcher l; volatile boolean busy; AlertDialog progress;
    File source; boolean computer;   // what the save on show came in (the staging folder, or an import/<title ID> folder), deleted when its dialogs end; whether a computer sent it
    LauncherSaves(Launcher l) { this.l = l; }

    File saves() { return new File(l.internal, "saves"); }
    File backups() { return new File(l.ext, "backups"); }
    File staging() { return new File(l.internal, "import-staging"); }
    ContentResolver cr() { return l.getContentResolver(); }
    boolean hasSave(String id) { return Saves.hasFiles(new File(saves(), id)) || Saves.hasFiles(new File(saves(), id + "_device")); }

    // ---------------- the rows ----------------
    View rows(final Launcher.Game g) {
        LinearLayout box = new LinearLayout(l); box.setOrientation(LinearLayout.VERTICAL);
        TextView h = l.caps("Save"); h.setPadding(0, l.px(18), 0, l.px(6)); box.addView(h);
        box.addView(row("Export save", "A zip of the save, to keep, or to take to another phone or an emulator.", "Export…", new Runnable() { public void run() { export(g); } }));
        box.addView(row("Import save", "From a zip or a folder: a DroidPlay export, Ryujinx's or a yuzu-family emulator's save folder, JKSV, EdiZon, Checkpoint, or a PC "
            + "port's. The save here is kept first.", "Import…", new Runnable() { public void run() { importAsk(g); } }));
        box.addView(row("Earlier saves", "The saves kept before an import, and Back up saves' copies.", "Restore…", new Runnable() { public void run() { restoreAsk(g); } }));
        return box;
    }
    View row(String label, String note, String button, final Runnable go) {
        LinearLayout r = new LinearLayout(l); r.setGravity(Gravity.CENTER_VERTICAL); r.setMinimumHeight(l.px(48)); r.setPadding(0, l.px(6), 0, l.px(6));
        LinearLayout words = new LinearLayout(l); words.setOrientation(LinearLayout.VERTICAL);
        words.addView(l.text(label, 14, Launcher.TEXT, 400));
        TextView t = l.text(note, 11, Launcher.TEXT2, 400); t.setPadding(0, l.px(2), l.px(12), 0); t.setLineSpacing(0, 1.2f); words.addView(t);
        r.addView(words, new LinearLayout.LayoutParams(0, -2, 1));
        TextView b = l.pill(button, Launcher.LIFT, Launcher.TEXT);
        b.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { if (!busy) go.run(); } });
        r.addView(b, new LinearLayout.LayoutParams(-2, l.px(36)));
        return r;
    }

    // The game closed first when it is running, after asking, then go: its host commits its save at its own times and would put it back over the new one
    void whenClosed(final Launcher.Game g, String doing, final Runnable go) {
        String running = l.runningGame();
        if (running == null || !running.equalsIgnoreCase(g.id)) { go.run(); return; }
        new AlertDialog.Builder(l, DIALOG).setTitle(g.name + " is running")
            .setMessage("Close it to " + doing + "? Progress it has not saved is lost.")
            .setPositiveButton("Close it", new DialogInterface.OnClickListener() { public void onClick(DialogInterface d, int w) { l.endGame(); l.ui.postDelayed(go, 600); } })
            .setNegativeButton("Cancel", null).show();
    }
    void pick(Launcher.Game g, Intent i, int req) {
        l.app.edit().putString(PREF, g.id).apply();
        try { l.startActivityForResult(i, req); }
        catch (android.content.ActivityNotFoundException e) { info("No file picker", "This phone has no app that picks files: " + e.getMessage()); }
    }

    // ---------------- export ----------------
    void export(final Launcher.Game g) {
        if (!hasSave(g.id)) { info("No save yet", g.name + " has no save on this phone yet: play it until it saves, then export it."); return; }
        whenClosed(g, "export its save", new Runnable() { public void run() {
            Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/zip")
                .putExtra(Intent.EXTRA_TITLE, fileName(g.name) + " save " + new SimpleDateFormat("yyyy-MM-dd HHmm", Locale.ROOT).format(new Date()) + ".zip");
            pick(g, i, EXPORT);
        } });
    }
    void exportTo(final Launcher.Game g, final Uri uri) {
        working("Exporting " + g.name + "'s save…", new Runnable() { public void run() {
            String readme = "DroidPlay save export: " + g.name + " (" + g.id + ")" + (g.version != null ? ", version " + g.version : "") + ", " + now() + ".\n\n"
                + "saves/" + g.id + "/ holds the save as the game sees it, and saves/" + g.id + "_device/ its device save, for a game that has both. DroidPlay imports this zip "
                + "as it is (the game's screen > Import save). For an emulator, copy the files inside saves/" + g.id + "/ into its save folder for this game.\n"
                + "xattrs.tsv: the files' extended attributes, which DroidPlay puts back.\n";
            try (OutputStream o = cr().openOutputStream(uri, "w")) {
                if (o == null) throw new IOException("the place picked can't be written");
                int n = Saves.export(l.internal, g.id, o, readme, XA);
                Log.i(Launcher.TAG, "save of " + g.id + " exported: " + n + " files to " + uri);
                done("Save exported", String.format(Locale.ROOT, "%s's save (%d files) is in %s.", g.name, n, name(uri)));
            } catch (Exception e) {
                Log.w(Launcher.TAG, "export: " + e);
                try { DocumentsContract.deleteDocument(cr(), uri); } catch (Exception gone) { /* the provider keeps it, or it is gone */ }
                done("Export failed", "The save couldn't be written: " + e.getMessage());
            }
        } });
    }

    // ---------------- import ----------------
    void importAsk(final Launcher.Game g) {
        whenClosed(g, "import a save", new Runnable() { public void run() {
            new AlertDialog.Builder(l, DIALOG).setTitle("Import a save for " + g.name)
                .setItems(new String[] {"From a zip file", "From a folder"}, new DialogInterface.OnClickListener() { public void onClick(DialogInterface d, int w) {
                    if (w == 0) pick(g, new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), IMPORT_FILE);
                    else pick(g, new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE), IMPORT_FOLDER);
                } }).setNegativeButton("Cancel", null).show();
        } });
    }
    void staged(final Launcher.Game g, final Uri uri, final boolean folder) {
        working("Reading what you picked…", new Runnable() { public void run() {
            File st = staging(); Saves.deleteTree(st); st.mkdirs(); String why;
            long limit = Math.min(8L << 30, l.internal.getUsableSpace() / 3);   // the copy here, the copy beside the save, and room left
            try { why = folder ? stageFolder(uri, st, limit) : stageFile(uri, st, limit); }
            catch (Exception e) { Log.w(Launcher.TAG, "import: " + e); why = String.valueOf(e.getMessage()).startsWith("too big") ? "It's bigger than this phone has room for." : "It can't be read: " + e.getMessage(); }
            if (why != null) { Saves.deleteTree(st); done("Nothing imported", why); return; }
            final List<Saves.Found> fs = Saves.find(st, g.id, Saves.names(new File(saves(), g.id)), Saves.names(new File(saves(), g.id + "_device")));
            then(new Runnable() { public void run() { source = staging(); computer = false; choose(g, fs); } });
        } });
    }
    String stageFile(Uri uri, File st, long limit) throws IOException {
        File zip = new File(l.getCacheDir(), "import.zip"); String name = name(uri);
        try {
            try (InputStream in = cr().openInputStream(uri)) { if (in == null) throw new IOException("the file can't be opened"); copy(in, zip, limit); }
            String kind = Saves.kind(Saves.head(zip, 8));
            if (kind == null) return name + " isn't a zip. Pick a zip of the save, or the folder that holds its files (From a folder).";
            if (!kind.equals("zip")) return kind + " archives can't be opened on a phone: unpack " + name + " first (with a file manager app, or on a computer), then import its folder.";
            try { Saves.unzip(zip, st, limit); }
            catch (IOException e) {
                String m = String.valueOf(e.getMessage());
                if (m.startsWith("method ")) return name + " is packed with a compression Android can't unpack (" + (m.equals("method 9") ? "Deflate64, which Windows uses for big zips" : m)
                    + "): unpack it with a file manager app or on a computer, then import its folder.";
                throw e;
            }
            return null;
        } finally { zip.delete(); }
    }
    // The folder picked → st/<its name>/, so that its name (a title ID, a Ryujinx save ID, a dated backup) is there for Saves.find
    String stageFolder(Uri tree, File st, long limit) throws IOException {
        String id = DocumentsContract.getTreeDocumentId(tree);
        String name = name(DocumentsContract.buildDocumentUriUsingTree(tree, id));
        if (name == null || name.isEmpty() || name.contains("/") || name.startsWith(".")) name = "picked";
        long[] left = {limit}; int[] n = {0};
        walk(tree, id, new File(st, name), left, n, 0);
        return n[0] == 0 ? "The folder " + name + " holds no files." : null;
    }
    void walk(Uri tree, String id, File dst, long[] left, int[] n, int depth) throws IOException {
        if (depth > 16) return;
        if (!dst.isDirectory() && !dst.mkdirs()) throw new IOException("can't make " + dst);
        String[] cols = {Document.COLUMN_DOCUMENT_ID, Document.COLUMN_DISPLAY_NAME, Document.COLUMN_MIME_TYPE, Document.COLUMN_LAST_MODIFIED};
        try (Cursor c = cr().query(DocumentsContract.buildChildDocumentsUriUsingTree(tree, id), cols, null, null, null)) {
            if (c == null) throw new IOException("the folder can't be listed");
            while (c.moveToNext()) {
                String kid = c.getString(0), name = c.getString(1), mime = c.getString(2);
                if (name == null || name.isEmpty() || name.equals(".") || name.equals("..") || name.contains("/") || Saves.junk(name)) continue;
                File out = new File(dst, name);
                if (Document.MIME_TYPE_DIR.equals(mime)) { walk(tree, kid, out, left, n, depth + 1); continue; }
                try (InputStream in = cr().openInputStream(DocumentsContract.buildDocumentUriUsingTree(tree, kid))) {
                    if (in == null) throw new IOException(name + " can't be opened");
                    left[0] -= copy(in, out, left[0]);
                }
                if (!c.isNull(3) && c.getLong(3) > 0) out.setLastModified(c.getLong(3));   // the save's own times, for the player to tell saves apart
                if (++n[0] % 50 == 0) say(String.format(Locale.ROOT, "Reading what you picked… %d files", n[0]));
            }
        }
    }

    void choose(final Launcher.Game g, final List<Saves.Found> fs) {
        if (fs.isEmpty()) {
            cleanup();
            info("No save found", "Nothing in " + (computer ? "what your computer sent" : "what you picked") + " looks like a save. Pick the folder that holds the save's files, or a zip of it: for an emulator, the folder its "
                + "\"Open save data location\" opens, or the one above it.");
            return;
        }
        if (fs.size() == 1) { confirm(g, fs.get(0)); return; }
        String[] items = new String[fs.size()];
        for (int i = 0; i < items.length; i++) items[i] = what(fs.get(i)) + "\n" + size(fs.get(i));
        new AlertDialog.Builder(l, DIALOG).setTitle(computer ? "Which save from your computer, for " + g.name + "?" : "Which save?")
            .setItems(items, new DialogInterface.OnClickListener() { public void onClick(DialogInterface d, int w) { confirm(g, fs.get(w)); } })
            .setNegativeButton("Cancel", new DialogInterface.OnClickListener() { public void onClick(DialogInterface d, int w) { cleanup(); } })
            .setCancelable(false).show();
    }
    void confirm(final Launcher.Game g, final Saves.Found f) {
        boolean other = f.titleId != null && !f.titleId.equalsIgnoreCase(g.id);
        StringBuilder m = new StringBuilder(what(f)).append('\n').append(size(f)).append("\nIt holds: ").append(Saves.top(f.main(), 6)).append('\n');
        if (other) m.append("\nThis is the save of another game: ").append(l.nameOf(f.titleId)).append(" (").append(f.titleId).append("). It won't load in ").append(g.name).append(" unless that is the same game from another region.\n");
        else if (f.titleId == null && !f.matched) m.append("\nThese files don't say which game they're from: check that they're ").append(g.name).append("'s.\n");
        if (f.matched) m.append("\nTheir names match ").append(g.name).append("'s save on this phone.\n");
        else if (f.unmatched) m.append("\nThey share no names with ").append(g.name).append("'s save on this phone, which holds ").append(Saves.top(new File(saves(), g.id), 4)).append(".\n");
        if (g.version != null) m.append("\nThe game here is version ").append(g.version).append(": a save from a later update may not load.\n");
        m.append('\n').append(hasSave(g.id) ? "The save " + g.name + " has now is kept first: Earlier saves > Restore puts it back." : g.name + " has no save on this phone yet.");
        new AlertDialog.Builder(l, DIALOG).setTitle(computer ? "Import this save from your computer?" : "Import this save?").setMessage((computer ? "For " + g.name + ": " : "") + m)
            .setPositiveButton(other ? "Import anyway" : "Import", new DialogInterface.OnClickListener() { public void onClick(DialogInterface d, int w) { install(g, f, false); } })
            .setNegativeButton("Cancel", new DialogInterface.OnClickListener() { public void onClick(DialogInterface d, int w) { cleanup(); } })
            .setCancelable(false).show();
    }

    // The game's save kept, then f swapped in. restoring: f is a kept save (Earlier saves), not the staged import
    void install(final Launcher.Game g, final Saves.Found f, final boolean restoring) {
        final String running = l.runningGame();
        if (running != null && running.equalsIgnoreCase(g.id)) {   // started from the desktop app while the picker was up
            if (!restoring) cleanup();
            info("Nothing imported", g.name + " is running: close it, then try again."); return;
        }
        working(restoring ? "Putting the save back…" : "Importing the save…", new Runnable() { public void run() {
            File keep = new File(backups(), new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date()) + "-" + g.id);
            boolean kept;
            try {
                kept = Saves.keep(l.internal, g.id, keep, "DroidPlay save backup: " + g.name + " (" + g.id + ")'s save before " + (restoring ? "a restore" : "an import") + ", " + now()
                    + ".\nThe game's screen in DroidPlay > Earlier saves > Restore puts it back; so does copying this folder to backups/restore/ on the phone.\n", XA);
            } catch (IOException e) {
                Saves.deleteTree(keep); if (!restoring) cleanup();
                done("Nothing imported", "The save " + g.name + " has now couldn't be kept first (" + e.getMessage() + "), so it was left as it is. Free some space and try again.");
                return;
            }
            try {
                Saves.install(l.internal, g.id, f, XA);
                Log.i(Launcher.TAG, "save of " + g.id + (restoring ? " restored from " : " imported from ") + f.format + " " + f.label + " (" + f.files + " files)" + (kept ? "; the one before is in " + keep : ""));
                done(restoring ? "Save restored" : "Save imported", g.name + " starts from it next time: pick Continue, or load it in the game." + (kept ? "\n\nThe save it had is kept: Earlier saves > Restore puts it back." : ""));
            } catch (IOException e) {
                Log.w(Launcher.TAG, "install: " + e);
                done("Import failed", "The save couldn't be swapped in (" + e.getMessage() + ")." + (kept ? " The one " + g.name + " had is kept: Earlier saves > Restore puts it back." : ""));
            } finally { if (!restoring) cleanup(); }
        } });
    }

    // The save's folder gone once its dialogs end. An import/<title ID> folder the app can't delete (adb made it, and its chmod was cut short) is remembered by its
    // time, so it isn't offered at every start
    void cleanup() {
        File f = source; source = null; if (f == null) return;
        Saves.deleteTree(f);
        if (f.exists() && computer) l.app.edit().putLong(SEEN + f.getName(), f.lastModified()).apply();
    }

    // ---------------- from the computer ----------------
    // A save the desktop app or the command line sent (scripts/build_android_from_nsp.py --import-save / --restore-backup): adb can't write the app's internal storage,
    // so it pushes to <external files>/import/<title ID>/, and the launcher takes it at its start and whenever it comes back to the front, with the same dialogs as an
    // import from the picker. One at a time; a game that is running waits until it isn't
    static final String SEEN = "import_seen_";
    void incoming() {
        if (busy || source != null) return;
        File[] ds = new File(l.ext, "import").listFiles(); if (ds == null) return;
        java.util.Arrays.sort(ds);
        String running = l.runningGame();
        for (File d : ds) {
            if (!d.isDirectory() || !d.getName().matches("(?i)0[1-7][0-9a-f]{14}")) continue;
            if (l.app.getLong(SEEN + d.getName(), -1) == d.lastModified()) continue;
            final String id = d.getName().toUpperCase(Locale.ROOT);
            if (id.equalsIgnoreCase(running)) continue;
            Launcher.Game g = null; for (Launcher.Game x : l.scan()) if (x.id.equals(id)) g = x;
            if (g == null) continue;   // the game isn't on the phone (yet)
            Log.i(Launcher.TAG, "a save for " + id + " came from the computer: " + d);
            source = d; computer = true;
            choose(g, Saves.find(d, id, Saves.names(new File(saves(), id)), Saves.names(new File(saves(), id + "_device"))));
            return;
        }
    }

    // ---------------- earlier saves ----------------
    void restoreAsk(final Launcher.Game g) {
        final List<Saves.Found> ks = Saves.kept(backups(), g.id);
        if (ks.isEmpty()) { info("No earlier saves", "No saves of " + g.name + " are kept on this phone. An import keeps the save it replaces, and Back up saves on the games list keeps every game's."); return; }
        whenClosed(g, "put a save back", new Runnable() { public void run() {
            String[] items = new String[ks.size()];
            for (int i = 0; i < items.length; i++) items[i] = what(ks.get(i)) + "\n" + size(ks.get(i));
            new AlertDialog.Builder(l, DIALOG).setTitle("Put back which save?")
                .setItems(items, new DialogInterface.OnClickListener() { public void onClick(DialogInterface d, int w) {
                    final Saves.Found f = ks.get(w);
                    new AlertDialog.Builder(l, DIALOG).setTitle("Put this save back?")
                        .setMessage(what(f) + "\n" + size(f) + "\nIt holds: " + Saves.top(f.main(), 6) + "\n\n" + (hasSave(g.id) ? "The save " + g.name + " has now is kept first." : ""))
                        .setPositiveButton("Put it back", new DialogInterface.OnClickListener() { public void onClick(DialogInterface d2, int w2) { install(g, f, true); } })
                        .setNegativeButton("Cancel", null).show();
                } }).setNegativeButton("Cancel", null).show();
        } });
    }

    // ---------------- results from the pickers ----------------
    boolean result(int req, int res, Intent data) {
        if (req != EXPORT && req != IMPORT_FILE && req != IMPORT_FOLDER) return false;
        if (res != android.app.Activity.RESULT_OK || data == null || data.getData() == null) return true;
        Launcher.Game g = null; String id = l.app.getString(PREF, null);
        for (Launcher.Game x : l.scan()) if (x.id.equalsIgnoreCase(id)) g = x;
        if (g == null) { l.toast("The game " + id + " is no longer on this phone"); return true; }
        if (req == EXPORT) exportTo(g, data.getData()); else staged(g, data.getData(), req == IMPORT_FOLDER);
        return true;
    }

    // ---------------- words ----------------
    static String what(Saves.Found f) {
        String w;
        switch (f.format) {
            case "DroidPlay": w = "A DroidPlay export or backup"; break;
            case "yuzu": w = "A yuzu-family emulator's save (yuzu, Citron, Eden, Sudachi…), " + f.label; break;
            case "Ryujinx": w = "A Ryujinx save folder, " + f.label; break;
            case "JKSV": w = "A JKSV backup, " + f.label; break;
            case "EdiZon": w = "An EdiZon backup, " + f.label; break;
            case "Checkpoint": w = "A Checkpoint backup, " + f.label; break;
            case "kept": w = f.label.matches("\\d{8}-\\d{6}-.+") ? when(f.label) + ", kept when another save was put in" : f.label.matches("\\d{8}-\\d{6}") ? when(f.label) + ", from Back up saves" : f.label; break;
            case "title": w = "A save folder named by its title ID"; break;
            default: w = f.label.isEmpty() ? "A save, the zip's files" : "A save folder, " + f.label;
        }
        return f.device != null && f.account == null && !f.format.equals("kept") ? w + " (device save)" : w;
    }
    static String size(Saves.Found f) {
        return String.format(Locale.ROOT, "%d %s, %s", f.files, f.files == 1 ? "file" : "files", f.bytes < (1 << 20) ? (f.bytes + 1023) / 1024 + " KB" : String.format(Locale.ROOT, "%.1f MB", f.bytes / 1048576.0))
            + (f.newest > 0 ? ", last changed " + DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(new Date(f.newest)) : "");
    }
    static String when(String folder) {   // a backup folder's name, yyyyMMdd-HHmmss[-<title ID>], as a date
        try { return DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).parse(folder.substring(0, Math.min(15, folder.length())))); }
        catch (ParseException e) { return folder; }
    }
    static String now() { return new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.ROOT).format(new Date()); }
    static String fileName(String s) { return s.replaceAll("[/\\\\:*?\"<>|]", "").trim(); }
    String name(Uri uri) {
        try (Cursor c = cr().query(uri, new String[] {OpenableColumns.DISPLAY_NAME}, null, null, null)) { if (c != null && c.moveToFirst()) return c.getString(0); }
        catch (Exception e) { /* a provider without names */ }
        return uri.getLastPathSegment();
    }
    // in → f, at most max bytes. → the bytes copied
    static long copy(InputStream in, File f, long max) throws IOException {
        long n = 0; byte[] b = new byte[1 << 16];
        f.getParentFile().mkdirs();
        try (OutputStream o = new FileOutputStream(f)) { for (int k; (k = in.read(b)) > 0; ) { if ((n += k) > max) throw new IOException("too big"); o.write(b, 0, k); } }
        return n;
    }

    // ---------------- the progress dialog ----------------
    void working(String what, final Runnable bg) {
        busy = true;
        progress = new AlertDialog.Builder(l, DIALOG).setMessage(what).setCancelable(false).show();
        new Thread(new Runnable() { public void run() {
            try { bg.run(); }
            catch (RuntimeException e) { Log.w(Launcher.TAG, "saves: " + e); done("Something went wrong", String.valueOf(e)); }   // the dialog never left up
        } }, "saves").start();
    }
    void say(final String s) { l.runOnUiThread(new Runnable() { public void run() { if (progress != null) progress.setMessage(s); } }); }
    void then(final Runnable r) {
        l.runOnUiThread(new Runnable() { public void run() {
            if (progress != null) { try { progress.dismiss(); } catch (Exception gone) { /* the window went with a recreated activity */ } progress = null; }
            busy = false; r.run();
        } });
    }
    void done(final String title, final String msg) { then(new Runnable() { public void run() { info(title, msg); } }); }
    void info(String title, String msg) { new AlertDialog.Builder(l, DIALOG).setTitle(title).setMessage(msg).setPositiveButton("OK", null).show(); }
}
