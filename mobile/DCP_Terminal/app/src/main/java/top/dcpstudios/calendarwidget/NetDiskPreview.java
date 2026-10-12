package top.dcpstudios.calendarwidget;

import android.app.Dialog;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.pdf.PdfRenderer;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Handler;
import android.os.ParcelFileDescriptor;
import android.text.Html;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.*;
import org.json.JSONObject;
import java.io.*;
import java.net.HttpURLConnection;
import java.nio.charset.*;
import java.util.*;

/** Account-bound previews. Office uses the existing server converter; no token is put in a URL. */
final class NetDiskPreview {
    private static final Map<MainActivity, Session> OPEN = Collections.synchronizedMap(new WeakHashMap<>());
    static void open(MainActivity activity, JSONObject node) {
        closeAll(activity);
        try { Session session = new Session(activity, node, NetDiskSession.account(activity)); OPEN.put(activity, session); session.show(); }
        catch (Exception error) { activity.error(error); }
    }
    static void closeAll(MainActivity activity) { Session old = OPEN.remove(activity); if (old != null) old.close(); }
    static void clearAccountData() { List<Session> sessions; synchronized (OPEN) { sessions = new ArrayList<>(OPEN.values()); } for (Session session : sessions) session.a.runOnUiThread(session::close); }
    static String extension(String name) { int dot = name.lastIndexOf('.'); return dot < 0 ? "" : name.substring(dot + 1).toLowerCase(Locale.ROOT); }
    static String kind(JSONObject node) {
        String ext = extension(node.optString("name")), mime = node.optString("mime_type").toLowerCase(Locale.ROOT);
        if (Arrays.asList("doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "rtf").contains(ext)) return "office";
        if ("pdf".equals(ext) || mime.equals("application/pdf")) return "pdf";
        if (Arrays.asList("md", "markdown", "mdown").contains(ext)) return "markdown";
        if (mime.startsWith("video/") || Arrays.asList("mp4", "webm", "mov", "mkv", "avi", "3gp", "m4v").contains(ext)) return "video";
        if (mime.startsWith("audio/") || Arrays.asList("mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "amr").contains(ext)) return "audio";
        if (mime.startsWith("image/") || Arrays.asList("png", "jpg", "jpeg", "webp", "gif", "bmp", "heic", "avif").contains(ext)) return "image";
        if (mime.startsWith("text/") || Arrays.asList("txt", "log", "csv", "tsv", "json", "xml", "yaml", "yml", "ini", "conf", "html", "htm", "css", "js", "ts", "py", "java", "sql", "tex").contains(ext)) return "text";
        return "unsupported";
    }
    static String text(byte[] bytes) throws CharacterCodingException {
        try { return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).decode(java.nio.ByteBuffer.wrap(bytes)).toString().replaceFirst("^\\uFEFF", ""); }
        catch (CharacterCodingException invalid) { return Charset.forName("GB18030").newDecoder().onMalformedInput(CodingErrorAction.REPLACE).decode(java.nio.ByteBuffer.wrap(bytes)).toString(); }
    }
    // Text is escaped before applying a small readable Markdown subset. Raw HTML and scripts remain text.
    static String markdown(String value) {
        StringBuilder out = new StringBuilder(); boolean code = false;
        for (String raw : value.split("\\r?\\n", -1)) {
            if (raw.trim().startsWith("```")) { out.append(code ? "</code></pre>" : "<pre><code>"); code = !code; continue; }
            String line = Html.escapeHtml(raw);
            if (code) { out.append(line).append('\n'); continue; }
            int heading = 0; while (heading < Math.min(6, raw.length()) && raw.charAt(heading) == '#') heading++;
            if (heading > 0 && raw.length() > heading && raw.charAt(heading) == ' ') out.append("<h").append(heading).append('>').append(Html.escapeHtml(raw.substring(heading + 1))).append("</h").append(heading).append('>');
            else if (raw.matches("[-*+] .*")) out.append("<p>• ").append(inline(Html.escapeHtml(raw.substring(2)))).append("</p>");
            else if (raw.startsWith("> ")) out.append("<blockquote>").append(inline(Html.escapeHtml(raw.substring(2)))).append("</blockquote>");
            else out.append("<p>").append(inline(line)).append("</p>");
        }
        if (code) out.append("</code></pre>"); return out.toString();
    }
    private static String inline(String text) { return text.replaceAll("\\*\\*([^*]+)\\*\\*", "<strong>$1</strong>").replaceAll("`([^`]+)`", "<code>$1</code>"); }

    private static final class Session {
        final MainActivity a; final JSONObject node; final NetDiskSession.Account account; final String kind; final Dialog dialog;
        final Handler handler = new Handler(android.os.Looper.getMainLooper()); final LinearLayout body; final TextView state;
        volatile boolean closed; volatile HttpURLConnection connection; volatile File local;
        PdfRenderer renderer; ParcelFileDescriptor descriptor; int pageIndex, renderGeneration; ImageView image; TextView pageLabel; Button previous, next;
        VideoView video; MediaController controls; MediaPlayer audio; WebView web;
        Session(MainActivity activity, JSONObject value, NetDiskSession.Account actor) {
            a = activity; node = value; account = actor; kind = kind(value); dialog = new Dialog(a); dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
            LinearLayout root = a.column(); root.setBackgroundColor(a.background); root.setPadding(a.d(16), a.d(12), a.d(16), a.d(12));
            LinearLayout heading = new LinearLayout(a); heading.setGravity(Gravity.CENTER_VERTICAL);
            TextView title = a.text(node.optString("name", "文件预览"), 19, a.ink); title.setMaxLines(2); title.setEllipsize(android.text.TextUtils.TruncateAt.END); heading.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
            heading.addView(button("关闭", this::close), new LinearLayout.LayoutParams(a.d(64), a.d(44))); root.addView(heading);
            state = a.text("正在准备预览…", 12, a.muted); state.setPadding(0, a.d(8), 0, a.d(8)); root.addView(state);
            body = a.column(); root.addView(body, new LinearLayout.LayoutParams(-1, 0, 1));
            LinearLayout actions = new LinearLayout(a); actions.addView(button("保存到设备", () -> { close(); a.netDiskScreen.chooseDownload(node); }), new LinearLayout.LayoutParams(0, a.d(44), 1));
            actions.addView(button("其他应用打开", () -> { close(); a.netDiskScreen.openFile(node); }), new LinearLayout.LayoutParams(0, a.d(44), 1)); root.addView(actions);
            dialog.setContentView(root); dialog.setOnDismissListener(d -> dispose());
        }
        Button button(String title, Runnable click) { return new NetDiskUi(a).button(title, title.contains("保存") ? "download" : title.contains("其他") ? "external" : "back", () -> { try { NetDiskSession.guard(a, account, click::run); } catch (Exception changed) { close(); } }); }
        void show() {
            dialog.show(); Window window = dialog.getWindow(); if (window != null) window.setLayout(-1, -1);
            handler.post(checkAccount);
            if (kind.equals("unsupported")) { state.setText("此格式可保存到设备，或使用其他应用打开。"); return; }
            if (kind.equals("audio") || kind.equals("video")) TerminalClient.IO.execute(this::media);
            else TerminalClient.IO.execute(this::document);
        }
        final Runnable checkAccount = new Runnable() { public void run() {
            if (closed) return; try { NetDiskSession.guard(a, account, () -> {}); if (a.isDestroyed() || a.isFinishing()) { close(); return; } }
            catch (Exception changed) { close(); return; } handler.postDelayed(this, 750);
        }};
        void ui(Runnable work) { a.runOnUiThread(() -> { if (closed) return; try { NetDiskSession.guard(a, account, work::run); } catch (Exception changed) { close(); } }); }
        void failure(Exception error) { ui(() -> state.setText("预览暂时无法打开，请保存到设备或使用其他应用。")); }
        String path() { return "/api/files/" + node.optLong("id") + "/preview"; }
        void document() {
            File downloaded = null;
            try {
                File directory = new File(a.getCacheDir(), "opened"); if (!directory.exists() && !directory.mkdirs()) throw new IOException("preview cache unavailable");
                downloaded = new File(directory, "preview-" + node.optLong("id") + "-" + UUID.randomUUID() + (kind.equals("office") || kind.equals("pdf") ? ".pdf" : ".data")); local = downloaded;
                boolean abbreviated = false;
                for (int attempt = 0; attempt < 2; attempt++) {
                    NetDiskSession.AuthorizedConnection opened = NetDiskSession.openBound(a, path(), "GET", account); HttpURLConnection c = opened.connection; connection = c; c.setReadTimeout(90000);
                    try {
                        int status = c.getResponseCode(); if (status == 401 && attempt == 0) { NetDiskSession.ensure(a, true); continue; }
                        if (status != 200) throw new IOException("preview unavailable");
                        long limit = kind.equals("text") || kind.equals("markdown") ? 2L * 1024 * 1024 : 128L * 1024 * 1024;
                        long size = -1; try { size = Long.parseLong(c.getHeaderField("Content-Length")); } catch (Exception ignored) {} if (size > limit && !kind.equals("text") && !kind.equals("markdown")) throw new IOException("preview file too large");
                        try (InputStream input = c.getInputStream(); OutputStream output = new FileOutputStream(downloaded)) {
                            byte[] block = new byte[65536]; long count = 0; int n;
                            while ((n = input.read(block)) != -1) {
                                if (closed) throw new IOException("preview closed"); NetDiskSession.guard(a, account, () -> {});
                                int wanted = (int)Math.min(n, limit - count); if (wanted > 0) output.write(block, 0, wanted); count += wanted;
                                if (wanted != n || count >= limit) { abbreviated = true; if (!kind.equals("text") && !kind.equals("markdown")) throw new IOException("preview file too large"); break; }
                            }
                        }
                        break;
                    } finally { c.disconnect(); connection = null; }
                }
                NetDiskSession.guard(a, account, () -> {}); final File ready = downloaded; final boolean excerpt = abbreviated;
                if (kind.equals("office") || kind.equals("pdf")) {
                    synchronized (this) { if (closed) { ready.delete(); return; } descriptor = ParcelFileDescriptor.open(ready, ParcelFileDescriptor.MODE_READ_ONLY); renderer = new PdfRenderer(descriptor); }
                    ui(() -> { pdf(); state.setText(kind.equals("office") ? "Office 文档预览" : "PDF 文档预览"); });
                } else if (kind.equals("image")) {
                    BitmapFactory.Options bounds = new BitmapFactory.Options(); bounds.inJustDecodeBounds = true; BitmapFactory.decodeFile(ready.getPath(), bounds);
                    bounds.inSampleSize = 1; while (bounds.outWidth / bounds.inSampleSize > 2048 || bounds.outHeight / bounds.inSampleSize > 2048) bounds.inSampleSize *= 2; bounds.inJustDecodeBounds = false;
                    Bitmap bitmap = BitmapFactory.decodeFile(ready.getPath(), bounds); if (bitmap == null) throw new IOException("unsupported image");
                    ui(() -> { image = new ImageView(a); image.setAdjustViewBounds(true); image.setScaleType(ImageView.ScaleType.FIT_CENTER); image.setImageBitmap(bitmap); body.addView(image, new LinearLayout.LayoutParams(-1, -1)); state.setText("图片预览"); });
                } else {
                    byte[] bytes; try (InputStream input = new FileInputStream(ready); ByteArrayOutputStream output = new ByteArrayOutputStream()) { byte[] block = new byte[8192]; int n; while ((n = input.read(block)) != -1) output.write(block, 0, n); bytes = output.toByteArray(); }
                    String content = text(bytes); ui(() -> { state.setText(excerpt ? "当前预览前 2 MB，完整内容可保存到设备。" : kind.equals("markdown") ? "Markdown 正在排版…" : "文本预览"); showText(content); });
                }
            } catch (Exception error) { failure(error); if (downloaded != null) downloaded.delete(); }
        }
        void showText(String content) {
            if (kind.equals("markdown")) {
                web = new WebView(a); web.getSettings().setJavaScriptEnabled(false); web.getSettings().setAllowFileAccess(false); web.getSettings().setAllowContentAccess(false); web.getSettings().setBlockNetworkLoads(true);
                web.setWebViewClient(new WebViewClient() {
                    @Override public boolean shouldOverrideUrlLoading(WebView view, String url) { return true; }
                    @Override public void onPageCommitVisible(WebView view, String url) { ui(() -> { if (state.getText().toString().equals("Markdown 正在排版…")) state.setText("Markdown 文档预览"); }); }
                });
                String document = "<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{font:16px/1.65 sans-serif;color:#1d1d1f;background:#fff;padding:12px;overflow-wrap:anywhere}pre{white-space:pre-wrap;background:#f5f5f7;padding:12px;border-radius:10px}code{font-family:monospace}blockquote{border-left:3px solid #007aff;padding-left:12px;color:#666}h1,h2,h3{line-height:1.3}</style>" + markdown(content);
                web.loadDataWithBaseURL("https://preview.invalid/", document, "text/html", "UTF-8", null); body.addView(web, new LinearLayout.LayoutParams(-1, -1));
            } else {
                ScrollView vertical = new ScrollView(a); HorizontalScrollView horizontal = new HorizontalScrollView(a); TextView text = a.text(content, 14, a.ink); text.setTypeface(android.graphics.Typeface.MONOSPACE); text.setTextIsSelectable(true); text.setPadding(a.d(12), a.d(12), a.d(12), a.d(12)); horizontal.addView(text); vertical.addView(horizontal); body.addView(vertical, new LinearLayout.LayoutParams(-1, -1));
            }
        }
        void pdf() {
            image = new ImageView(a); image.setScaleType(ImageView.ScaleType.FIT_CENTER); image.setBackgroundColor(Color.WHITE); body.addView(image, new LinearLayout.LayoutParams(-1, 0, 1));
            LinearLayout pages = new LinearLayout(a); pages.setGravity(Gravity.CENTER_VERTICAL); previous = button("上一页", () -> render(pageIndex - 1)); next = button("下一页", () -> render(pageIndex + 1)); pageLabel = a.text("", 13, a.muted); pageLabel.setGravity(Gravity.CENTER);
            pages.addView(previous, new LinearLayout.LayoutParams(a.d(88), a.d(44))); pages.addView(pageLabel, new LinearLayout.LayoutParams(0, a.d(44), 1)); pages.addView(next, new LinearLayout.LayoutParams(a.d(88), a.d(44))); body.addView(pages); render(0);
        }
        void render(int index) {
            if (closed || renderer == null || index < 0 || index >= renderer.getPageCount()) return; pageIndex = index; final int generation = ++renderGeneration;
            previous.setEnabled(index > 0); next.setEnabled(index + 1 < renderer.getPageCount()); pageLabel.setText((index + 1) + " / " + renderer.getPageCount());
            TerminalClient.IO.execute(() -> { try {
                Bitmap page;
                synchronized (this) { if (closed || renderer == null) return; try (PdfRenderer.Page p = renderer.openPage(index)) { int width = Math.min(1600, a.getResources().getDisplayMetrics().widthPixels); int height = Math.max(1, (int)((long)width * p.getHeight() / p.getWidth())); if (height > 2400) { width = Math.max(1, width * 2400 / height); height = 2400; } page = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888); page.eraseColor(Color.WHITE); p.render(page, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY); } }
                ui(() -> { if (generation == renderGeneration) image.setImageBitmap(page); });
            } catch (Exception error) { failure(error); } });
        }
        void media() {
            if (closed) return;
            try {
                String authorization = NetDiskSession.authorization(a); NetDiskSession.guard(a, account, () -> {});
                Uri uri = Uri.parse(account.origin + path()); Map<String, String> headers = Collections.singletonMap("Authorization", authorization);
                ui(() -> {
                    if (kind.equals("video")) { video = new VideoView(a); body.addView(video, new LinearLayout.LayoutParams(-1, -1)); controls = new MediaController(a); controls.setAnchorView(video); video.setMediaController(controls); video.setOnPreparedListener(player -> handler.post(() -> ui(() -> { if (video == null || controls == null) return; state.setText("视频预览"); video.seekTo(1); controls.show(2500); }))); video.setOnErrorListener((player, what, extra) -> { handler.post(() -> ui(() -> state.setText("此视频暂时无法播放，可使用其他应用打开。"))); return true; }); video.setVideoURI(uri, headers); }
                    else { try { audio = new MediaPlayer(); TextView label = a.text(node.optString("name"), 20, a.ink); label.setGravity(Gravity.CENTER); body.addView(label, new LinearLayout.LayoutParams(-1, 0, 1)); SeekBar seek = new SeekBar(a); body.addView(seek); TextView clock = a.text("", 13, a.muted); body.addView(clock); Button play = button("正在加载…", () -> { if (audio == null) return; try { if (audio.isPlaying()) { audio.pause(); } else { audio.start(); } } catch (IllegalStateException ignored) {} }); play.setEnabled(false); body.addView(play, new LinearLayout.LayoutParams(-1, a.d(44)));
                        seek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() { public void onStartTrackingTouch(SeekBar s) {} public void onStopTrackingTouch(SeekBar s) {} public void onProgressChanged(SeekBar s, int progress, boolean user) { if (user && audio != null) try { audio.seekTo(progress); } catch (IllegalStateException ignored) {} } });
                        audio.setOnPreparedListener(player -> { if (closed) return; state.setText("音频预览"); seek.setMax(player.getDuration()); play.setEnabled(true); play.setText("播放"); handler.post(new Runnable() { public void run() { if (closed || audio == null) return; try { int at = audio.getCurrentPosition(); seek.setProgress(at); clock.setText(String.format(Locale.ROOT, "%d:%02d / %d:%02d", at / 60000, at / 1000 % 60, seek.getMax() / 60000, seek.getMax() / 1000 % 60)); play.setText(audio.isPlaying() ? "暂停" : "播放"); handler.postDelayed(this, 500); } catch (IllegalStateException ignored) {} } }); });
                        audio.setOnErrorListener((player, what, extra) -> { ui(() -> state.setText("此音频暂时无法播放，可使用其他应用打开。")); return true; }); audio.setDataSource(a, uri, headers); audio.prepareAsync();
                    } catch (Exception error) { failure(error); } }
                });
            } catch (Exception error) { failure(error); }
        }
        void close() { if (closed) return; try { dialog.dismiss(); } finally { dispose(); } }
        synchronized void dispose() {
            if (closed) return; closed = true; handler.removeCallbacksAndMessages(null);
            try {
                HttpURLConnection active = connection; connection = null;
                if (active != null) try { active.disconnect(); } catch (RuntimeException ignored) {}
                MediaController overlay = controls; controls = null;
                if (overlay != null) try { overlay.hide(); } catch (RuntimeException ignored) {}
                VideoView playing = video; video = null;
                if (playing != null) {
                    try { playing.setMediaController(null); } catch (RuntimeException ignored) {}
                    playing.setOnPreparedListener(null);
                    // A cancelled prepare must not open Android's playback-error dialog.
                    playing.setOnErrorListener((player, what, extra) -> true);
                    // Clear the source before detaching/releasing: a late surface callback
                    // must not reopen the closed stream. suspend releases in any player state.
                    try { playing.setVideoURI(null, null); } catch (RuntimeException ignored) {}
                    try { playing.suspend(); } catch (RuntimeException ignored) {}
                    try { body.removeView(playing); } catch (RuntimeException ignored) {}
                }
                MediaPlayer sound = audio; audio = null;
                if (sound != null) try { sound.release(); } catch (RuntimeException ignored) {}
                WebView reader = web; web = null;
                if (reader != null) {
                    try { reader.stopLoading(); } catch (RuntimeException ignored) {}
                    try { reader.destroy(); } catch (RuntimeException ignored) {}
                }
                PdfRenderer pages = renderer; renderer = null;
                if (pages != null) try { pages.close(); } catch (RuntimeException ignored) {}
                ParcelFileDescriptor file = descriptor; descriptor = null;
                if (file != null) try { file.close(); } catch (IOException ignored) {}
                if (local != null) local.delete();
            } finally { if (OPEN.get(a) == this) OPEN.remove(a); }
        }
    }
}
