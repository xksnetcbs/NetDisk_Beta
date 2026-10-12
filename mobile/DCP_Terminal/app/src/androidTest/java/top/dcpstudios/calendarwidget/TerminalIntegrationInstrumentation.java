package top.dcpstudios.calendarwidget;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/** Runs against an isolated emulator; never requires server or administrator credentials. */
public class TerminalIntegrationInstrumentation extends WidgetRegressionInstrumentation {
    private boolean widgetSuite, publicSuite, remoteSuite, previewSuite, replyRemoteSuite, diskClickSuite, videoExitSuite;
    private String upgradeSuite;
    @Override public void onCreate(Bundle arguments) {
        widgetSuite = arguments != null && "widget".equals(arguments.getString("suite"));
        publicSuite = arguments != null && "public".equals(arguments.getString("suite"));
        remoteSuite = arguments != null && "remote".equals(arguments.getString("suite"));
        previewSuite = arguments != null && "preview".equals(arguments.getString("suite"));
        replyRemoteSuite = arguments != null && "reply-remote".equals(arguments.getString("suite"));
        diskClickSuite = arguments != null && "disk-click".equals(arguments.getString("suite"));
        videoExitSuite = arguments != null && "video-exit".equals(arguments.getString("suite"));
        upgradeSuite=arguments==null?"":arguments.getString("suite","");
        super.onCreate(arguments);
    }

    static WebView findWeb(View view) {
        if (view instanceof WebView) return (WebView)view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) {
            WebView match = findWeb(((ViewGroup)view).getChildAt(i)); if (match != null) return match;
        }
        return null;
    }

    static boolean textPresent(View view, String label) {
        if (view instanceof TextView && label.contentEquals(((TextView)view).getText())) return true;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) {
            if (textPresent(((ViewGroup)view).getChildAt(i), label)) return true;
        }
        return false;
    }

    private void identity(Context context, long userId, boolean administrator, String secret) throws Exception {
        runOnMainSync(() -> CookieManager.getInstance().setCookie("https://127.0.0.1:1/api/auth/refresh",
            "dcp_netdisk_session=" + secret + "; Path=/api/auth; Secure; HttpOnly; Max-Age=3600"));
        CookieManager.getInstance().flush();
        for (int retry = 0; retry < 50 && NetDiskSession.cookie(context).isEmpty(); retry++) Thread.sleep(20);
        NetDiskSession.prefs(context).edit().putString("origin", "https://127.0.0.1:1")
            .putLong("user_id", userId).putString("username", "isolated-user-" + userId)
            .putBoolean("signed_out", false).putBoolean("terminal_access", administrator)
            .putString("session_cookie_digest", NetDiskSession.digest(NetDiskSession.cookie(context))).commit();
    }

    @Override public void onStart() {
        if (widgetSuite) { super.onStart(); return; }
        if(upgradeSuite.startsWith("upgrade-")){UpgradeRegression.run(this,upgradeSuite);return;}
        if (publicSuite) { publicWebView(); return; }
        if (remoteSuite) { RemoteTerminalRegression.run(this); return; }
        if (previewSuite) { PreviewRemoteRegression.run(this); return; }
        if (replyRemoteSuite) { ReplyRemoteRegression.run(this); return; }
        if (diskClickSuite) { NetDiskClickRegression.run(this); return; }
        if (videoExitSuite) { VideoExitRegression.run(this); return; }
        Bundle result = new Bundle(); int outcome = Activity.RESULT_OK;
        try {
            Context context = getTargetContext();
            NetDiskSession.prefs(context).edit().putString("origin", "https://127.0.0.1:1").commit();
            CalendarStore.prefs(context).edit().putInt("interval", 0).commit();
            TerminalClient.prefs(context).edit().putBoolean("notifications", false).putBoolean("notification_setup_seen", true).commit();
            identity(context, 11, false, "ordinary-isolated-cookie");
            TerminalDb db = TerminalDb.get(context); db.clearAccountData();
            db.put(new JSONObject().put("id", 501).put("source", "wechat").put("title", "private legacy message").put("body", "isolated fixture").put("occurred_at", 0));
            db.schedules(new JSONArray().put(new JSONObject().put("id", "netdisk:task:101").put("source", "netdisk").put("netdisk_kind", "task")
                .put("title", "Assigned NetDisk task").put("start_at", 1790000000000L).put("end_at", 1790003600000L).put("status", "active")));
            String global = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:legacy-global\nSUMMARY:Legacy global calendar\nDTEND:20261201T120000Z\nEND:VEVENT\nEND:VCALENDAR\n";
            try (FileOutputStream output = new FileOutputStream(new File(context.getFilesDir(), "calendar.ics"))) {
                output.write(global.getBytes(StandardCharsets.UTF_8));
            }
            check(db.messages("").isEmpty() && db.message(501) == null && db.unread() == 0, "ordinary account cannot read cached global messages");
            java.util.List<CalendarData.Event> ordinary = CalendarStore.read(context);
            check(ordinary.size() == 1 && ordinary.get(0).uid.equals("netdisk:task:101"), "ordinary calendar contains only assigned NetDisk schedule");
            check(ordinary.get(0).course.equals("网盘任务") && ordinary.get(0).due == 1790003600000L, "NetDisk source and millisecond time are retained");
            NetDiskSession.prefs(context).edit().putBoolean("terminal_access", true).commit();
            check(db.messages("").size() == 1 && CalendarStore.read(context).size() == 1, "administrator uses the server calendar without merging a second legacy ICS cache");
            NetDiskSession.applyCapabilities(context, new JSONObject().put("terminal_access", false));
            check(db.messages("").isEmpty(), "capability revocation hides legacy cache");
            check(!new File(context.getFilesDir(), "calendar.ics").exists(), "capability downgrade physically deletes shared calendar cache");
            try (android.database.Cursor rows = db.getReadableDatabase().rawQuery("SELECT count(*) FROM messages", null)) {
                rows.moveToFirst(); check(rows.getInt(0) == 0, "capability downgrade physically deletes cached global messages");
            }
            identity(context, 12, false, "another-isolated-cookie");
            db.schedules(new JSONArray().put(new JSONObject().put("id", "netdisk:event:12").put("title", "My event").put("source", "netdisk").put("end_at", 1790000000000L)));
            runOnMainSync(() -> CookieManager.getInstance().setCookie("https://127.0.0.1:1/api/auth/refresh",
                "dcp_netdisk_session=changed-cookie; Path=/api/auth; Secure; HttpOnly"));
            CookieManager.getInstance().flush(); Thread.sleep(100);
            check(CalendarStore.read(context).isEmpty(), "unverified account switch cannot show previous user's schedules");
            NetDiskSession.observeWebLogin(context, true);
            check(!NetDiskSession.isLoggedIn(context) && db.schedules().isEmpty(), "explicit logout hides schedules and clears native identity");
            boolean tokenField = false;
            for (java.lang.reflect.Field field : TerminalDefaults.class.getDeclaredFields()) if (field.getName().equals("TOKEN")) tokenField = true;
            check(!tokenField && LegacyConnection.password().isEmpty(), "APK contains no built-in Terminal token or legacy calendar password");
            NetDiskTransportRegression.run(this, context);
            NativeCalendarRegression.run(this,context);
            CompletionRaceRegression.run(this,context);
            TimetableCalendarRegression.run(this,context);
            NativeDiskUiRegression.run(this,context);
            MessageReplyRegression.run(this,context);
            NotificationRegression.run(this,context);
            activity = startActivitySync(new Intent(context, MainActivity.class).putExtra("page", "netdisk").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            runOnMainSync(() -> {
                MainActivity main = (MainActivity)activity;
                check(textPresent(main.root, "网盘") && textPresent(main.root, "日程") && textPresent(main.root, "消息"), "bottom navigation includes the native NetDisk tab");
                check(findWeb(main.root)==null,"native NetDisk tab has no WebView or webpage");
                check(main.netDiskScreen.username!=null&&main.netDiskScreen.password!=null&&textPresent(main.root,"登录网盘"),"native login uses Android fields and device session");
            });
            result.putString("stream", "PASS: native NetDisk tab, login cookie, assigned schedules, role and account cache isolation\n");
        } catch (Throwable error) {
            outcome = Activity.RESULT_CANCELED; result.putString("stream", "FAIL: " + error + "\n"); error.printStackTrace();
        } finally {
            if (activity != null) runOnMainSync(() -> activity.finish());
            finish(outcome, result);
        }
    }

    private void publicWebView() {
        Bundle result = new Bundle(); int outcome = Activity.RESULT_OK;
        try {
            Context context = getTargetContext(); NetDiskSession.clear(context);
            runOnMainSync(() -> {
                CookieManager.getInstance().removeAllCookies(null);
                android.webkit.WebStorage.getInstance().deleteAllData();
            });
            CookieManager.getInstance().flush();
            NetDiskSession.prefs(context).edit().putString("origin", TerminalDefaults.URL).putBoolean("signed_out", false).commit();
            activity = startActivitySync(new Intent(context, MainActivity.class).putExtra("page", "netdisk").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            runOnMainSync(()->check(findWeb(((MainActivity)activity).root)==null&&textPresent(((MainActivity)activity).root,"登录网盘"),"native Android login is available without loading a page"));
            getUiAutomation().waitForIdle(1000, 10000); Thread.sleep(2000);
            android.graphics.Bitmap screen = getUiAutomation().takeScreenshot();
            try (FileOutputStream output = new FileOutputStream(new File(context.getFilesDir(), "netdisk-public-login.png"))) {
                screen.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output);
            }
            result.putString("stream", "PASS: actual native NetDisk login form with no WebView\n");
        } catch (Throwable error) {
            outcome = Activity.RESULT_CANCELED; result.putString("stream", "FAIL: " + error + "\n");
        } finally {
            if (activity != null) runOnMainSync(() -> activity.finish());
            finish(outcome, result);
        }
    }
}
