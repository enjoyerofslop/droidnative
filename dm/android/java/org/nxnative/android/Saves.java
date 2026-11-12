// Save import and export for the launcher's Save rows (LauncherSaves.java), in plain Java (java.io, java.util.zip) so that a JVM runs it in
// dm/tools/tests/test_android_cli.py. A game's save is internal storage's saves/<title ID>: the folder the game sees at save:/, committed whole by the host
// (hle_fs.c), with saves/<title ID>_device beside it for a game that mounts device save data as well as account save data.
//   Finding a save in the files picked (find): the formats other tools write, each of which says where the save's own folder is and, mostly, whose it is:
//     a DroidPlay export or backup     saves/<title ID>/, saves/<title ID>_device/, xattrs.tsv (Launcher.backup, export below)
//     yuzu and its successors          nand/user/save/0000000000000000/<user ID>/<title ID>/; the all-zero user ID holds device saves
//     Ryujinx                          bis/user/save/<save ID>/0/ (1/ is its working copy); ExtraData0 starts with the title ID, its byte 0x20 is the save's type
//     JKSV                             JKSV/<game>/<user> - <date>/, with .nx_save_meta.bin (title ID at 5, type at 37) from its rewrite on
//     EdiZon                           EdiZon/saves/<title ID>/<date>/, with edizon_save_metadata.json ("title_id")
//     Checkpoint                       Checkpoint/saves/0x<title ID> <game>/<date> <user>/
//   Anything else is a save folder as it is (UltraTears' userdata/save/<user ID>/, an emulator's folder picked at the save itself, a save site's zip): the folder
//   picked or a zip's one top folder, or, when the game has a save here already, the folder whose names match it best. Several saves (users, dates) are all
//   returned, for the player to pick; another game's only when nothing else is there.
//   Swapping one in (install): the current save is first copied out (keep), as Launcher.backup writes a backup, then each part is copied beside the save and
//   renamed over it through <save>.swap, the host's own convention for a swap of renames (plat_android.c), so a kill midway leaves the old save or the new one.
package org.nxnative.android;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipException;
import java.util.zip.ZipFile;
import java.util.zip.ZipOutputStream;

final class Saves {
    static final String JKSV_META = ".nx_save_meta.bin", EDIZON_META = "edizon_save_metadata.json";
    // A title ID (0100… on the Switch, 0400… on the Switch 2), never a Ryujinx save ID (00…) or a system save's (80…)
    static final Pattern TITLE = Pattern.compile("(?i)(0[1-7][0-9a-f]{14})(_device)?"), CHECKPOINT = Pattern.compile("(?i)0x(0[1-7][0-9a-f]{14})( .*)?");
    static final Pattern USER = Pattern.compile("(?i)[0-9a-f]{32}"), HEX16 = Pattern.compile("(?i)[0-9a-f]{16}");
    // backup folders by date: JKSV's "<user> - 2023.01.22 @ 15.10.11", EdiZon's "20220320_225347", Checkpoint's "20200101-120000 <user>"
    static final Pattern DATED = Pattern.compile(".+ - \\d{4}\\.\\d{2}\\.\\d{2} @ \\d{2}\\.\\d{2}\\.\\d{2}|\\d{8}_\\d{6}|\\d{8}-\\d{6}( .*)?");

    // A save found: the folder that is the game's save (account), its device save, or both
    static final class Found {
        File account, device; String format, label, titleId;   // titleId null: the files don't say whose save it is
        File xattrs; String xattrsAccount, xattrsDevice;        // a DroidPlay backup's xattrs.tsv, and each part's path in it
        boolean matched, unmatched;                             // its names match the game's save here / share none with it
        int files; long bytes, newest;
        File main() { return account != null ? account : device; }
    }

    // Copies keep the save's extended attributes (hle_fs.c's guest names of case collisions): android.system.Os on the phone, nothing on a JVM
    interface Xattrs { void read(File f, String rel, StringBuilder tsv); void apply(File root, String top, File tsv); }

    // ---------------- finding a save ----------------
    static List<Found> find(File root, String tid, Set<String> account, Set<String> device) {
        List<Found> all = new ArrayList<>();
        scan(root, 0, null, all);
        if (all.isEmpty()) { Found f = bare(root, account, device); if (f != null) all.add(f); }
        List<Found> mine = new ArrayList<>();
        for (Found f : all) if (f.titleId == null || f.titleId.equalsIgnoreCase(tid)) mine.add(f);
        List<Found> out = mine.isEmpty() ? all : mine;
        for (Found f : out) {
            if (f.account != null) count(f.account, f, true);
            if (f.device != null) count(f.device, f, true);
            if (!f.matched && (!account.isEmpty() || !device.isEmpty())) f.unmatched = overlap(f.main(), account) + overlap(f.main(), device) == 0;
        }
        Collections.sort(out, new Comparator<Found>() { public int compare(Found a, Found b) { return Long.compare(b.newest, a.newest); } });
        return out;
    }

    // → whether it found a save at or under d. hint: the title ID the folders above gave
    static boolean scan(File d, int depth, String hint, List<Found> out) {
        if (depth > 8) return false;
        File jk = new File(d, JKSV_META), ed = new File(d, EDIZON_META);
        if (jk.isFile()) { out.add(jksv(d, jk, hint)); return true; }
        if (ed.isFile()) { out.add(edizon(d, ed, hint)); return true; }
        if (ryujinx(d)) { out.add(ryujinxSave(d)); return true; }
        boolean any = false; Map<String, Found> titles = new LinkedHashMap<>();
        boolean deviceUser = d.getName().matches("0{32}");   // yuzu's user folder of device saves
        for (File k : list(d)) {
            if (!k.isDirectory()) continue;
            String n = k.getName(); Matcher t = TITLE.matcher(n), c = CHECKPOINT.matcher(n);
            if (t.matches() && !ryujinx(k)) {   // a title ID's folder: its dated backups (EdiZon), or the save itself (yuzu, a DroidPlay backup)
                String id = t.group(1).toUpperCase(Locale.ROOT);
                if (backups(k)) { for (File b : list(k)) if (b.isDirectory() && !scan(b, depth + 2, id, out)) out.add(dated(b, id)); any = true; continue; }
                Found f = titles.get(id);
                if (f == null) { f = new Found(); f.titleId = id; f.format = format(d); f.label = label(d, k); titles.put(id, f); }
                if (t.group(2) != null || deviceUser) f.device = k; else f.account = k;
                continue;
            }
            if (c.matches()) {   // Checkpoint: 0x<title ID> <game>/<backups>
                String id = c.group(1).toUpperCase(Locale.ROOT);
                for (File b : list(k)) if (b.isDirectory() && !scan(b, depth + 2, id, out)) { Found f = dated(b, id); f.format = "Checkpoint"; out.add(f); }
                any = true; continue;
            }
            if (DATED.matcher(n).matches()) { if (!scan(k, depth + 1, hint, out)) out.add(dated(k, hint)); any = true; continue; }
            any |= scan(k, depth + 1, hint, out);
        }
        for (Found f : titles.values()) {
            if (f.format.equals("DroidPlay")) {   // its xattrs.tsv, as Launcher.restore takes it
                f.xattrs = new File(d.getParentFile(), "xattrs.tsv");
                if (f.account != null) f.xattrsAccount = "saves/" + f.account.getName();
                if (f.device != null) f.xattrsDevice = "saves/" + f.device.getName();
            }
            out.add(f); any = true;
        }
        return any;
    }

    // Ryujinx's save folder: its committed copy 0/, its working copy 1/ (and _/ while it commits), ExtraData0/1 and .lock; without those three, a save ID's folder
    static boolean ryujinx(File d) {
        if (!new File(d, "0").isDirectory()) return false;
        boolean mark = false;
        for (File k : list(d)) {
            String n = k.getName();
            if (n.equals("ExtraData0") || n.equals("ExtraData1") || n.equals(".lock")) mark = true;
            else if (!n.equals("0") && !n.equals("1") && !n.equals("_")) return false;
        }
        return mark || HEX16.matcher(d.getName()).matches();
    }
    static Found ryujinxSave(File d) {
        Found f = new Found(); f.format = "Ryujinx"; f.label = d.getName();
        byte[] x = head(new File(d, "ExtraData0"), 0x40); if (x == null || x.length < 0x21) x = head(new File(d, "ExtraData1"), 0x40);
        boolean dev = false;
        if (x != null && x.length >= 0x21) {   // LibHac's SaveDataExtraData: SaveDataAttribute first (ProgramId u64, UserId u128, StaticSaveDataId u64, Type u8)
            long id = le64(x, 0); if (id != 0) f.titleId = String.format(Locale.ROOT, "%016X", id);
            dev = x[0x20] == 3;   // SaveDataType.Device
        }
        if (dev) f.device = new File(d, "0"); else f.account = new File(d, "0");
        return f;
    }
    static Found jksv(File d, File meta, String hint) {
        Found f = new Found(); f.format = "JKSV"; f.label = d.getName(); f.titleId = hint; f.account = d;
        byte[] m = head(meta, 64);   // fs::SaveMetaData, packed: magic "JKSV", revision u8, applicationID u64, AccountUid, systemSaveID u64, saveDataType u8
        if (m != null && m.length >= 38 && m[0] == 'J' && m[1] == 'K' && m[2] == 'S' && m[3] == 'V') {
            long id = le64(m, 5); if (id != 0) f.titleId = String.format(Locale.ROOT, "%016X", id);
            if (m[37] == 3) { f.device = d; f.account = null; }   // FsSaveDataType_Device
        }
        return f;
    }
    static Found edizon(File d, File meta, String hint) {
        Found f = new Found(); f.format = "EdiZon"; f.account = d; f.titleId = hint;
        String j = text(meta); Matcher m = Pattern.compile("\"title_id\"\\s*:\\s*\"(" + TITLE.pattern() + ")\"").matcher(j == null ? "" : j);
        if (m.find()) f.titleId = m.group(2).toUpperCase(Locale.ROOT);
        Matcher u = Pattern.compile("\"user_name\"\\s*:\\s*\"([^\"]*)\"").matcher(j == null ? "" : j);
        f.label = (u.find() ? u.group(1) + ", " : "") + d.getName();
        return f;
    }
    static Found dated(File d, String hint) {   // a backup folder named by its date: the save as it is
        Found f = new Found(); f.account = d; f.titleId = hint; f.label = d.getName();
        f.format = d.getName().contains(" @ ") ? "JKSV" : d.getName().matches("\\d{8}_\\d{6}") ? "EdiZon" : "Checkpoint";
        return f;
    }
    static boolean backups(File d) {   // only dated backup folders inside (EdiZon's saves/<title ID>/)
        File[] ks = list(d); if (ks.length == 0) return false;
        for (File k : ks) if (!k.isDirectory() || !DATED.matcher(k.getName()).matches()) return false;
        return true;
    }
    static String format(File parent) {   // whose layout a title ID's folder is in, from the folder holding it
        if (USER.matcher(parent.getName()).matches()) return "yuzu";
        if (parent.getName().equals("saves")) return "DroidPlay";   // a DroidPlay export or backup (EdiZon's saves/ holds dated backups, taken above)
        return "title";
    }
    static String label(File parent, File k) { return USER.matcher(parent.getName()).matches() ? (parent.getName().matches("0{32}") ? "device save" : "user " + parent.getName()) : k.getName(); }

    // The save as it is: the end of the chain of lone folders from root (the folder picked, staged as root's one folder; a zip's one top folder; UltraTears'
    // userdata/save/<user ID>/). Where the game has a save here, the folder whose names match its names best (breadth first: the shallowest of equal matches),
    // whichever part of it they match: that also finds a save whose top is one folder (Smash's save_data/), which the chain would pass through
    static Found bare(File root, Set<String> account, Set<String> device) {
        File[] top = list(root); if (top.length == 0) return null;
        File r = root;
        for (int i = 0; i < 8 && top.length == 1 && top[0].isDirectory(); i++) { r = top[0]; top = list(r); }
        Found f = new Found(); f.format = "folder"; boolean dev = false;
        if (!account.isEmpty() || !device.isEmpty()) {
            File best = null; int bestN = 0; int depth = 0;
            for (List<File> level = Collections.singletonList(root); !level.isEmpty() && depth <= 6; depth++) {
                List<File> next = new ArrayList<>();
                for (File d : level) {
                    int a = overlap(d, account), v = overlap(d, device);
                    if (Math.max(a, v) > bestN) { best = d; bestN = Math.max(a, v); dev = v > a; }
                    for (File k : list(d)) if (k.isDirectory()) next.add(k);
                }
                level = next;
            }
            if (best != null) { r = best; f.matched = true; }
        }
        f.label = r == root ? "" : r.getName();
        if (dev) f.device = r; else f.account = r;
        return f;
    }
    static int overlap(File d, Set<String> names) {
        if (names.isEmpty()) return 0;
        int n = 0; for (File k : list(d)) if (names.contains(k.getName().toLowerCase(Locale.ROOT))) n++;
        return n;
    }
    // The names at the top of a save (lower case), to match an import against
    static Set<String> names(File save) { Set<String> s = new HashSet<>(); for (File k : list(save)) s.add(k.getName().toLowerCase(Locale.ROOT)); return s; }
    // What a save holds at its top, for the player: folders with a slash, at most max names
    static String top(File save, int max) {
        List<String> ns = new ArrayList<>(); for (File k : list(save)) if (!meta(k.getName())) ns.add(k.getName() + (k.isDirectory() ? "/" : ""));
        StringBuilder s = new StringBuilder();
        for (int i = 0; i < ns.size() && i < max; i++) s.append(i > 0 ? ", " : "").append(ns.get(i));
        if (ns.size() > max) s.append(String.format(Locale.ROOT, " and %d more", ns.size() - max));
        return s.toString();
    }

    // ---------------- swapping a save in ----------------
    // tid's save copied out to keep/ as a backup (saves/<tid>[_device], xattrs.tsv, README.txt). → whether there was a save to keep
    static boolean keep(File internal, String tid, File keep, String readme, Xattrs xa) throws IOException {
        StringBuilder tsv = new StringBuilder(); boolean any = false;
        for (String part : new String[] {tid, tid + "_device"}) {
            File s = new File(internal, "saves/" + part); if (!hasFiles(s)) continue;
            copy(s, new File(keep, "saves/" + part), "saves/" + part, tsv, xa, false); any = true;
        }
        if (!any) return false;
        write(new File(keep, "xattrs.tsv"), tsv.toString()); write(new File(keep, "README.txt"), readme);
        return true;
    }

    // f in place of tid's save. Each part goes to saves/<tid> (account) or saves/<tid>_device: a device save alone goes to _device only where the game keeps one
    // there (it mounts both kinds; hle_fs.c h_fs_MountDeviceSave), else it is the game's one save. Call keep first
    static void install(File internal, String tid, Found f, Xattrs xa) throws IOException {
        File saves = new File(internal, "saves"); if (!saves.isDirectory() && !saves.mkdirs()) throw new IOException("can't make " + saves);
        String acc = tid, dev = f.account != null || new File(saves, tid + "_device").isDirectory() ? tid + "_device" : tid;
        if (f.account != null) put(saves, acc, f.account, f.xattrs, f.xattrsAccount, xa);
        if (f.device != null) put(saves, dev, f.device, f.xattrs, f.xattrsDevice, xa);
    }
    static void put(File saves, String part, File src, File tsv, String top, Xattrs xa) throws IOException {
        File dst = new File(saves, part), tmp = new File(saves, part + ".importing"), side = new File(saves, part + ".swap");
        deleteTree(tmp); copy(src, tmp, null, null, null, true);
        if (xa != null && tsv != null && top != null && tsv.isFile()) xa.apply(tmp, top, tsv);
        for (String left : new String[] {".work", ".new"}) deleteTree(new File(saves, part + left));   // the host's copies of a save it was writing; discarded at its next start anyway
        deleteTree(side);
        if (dst.exists() && !dst.renameTo(side)) { deleteTree(tmp); throw new IOException("can't move " + dst + " aside"); }
        if (!tmp.renameTo(dst)) { side.renameTo(dst); deleteTree(tmp); throw new IOException("can't move " + tmp + " into place"); }
        deleteTree(side);
    }

    // The saves kept on this phone (backups/<time>[-<title ID>]/saves/<tid>…), newest first, as Founds to install
    static List<Found> kept(File backups, String tid) {
        List<Found> out = new ArrayList<>(); File[] ds = backups.listFiles(); if (ds == null) return out;
        Arrays.sort(ds, Collections.reverseOrder());
        for (File d : ds) {
            if (!d.isDirectory() || d.getName().equals("restore")) continue;
            File a = new File(d, "saves/" + tid), v = new File(d, "saves/" + tid + "_device");
            if (!hasFiles(a) && !hasFiles(v)) continue;
            Found f = new Found(); f.format = "kept"; f.label = d.getName(); f.titleId = tid; f.xattrs = new File(d, "xattrs.tsv");
            if (hasFiles(a)) { f.account = a; f.xattrsAccount = "saves/" + tid; }
            if (hasFiles(v)) { f.device = v; f.xattrsDevice = "saves/" + tid + "_device"; }
            count(a, f, false); count(v, f, false); out.add(f);
        }
        return out;
    }

    // ---------------- export ----------------
    // tid's save as a ZIP laid out as a backup (saves/<tid>[_device]/…, xattrs.tsv, README.txt), so the import above and Launcher.restore both take it. → files written
    static int export(File internal, String tid, OutputStream out, String readme, Xattrs xa) throws IOException {
        StringBuilder tsv = new StringBuilder(); int[] n = {0};
        ZipOutputStream z = new ZipOutputStream(out);
        for (String part : new String[] {tid, tid + "_device"}) {
            File s = new File(internal, "saves/" + part); if (hasFiles(s)) zip(z, s, "saves/" + part, tsv, xa, n);
        }
        entry(z, "xattrs.tsv", tsv.toString().getBytes(StandardCharsets.UTF_8));
        entry(z, "README.txt", readme.getBytes(StandardCharsets.UTF_8));
        z.finish(); z.flush();
        return n[0];
    }
    static void zip(ZipOutputStream z, File f, String rel, StringBuilder tsv, Xattrs xa, int[] n) throws IOException {
        if (xa != null) xa.read(f, rel, tsv);
        ZipEntry e = new ZipEntry(f.isDirectory() ? rel + "/" : rel); e.setTime(f.lastModified()); z.putNextEntry(e);
        if (f.isDirectory()) { z.closeEntry(); for (File k : sorted(f.listFiles())) zip(z, k, rel + "/" + k.getName(), tsv, xa, n); return; }
        try (InputStream in = new FileInputStream(f)) { byte[] b = new byte[1 << 16]; for (int k; (k = in.read(b)) > 0; ) z.write(b, 0, k); }
        z.closeEntry(); n[0]++;
    }
    static void entry(ZipOutputStream z, String name, byte[] data) throws IOException { z.putNextEntry(new ZipEntry(name)); z.write(data); z.closeEntry(); }

    // ---------------- the files picked ----------------
    // What a file is, from its first bytes: "zip", or the archive Android can't open (rar, 7z, gz), or null
    static String kind(byte[] h) {
        if (h.length >= 4 && h[0] == 'P' && h[1] == 'K' && (h[2] == 3 || h[2] == 5) && (h[3] == 4 || h[3] == 6)) return "zip";
        if (h.length >= 6 && h[0] == 'R' && h[1] == 'a' && h[2] == 'r' && h[3] == '!') return "RAR";
        if (h.length >= 6 && (h[0] & 0xFF) == '7' && (h[1] & 0xFF) == 'z' && (h[2] & 0xFF) == 0xBC && (h[3] & 0xFF) == 0xAF) return "7z";
        if (h.length >= 2 && (h[0] & 0xFF) == 0x1F && (h[1] & 0xFF) == 0x8B) return "gzip";
        return null;
    }
    // A ZIP's files under dst (names that leave it refused), at most max bytes. A method ZipFile doesn't read (Deflate64, which Windows' own zip uses for big
    // files) fails with "method <n>" in the message. Names not in UTF-8 are taken as code page 437, as old Windows zips write them. → the files written
    static int unzip(File zip, File dst, long max) throws IOException {
        try (ZipFile z = new ZipFile(zip, StandardCharsets.UTF_8)) { return unzip(z, dst, max); }
        catch (IllegalArgumentException | ZipException malformed) {   // a name not in UTF-8 (OpenJDK 8's ZipFile throws the first, later ones the second), or a method
            if (method(malformed) != null) throw new IOException(method(malformed));
            Charset cp; try { cp = Charset.forName("IBM437"); } catch (IllegalArgumentException none) { cp = StandardCharsets.ISO_8859_1; }
            deleteTree(dst);
            try (ZipFile z = new ZipFile(zip, cp)) { return unzip(z, dst, max); }
            catch (ZipException e) { throw method(e) != null ? new IOException(method(e)) : e; }
        }
    }
    static String method(Exception e) {   // later ZipFiles refuse a method they don't read when they open the file: "invalid CEN header (bad compression method: 9)"
        Matcher m = Pattern.compile("compression method:? *(\\d+)").matcher(String.valueOf(e.getMessage()));
        return m.find() ? "method " + m.group(1) : null;
    }
    static int unzip(ZipFile z, File dst, long max) throws IOException {
        String root = dst.getCanonicalPath() + File.separator; long total = 0; int n = 0;
        List<ZipEntry> es = new ArrayList<>();
        for (Enumeration<? extends ZipEntry> en = z.entries(); en.hasMoreElements(); ) {
            ZipEntry e = en.nextElement(); es.add(e);
            if (e.getMethod() != ZipEntry.STORED && e.getMethod() != ZipEntry.DEFLATED) throw new IOException("method " + e.getMethod() + " of " + e.getName());
            if (e.getSize() > 0) total += e.getSize();
        }
        if (total > max) throw new IOException(String.format(Locale.ROOT, "too big: %d bytes unpacked", total));
        byte[] b = new byte[1 << 16]; long done = 0;
        for (ZipEntry e : es) {
            String name = e.getName().replace('\\', '/');
            if (junkPath(name)) continue;
            File out = new File(dst, name);
            if (!out.getCanonicalPath().startsWith(root) && !(out.getCanonicalPath() + File.separator).equals(root)) throw new IOException("a file outside the folder: " + e.getName());
            if (e.isDirectory()) { out.mkdirs(); continue; }
            out.getParentFile().mkdirs();
            try (InputStream in = z.getInputStream(e); OutputStream o = new FileOutputStream(out)) {
                for (int k; (k = in.read(b)) > 0; ) { o.write(b, 0, k); if ((done += k) > max) throw new IOException("too big: more than " + max + " bytes unpacked"); }
            }
            if (e.getTime() > 0) out.setLastModified(e.getTime());
            n++;
        }
        return n;
    }

    // ---------------- helpers ----------------
    // Files no save holds: other systems' folder notes. meta: a backup tool's own file at a save's top, which isn't the game's
    static boolean junk(String n) { return n.equals(".DS_Store") || n.equals("Thumbs.db") || n.equals("desktop.ini") || n.equals("__MACOSX") || n.startsWith("._"); }
    static boolean junkPath(String p) { for (String s : p.split("/")) if (junk(s)) return true; return false; }
    static boolean meta(String n) { return n.equals(JKSV_META) || n.equals(EDIZON_META); }
    static File[] list(File d) {
        File[] ks = d.listFiles(); if (ks == null) return new File[0];
        List<File> out = new ArrayList<>(); for (File k : ks) if (!junk(k.getName())) out.add(k);
        return sorted(out.toArray(new File[0]));
    }
    static File[] sorted(File[] fs) { if (fs == null) return new File[0]; Arrays.sort(fs); return fs; }
    // A copy of a save folder: junk left out everywhere, a backup tool's own files at its top (top), each file's attributes read into tsv when given
    static void copy(File s, File d, String rel, StringBuilder tsv, Xattrs xa, boolean top) throws IOException {
        if (!d.isDirectory() && !d.mkdirs()) throw new IOException("can't make " + d);
        if (xa != null && tsv != null) xa.read(s, rel, tsv);
        for (File k : list(s)) {
            if (top && meta(k.getName())) continue;
            File t = new File(d, k.getName()); String r = rel == null ? null : rel + "/" + k.getName();
            if (k.isDirectory()) { copy(k, t, r, tsv, xa, false); continue; }
            try (InputStream in = new FileInputStream(k); FileOutputStream o = new FileOutputStream(t)) {
                byte[] b = new byte[1 << 16]; for (int n; (n = in.read(b)) > 0; ) o.write(b, 0, n);
                o.getFD().sync();
            }
            t.setLastModified(k.lastModified());
            if (xa != null && tsv != null) xa.read(k, r, tsv);
        }
    }
    static void count(File d, Found f, boolean top) {
        if (d == null) return;
        for (File k : list(d)) {
            if (top && meta(k.getName())) continue;
            if (k.isDirectory()) count(k, f, false); else { f.files++; f.bytes += k.length(); f.newest = Math.max(f.newest, k.lastModified()); }
        }
    }
    static boolean hasFiles(File f) { if (f.isFile()) return true; File[] ks = f.listFiles(); if (ks != null) for (File k : ks) if (hasFiles(k)) return true; return false; }
    static void deleteTree(File f) { File[] ks = f.listFiles(); if (ks != null) for (File k : ks) deleteTree(k); f.delete(); }
    static byte[] head(File f, int max) {
        try (InputStream in = new FileInputStream(f)) { byte[] b = new byte[max]; int n = 0; for (int k; n < max && (k = in.read(b, n, max - n)) > 0; ) n += k; return Arrays.copyOf(b, n); }
        catch (IOException e) { return null; }
    }
    static String text(File f) { byte[] b = head(f, 1 << 16); return b == null ? null : new String(b, StandardCharsets.UTF_8); }
    static long le64(byte[] b, int at) { long v = 0; for (int i = 7; i >= 0; i--) v = v << 8 | (b[at + i] & 0xFF); return v; }
    static void write(File f, String s) throws IOException { f.getParentFile().mkdirs(); try (FileOutputStream o = new FileOutputStream(f)) { o.write(s.getBytes(StandardCharsets.UTF_8)); } }
}
