// Removing a game from the phone, for the Remove game row of a game's settings screen (LauncherRemove.java), in plain Java (java.io, java.nio.file) so that a JVM runs
// it in dm/tools/tests/test_android_remove.py. What a launcher install of a game put on the phone, and so what goes:
//   <external files>/games/<title ID>/   the game: code, shaders, font, the RomFS image or folder, DLC (aoc/), icon, control data, defaults.txt, game.json, launcher.txt,
//                                         the host's glslc_capture/ and vk_start.txt (build_android_from_nsp.py push_game, front_android.c)
//   <internal files>/cache/<title ID>/   the drivers' pipeline caches and their lists of pipelines (front_android.c DM_PIPELINE_CACHE)
//   <folder>/<title ID>/RomFS.img        the RomFS image of an install with --romfs-dir (sd: the SD card's Android/data/org.nxnative.android/files/romfs), which the
//                                         game's defaults.txt names as DM_ROMFS (build_android_from_nsp.py romfs_path), with what a copy cut short left beside it
// The saves stay (internal saves/<title ID> and <title ID>_device, and backups/), and so do the game's settings: an install of the game again finds them.
// The game's folder is first renamed to games/.removing-<title ID>, which the games list skips, so a removal cut short (the app killed) leaves no half game in the
// list; sweep() finishes such a folder at the launcher's next start. Symbolic links are deleted, never followed.
package org.nxnative.android;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Locale;
import java.util.regex.Pattern;

final class Removal {
    static final Pattern ID = Pattern.compile("[0-9A-Fa-f]{16}");
    static final String PREFIX = ".removing-";
    static final String[] ROMFS_FILES = {"RomFS.img", "RomFS.img.partial", "RomFS.img.piece"};   // the image, and push_resumable's pieces of a copy cut short
    final String id; final File game, cache;
    final File romfs;          // the RomFS image in a folder of its own (--romfs-dir), or null: none, or the game's folder holds it
    final boolean romfsThere;  // whether that image can be seen now (an SD card taken out: not)
    final long gameBytes, cacheBytes, romfsBytes;

    // game: the game's folder under games/; internal: the app's internal files
    Removal(File game, File internal, String id) {
        if (!ID.matcher(id).matches()) throw new IllegalArgumentException("not a title ID: " + id);
        this.id = id.toUpperCase(Locale.ROOT); this.game = game; cache = new File(internal, "cache/" + this.id);
        romfs = elsewhere(game, this.id); romfsThere = romfs != null && romfs.isFile();
        gameBytes = size(game); cacheBytes = size(cache);
        long r = 0; if (romfs != null) for (String n : ROMFS_FILES) r += size(new File(romfs.getParentFile(), n));
        romfsBytes = r;
    }
    long bytes() { return gameBytes + cacheBytes + romfsBytes; }

    // defaults.txt's DM_ROMFS when it is the packing script's <folder>/<title ID>/RomFS.img outside the game's folder. Anything else it may name (fd:, a file of
    // another name, a folder not named after this game) isn't the install's to delete
    static File elsewhere(File game, String id) {
        String v = null;
        try {
            for (String line : new String(Files.readAllBytes(new File(game, "defaults.txt").toPath()), StandardCharsets.UTF_8).split("\r?\n"))
                if (v == null && line.startsWith("DM_ROMFS=")) v = line.substring(9);   // the first one, as the host takes it (front_android.c env_file)
        } catch (IOException e) { return null; }
        if (v == null || !v.startsWith("/")) return null;
        File f = canonical(new File(v)), dir = f.getParentFile();
        if (!f.getName().equals("RomFS.img") || dir == null || !dir.getName().equalsIgnoreCase(id)) return null;
        String g = canonical(game).getPath() + File.separator;
        return f.getPath().startsWith(g) ? null : f;
    }

    // Everything deleted that can be. → how it went: a file the app may not delete (adb made it, and its permissions were cut short) stays
    Tally remove() {
        Tally t = new Tally();
        File dead = new File(game.getParentFile(), PREFIX + game.getName());
        t.delete(dead);   // one an earlier removal left
        t.delete(game.renameTo(dead) ? dead : game);
        t.delete(cache);
        if (romfs != null) {
            for (String n : ROMFS_FILES) t.delete(new File(romfs.getParentFile(), n));
            romfs.getParentFile().delete();   // the game's folder there, when nothing else is in it; the folder above stays
        }
        return t;
    }

    // The game folders a removal cut short left behind (games/.removing-<title ID>), deleted. → how many
    static int sweep(File games) {
        File[] ds = games.listFiles(); int n = 0; Tally t = new Tally();
        if (ds != null) for (File d : ds) if (d.getName().startsWith(PREFIX) && ID.matcher(d.getName().substring(PREFIX.length())).matches()) { t.delete(d); n++; }
        return n;
    }

    // What a removal deleted: the bytes, the files that stayed and the first of them
    static final class Tally {
        long freed; int left; String leftAt;
        void delete(File f) {
            if (!link(f) && f.isDirectory()) { File[] ks = f.listFiles(); if (ks != null) for (File k : ks) delete(k); }
            long n = link(f) || f.isDirectory() ? 0 : f.length();
            if (f.delete()) freed += n;
            else if (link(f) || f.exists()) { left++; if (leftAt == null) leftAt = f.getPath(); }
        }
    }
    static long size(File f) {
        if (link(f)) return 0;
        if (!f.isDirectory()) return f.length();   // 0 when it isn't there
        long n = 0; File[] ks = f.listFiles(); if (ks != null) for (File k : ks) n += size(k);
        return n;
    }
    static boolean link(File f) { return Files.isSymbolicLink(f.toPath()); }
    static File canonical(File f) { try { return f.getCanonicalFile(); } catch (IOException e) { return f.getAbsoluteFile(); } }

    // A size as the games list shows one: GB to a tenth, else MB
    static String size(long n) {
        if (n >= 1L << 30) return String.format(Locale.ROOT, "%.1f GB", n / 1073741824.0);
        return String.format(Locale.ROOT, "%d MB", n > 0 ? Math.max(1, (n + (1 << 19)) >> 20) : 0);
    }
    // Where the image in a folder of its own is, in the player's words: on the SD card (a card's /storage/<ID>, not the phone's own /storage/emulated), or its folder
    static String where(File romfs) {
        String p = romfs.getPath();
        return p.startsWith("/storage/") && !p.startsWith("/storage/emulated/") && !p.startsWith("/storage/self/") ? "on the SD card" : "in " + romfs.getParent();
    }
}
