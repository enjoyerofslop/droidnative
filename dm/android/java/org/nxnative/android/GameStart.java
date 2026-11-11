// A game app's entry activity (build_apk.py --game-app): one game in an app of its own, with that game's name and icon, no launcher. The APK carries the game in
// assets/game/, laid out as the launcher's games/<title ID>/ (build_android_from_nsp.py --game-apk): the rewritten code, the shaders, the font, any DLC, the icon,
// the control data, defaults.txt and game.json, and the RomFS image when the APK can hold it (an APK stays under 4 GB: apksigner reads no ZIP64).
//   First start, and after an update of the app: everything but the RomFS is unpacked to <external files>/games/<title ID>/, where front_android.c looks for a game.
//   The translated shaders come as one stored ZIP, spv.zip, unpacked into spv/ (an APK holds at most 65,535 entries, and a game's shaders are files of their own:
//   droidplay-core issue #169); the host reads them by path there.
//   The RomFS is read where it is, never copied: the APK's own stored entry; else the app's OBB file, Android/obb/<package>/main.<version code>.<package>.obb, which an
//   XAPK installer puts there (build_android_from_nsp.py --xapk); else the <name>.romfs file the player picked once with Android's file picker (kept as a persistable
//   grant). Each is checked for the RomFS image's mark and the size game.json gives before the game starts. It reaches the host as DM_ROMFS=fd:<descriptor>:<offset>:<length> (dm/host/romfs_image.h romfs_image_spec), set in this process's
//   environment before `GameActivity` starts in the same process, so the host reads it at its start; the descriptor stays open for the process's life.
//   defaults.txt (the game language picked when packing) is set the same way, without overriding the environment; env.txt still overrides both (front_android.c).
//   DLC the APK couldn't hold (droidplay-core issue #169) follows the RomFS in that same file, the .romfs or the OBB, as a pack (build_android_from_nsp.py make_game_app
//   says how it is laid out); game.json gives its offset (dlc_at) and the file's whole size (data_bytes). Its images are copied out once into games/<title ID>/aoc/, where
//   front_android.c points DM_AOC_DIR as for a launcher install (the host mounts DLC by path), before the game starts; DLC the APK holds is unpacked with the rest.
//   The host ends the process when its activity is destroyed (front_android.c), so every start of the game comes through here again in a fresh process.
package org.nxnative.android;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.AssetFileDescriptor;
import android.content.res.AssetManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.system.Os;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import org.json.JSONObject;

public class GameStart extends Activity {
    static final String ROMFS = "RomFS.img", PREF_URI = "romfs_uri", SPV_ZIP = "spv.zip";
    static final int PICK = 1;
    String id, name; long romfsBytes, dataBytes, dlcAt; File dir;
    TextView status; TextView choose;

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        JSONObject g;
        try { g = new JSONObject(new String(readAsset("game/game.json"), StandardCharsets.UTF_8)); }
        catch (Exception e) { fail("This app holds no game (assets/game/game.json): " + e); return; }
        id = g.optString("title_id").toUpperCase(Locale.ROOT); name = g.optString("name", id); romfsBytes = g.optLong("romfs_bytes", -1);
        dataBytes = g.optLong("data_bytes", romfsBytes); dlcAt = g.optLong("dlc_at", 0);
        File ext = getExternalFilesDir(null); if (ext == null) ext = getFilesDir();
        dir = new File(ext, "games/" + id);
        layout();
        new Thread(new Runnable() { public void run() { prepare(); } }, "unpack").start();
    }

    // ---------------- the game's files ----------------
    void prepare() {
        try {
            String stamp = Long.toString(getPackageManager().getPackageInfo(getPackageName(), 0).lastUpdateTime);
            File mark = new File(dir, ".unpacked");
            if (!stamp.equals(readFile(mark)) || !new File(dir, "code/main.fixups.tsv").isFile()) unpack(mark, stamp);
            ui(new Runnable() { public void run() { romfs(); } });
        } catch (Exception e) { fail("Couldn't unpack " + name + ": " + e); }
    }

    // assets/game/** except the RomFS → games/<title ID>/, the folders the host reads replaced whole (an update can drop files, as one built without a Vulkan driver drops
    // vk_driver/, 19 MB the host would no longer name); the player's own files there (env.txt, launcher.txt) stay
    void unpack(File mark, String stamp) throws Exception {
        AssetManager am = getAssets(); List<String> files = new ArrayList<>();
        // the packer's list of the files (a lookup per entry would ask the APK's index once for each of tens of thousands of shaders); a walk without one
        try { for (String l : new String(readAsset("game/files.txt"), StandardCharsets.UTF_8).split("\n")) if (!l.isEmpty()) files.add("game/" + l); }
        catch (java.io.FileNotFoundException none) { list(am, "game", files); }
        for (String top : new String[] {"code", "spv", "font", "aoc", "vk_driver"}) rm(new File(dir, top));
        dir.mkdirs(); byte[] buf = new byte[1 << 16]; int n = 0;
        for (String f : files) {
            if (++n % 200 == 1 || n == files.size()) say(String.format(Locale.ROOT, "Preparing %s for its first start… %d of %d files", name, n, files.size()));
            if (f.equals("game/" + SPV_ZIP)) {   // the shaders: one entry, many files
                try (InputStream in = am.open(f, AssetManager.ACCESS_STREAMING)) {
                    unzip(in, new File(dir, "spv"), buf, new Count() { public void at(int k) { say(String.format(Locale.ROOT, "Preparing %s for its first start… %d shaders", name, k)); } });
                }
                continue;
            }
            File out = new File(dir, f.substring("game/".length())); out.getParentFile().mkdirs();
            try (InputStream in = am.open(f, AssetManager.ACCESS_STREAMING); OutputStream o = new FileOutputStream(out)) {
                for (int k; (k = in.read(buf)) > 0; ) o.write(buf, 0, k);
            }
        }
        try (OutputStream o = new FileOutputStream(mark)) { o.write(stamp.getBytes(StandardCharsets.UTF_8)); }
    }

    // A ZIP read as a stream (the packer's spv.zip: stored entries, their sizes in the local headers) → its files under dst, which a name may not leave; → how many.
    // Pure Java, so a JVM runs it against the packer's ZIP (dm/tools/tests/test_android_cli.py). count, when given, hears every 2,000 files
    interface Count { void at(int files); }
    static int unzip(InputStream in, File dst, byte[] buf, Count count) throws IOException {
        int n = 0; String root = dst.getCanonicalPath() + File.separator;
        try (ZipInputStream z = new ZipInputStream(in)) {
            for (ZipEntry e; (e = z.getNextEntry()) != null; ) {
                File out = new File(dst, e.getName());
                if (!out.getCanonicalPath().startsWith(root)) throw new IOException("a file outside the folder: " + e.getName());
                if (e.isDirectory()) { out.mkdirs(); continue; }
                out.getParentFile().mkdirs();
                try (OutputStream o = new FileOutputStream(out)) { for (int k; (k = z.read(buf)) > 0; ) o.write(buf, 0, k); }
                if (++n % 2000 == 0 && count != null) count.at(n);
            }
        }
        return n;
    }

    static void list(AssetManager am, String path, List<String> out) throws Exception {
        String[] kids = am.list(path);
        if (kids == null || kids.length == 0) { if (!path.endsWith("/" + ROMFS)) out.add(path); return; }   // a file (an empty folder lists nothing too: none are packed)
        for (String k : kids) list(am, path + "/" + k, out);
    }

    // ---------------- the RomFS ----------------
    void romfs() {
        try {   // in the APK: a stored (uncompressed) entry, which openFd gives as the APK's descriptor with the entry's offset and length
            AssetFileDescriptor a = getAssets().openFd("game/" + ROMFS);
            int fd = ParcelFileDescriptor.dup(a.getFileDescriptor()).detachFd();
            long off = a.getStartOffset(), len = a.getLength(); a.close();
            start(fd, off, len); return;
        } catch (java.io.FileNotFoundException none) {   // not in the APK: the app's OBB file (an XAPK's), else the file the player picked
        } catch (Exception e) { fail("Couldn't open " + name + "'s data in the app: " + e); return; }
        String obb = null;
        try {
            String file = "main." + getPackageManager().getPackageInfo(getPackageName(), 0).getLongVersionCode() + "." + getPackageName() + ".obb";
            for (File d : getObbDirs()) {
                File f = d == null ? null : new File(d, file);
                if (f == null || !f.isFile()) continue;
                obb = open(ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY), f.getPath());
                if (obb == null) return;
            }
        } catch (Exception e) { obb = "The game data in the app's OBB folder can't be read: " + e.getMessage(); }
        String u = prefs().getString(PREF_URI, null), why = null;
        if (u != null) {
            try { why = open(getContentResolver().openFileDescriptor(Uri.parse(u), "r"), "the file you picked"); }
            catch (SecurityException e) { why = "This app may no longer read the game data you picked before."; }
            catch (Exception e) { why = "The game data you picked before can't be opened: " + e.getMessage(); }
            if (why == null) return;
        }
        if (why != null || obb != null) say((why != null ? why : obb) + "\n\nPick " + dataName() + " again.");
        else say("Pick " + name + "'s game data: the file " + dataName() + " that came with this app (" + gb(dataBytes) + "). Put it anywhere on this device or its SD card first; the app reads it where it is.");
        choose.setVisibility(View.VISIBLE);
    }

    // The game data opened and checked (a RomFS image, in a file of the size this app was packed with), its DLC copied out if it holds any, then the game started;
    // else why not. The copy runs on a thread of its own, and a failure there is shown when it comes
    String open(final ParcelFileDescriptor p, String what) {
        try {
            if (p == null) return "The game data (" + what + ") can't be opened.";
            final long size = p.getStatSize(); byte[] h = new byte[8];
            int got = Os.pread(p.getFileDescriptor(), h, 0, 8, 0);
            if (got != 8 || !new String(h, StandardCharsets.US_ASCII).equals("DMROMFS1")) { p.close(); return "That file (" + what + ") isn't " + name + "'s game data."; }
            if (dataBytes > 0 && size != dataBytes) { p.close(); return String.format(Locale.ROOT, "That file (%s) is %s, but %s's game data is %s: it's another version, or not copied completely.", what, gb(size), name, gb(dataBytes)); }
            final long len = romfsBytes > 0 ? romfsBytes : size;
            if (dlcAt <= 0) { start(p.detachFd(), 0, len); return null; }
            new Thread(new Runnable() { public void run() {
                String why;
                try { why = dlc(p.getFileDescriptor()); } catch (Exception e) { why = "Couldn't copy " + name + "'s DLC out of its game data: " + e.getMessage(); }
                if (why != null) {
                    try { p.close(); } catch (IOException e) { /* closing */ }
                    say(why); ui(new Runnable() { public void run() { choose.setVisibility(View.VISIBLE); } }); return;
                }
                final int fd = p.detachFd();
                ui(new Runnable() { public void run() { try { start(fd, 0, len); } catch (Exception e) { fail("Couldn't start " + name + ": " + e); } } });
            } }, "dlc").start();
            return null;
        } catch (Exception e) { return "The game data (" + what + ") can't be read: " + e.getMessage(); }
    }

    // A DLC pack's first 16 bytes → its image count, or -1 when they aren't a pack's. Its whole header (16 + 24 per image) and the pack's length → each image's
    // {index, offset from the pack's start, length}, or null when one lies outside the pack or past the header. Pure Java, so a JVM runs them against the packer's packs
    // (dm/tools/tests/test_android_cli.py)
    static int dlcCount(byte[] h) {
        if (h.length < 16 || !new String(h, 0, 8, StandardCharsets.US_ASCII).equals("DMAOCPK1")) return -1;
        int n = ByteBuffer.wrap(h).order(ByteOrder.LITTLE_ENDIAN).getInt(8);
        return n >= 0 && n <= 2000 ? n : -1;
    }
    static long[][] dlcRecords(byte[] head, long packBytes) {
        int n = dlcCount(head); if (n < 0 || head.length < 16 + 24 * n) return null;
        ByteBuffer b = ByteBuffer.wrap(head).order(ByteOrder.LITTLE_ENDIAN); long[][] r = new long[n][];
        for (int i = 0; i < n; i++) {
            long idx = b.getInt(16 + 24 * i) & 0xffffffffL, off = b.getLong(24 + 24 * i), len = b.getLong(32 + 24 * i);
            if (idx == 0 || idx > 2000 || off < 16 + 24 * n || len < 0 || off + len > packBytes) return null;
            r[i] = new long[] {idx, off, len};
        }
        return r;
    }

    // The DLC pack at dlcAt in the game data → games/<title ID>/aoc/<index>.img. Skipped when aoc/.pack holds this pack's mark (the file's size and its header's CRC) and
    // every image is there at its size; copied whole otherwise, each image through a .part file. → null, or why not
    String dlc(FileDescriptor fd) throws Exception {
        byte[] h = new byte[16];
        int n = Os.pread(fd, h, 0, 16, dlcAt) == 16 ? dlcCount(h) : -1;
        if (n < 0) return "The game data holds no DLC where this app expects it: pick the file that came with this app.";
        byte[] head = new byte[16 + 24 * n];
        for (int at = 0, k; at < head.length; at += k) if ((k = Os.pread(fd, head, at, head.length - at, dlcAt + at)) <= 0) return "The DLC in the game data can't be read: it ends early.";
        long[][] r = dlcRecords(head, dataBytes - dlcAt);
        if (r == null) return "The DLC in the game data can't be read: an image lies outside it.";
        int[] idx = new int[n]; long[] off = new long[n], len = new long[n]; long total = 0;
        for (int i = 0; i < n; i++) { idx[i] = (int) r[i][0]; off[i] = r[i][1]; len[i] = r[i][2]; total += len[i]; }
        CRC32 c = new CRC32(); c.update(head); String mark = dataBytes + ":" + Long.toHexString(c.getValue());
        File aoc = new File(dir, "aoc"), stamp = new File(aoc, ".pack");
        boolean have = mark.equals(readFile(stamp));
        for (int i = 0; i < n && have; i++) have = new File(aoc, idx[i] + ".img").length() == len[i];
        if (have) return null;
        rm(aoc); aoc.mkdirs();
        if (aoc.getUsableSpace() < total + (64L << 20)) return String.format(Locale.ROOT, "There isn't room on this device to copy %s's DLC out of its game data (%s).", name, gb(total));
        byte[] buf = new byte[4 << 20]; long done = 0, shown = -1;
        for (int i = 0; i < n; i++) {
            File part = new File(aoc, idx[i] + ".img.part");
            try (OutputStream o = new FileOutputStream(part)) {
                for (long pos = dlcAt + off[i], left = len[i]; left > 0; ) {
                    int k = Os.pread(fd, buf, 0, (int) Math.min(buf.length, left), pos);
                    if (k <= 0) throw new IOException("the game data ends early");
                    o.write(buf, 0, k); pos += k; left -= k; done += k;
                    if (done / (64L << 20) != shown) { shown = done / (64L << 20); say(String.format(Locale.ROOT, "Copying %s's DLC for its first start… %s of %s", name, gb(done), gb(total))); }
                }
            }
            if (!part.renameTo(new File(aoc, idx[i] + ".img"))) throw new IOException("can't name " + part);
        }
        try (OutputStream o = new FileOutputStream(stamp)) { o.write(mark.getBytes(StandardCharsets.UTF_8)); }
        return null;
    }

    @Override protected void onActivityResult(int req, int res, Intent data) {
        if (req != PICK || res != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData(); String why;
        try { getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION); } catch (SecurityException e) { /* this start only */ }
        try { why = open(getContentResolver().openFileDescriptor(uri, "r"), "the file you picked"); }
        catch (Exception e) { why = "The file you picked can't be opened: " + e.getMessage(); }
        if (why == null) prefs().edit().putString(PREF_URI, uri.toString()).apply();
        else say(why + "\n\nPick " + dataName() + " again.");
    }

    void start(int fd, long off, long len) throws Exception {
        Os.setenv("DM_ROMFS", "fd:" + fd + ":" + off + ":" + len, true);
        String d = readFile(new File(dir, "defaults.txt"));
        if (d != null) for (String line : d.split("\n")) {
            int eq = line.indexOf('='); if (line.startsWith("#") || eq <= 0) continue;
            Os.setenv(line.substring(0, eq).trim(), line.substring(eq + 1).trim(), false);
        }
        startActivity(new Intent(this, org.nxnative.android.GameActivity.class)); overridePendingTransition(0, 0);
        finish();
    }

    // ---------------- the screen ----------------
    void layout() {
        getWindow().getDecorView().setBackgroundColor(Launcher.INK);
        LinearLayout col = new LinearLayout(this); col.setOrientation(LinearLayout.VERTICAL); col.setGravity(Gravity.CENTER); col.setPadding(px(48), px(24), px(48), px(24));
        Bitmap icon = BitmapFactory.decodeFile(new File(dir, "icon.jpg").getPath());
        if (icon == null) try { byte[] j = readAsset("game/icon.jpg"); icon = BitmapFactory.decodeByteArray(j, 0, j.length); } catch (Exception e) { /* no icon */ }
        if (icon != null) { ImageView iv = new ImageView(this); iv.setImageBitmap(icon); iv.setClipToOutline(true); col.addView(iv, new LinearLayout.LayoutParams(px(120), px(120))); }
        TextView t = text(name, 22, Launcher.TEXT); t.setTypeface(Typeface.create("sans-serif", Typeface.BOLD)); t.setPadding(0, px(16), 0, px(8)); col.addView(t);
        status = text("Starting…", 14, Launcher.TEXT2); status.setMaxWidth(px(560)); col.addView(status);
        choose = text("Choose the game data…", 16, Launcher.INK); choose.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        choose.setPadding(px(22), px(10), px(22), px(10)); choose.setBackgroundColor(Launcher.CREAM); choose.setVisibility(View.GONE);
        choose.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
            startActivityForResult(i, PICK);
        } });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT); lp.topMargin = px(20);
        col.addView(choose, lp);
        setContentView(col);
    }

    TextView text(String s, int sp, int color) {
        TextView t = new TextView(this); t.setText(s); t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp); t.setTextColor(color); t.setGravity(Gravity.CENTER); return t;
    }
    void say(final String s) { ui(new Runnable() { public void run() { status.setText(s); } }); }
    void fail(String s) { say(s); android.util.Log.e("DroidPlay", s); }
    void ui(Runnable r) { if (android.os.Looper.myLooper() == android.os.Looper.getMainLooper()) r.run(); else runOnUiThread(r); }
    int px(int dp) { return Math.round(dp * getResources().getDisplayMetrics().density); }
    SharedPreferences prefs() { return getSharedPreferences("game", MODE_PRIVATE); }
    String dataName() { return name.replaceAll("[/\\\\:*?\"<>|]", "").trim() + ".romfs"; }
    static String gb(long b) { return b < 0 ? "its size unknown" : String.format(Locale.ROOT, "%.1f GB", b / 1e9); }

    byte[] readAsset(String path) throws Exception {
        try (InputStream in = getAssets().open(path)) { java.io.ByteArrayOutputStream o = new java.io.ByteArrayOutputStream(); byte[] buf = new byte[8192]; for (int k; (k = in.read(buf)) > 0; ) o.write(buf, 0, k); return o.toByteArray(); }
    }
    static String readFile(File f) {
        try (InputStream in = new java.io.FileInputStream(f)) { byte[] b = new byte[(int) Math.min(f.length(), 1 << 20)]; int n = in.read(b); return n < 0 ? "" : new String(b, 0, n, StandardCharsets.UTF_8); }
        catch (Exception e) { return null; }
    }
    static void rm(File f) {
        File[] kids = f.listFiles(); if (kids != null) for (File k : kids) rm(k);
        f.delete();
    }
}
