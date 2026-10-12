package top.dcpstudios.calendarwidget;

import android.content.Context;
import android.webkit.CookieManager;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLConnection;
import java.net.URLStreamHandler;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/** Exercises the unchanged native client through deterministic HTTPS responses. */
final class NetDiskTransportRegression {
    static int refreshes, forbiddenRequests;
    static boolean expireNext;
    static boolean wrongClaimNext;
    static boolean forced,sourceCompleted,forceOffline;static int forceWrites;
    static JSONObject timetableData;
    static volatile JSONObject replyBody;
    static volatile int replyWrites;
    static volatile boolean replyUncertain;
    static volatile String delayPath;
    static java.util.concurrent.CountDownLatch entered, release;
    static void delay(String path){delayPath=path;entered=new java.util.concurrent.CountDownLatch(1);release=new java.util.concurrent.CountDownLatch(1);}

    static void install() {
        URL.setURLStreamHandlerFactory(protocol -> "https".equals(protocol) ? new URLStreamHandler() {
            @Override protected URLConnection openConnection(URL url) { return new Response(url); }
        } : null);
    }

    static final class Response extends HttpURLConnection {
        private JSONObject payload;
        private String calendar;
        private int code = 200;
        private final ByteArrayOutputStream posted=new ByteArrayOutputStream();
        Response(URL url) { super(url); }
        @Override public void connect() {}
        @Override public void disconnect() {}
        @Override public boolean usingProxy() { return false; }
        @Override public OutputStream getOutputStream() { return posted; }
        @Override public Map<String, List<String>> getHeaderFields() { return Collections.emptyMap(); }
        private void prepare() {
            if (payload != null || calendar != null) return;
            try {
                String path = java.net.URLDecoder.decode(url.getPath(),"UTF-8");
                if(path.equals(delayPath)){
                    entered.countDown();
                    if(!release.await(10,java.util.concurrent.TimeUnit.SECONDS))throw new AssertionError("Delayed response was not released");
                    delayPath=null;
                }
                if (path.equals("/api/auth/refresh")) {
                    refreshes++;
                    String cookie = getRequestProperty("Cookie");
                    long user = cookie != null && cookie.contains("administrator-cookie") ? 44 : 11;
                    payload = new JSONObject().put("ok", true).put("data", new JSONObject().put("access_token", "isolated-native-access-" + user)
                        .put("user", new JSONObject().put("id", user).put("username", "fixture-" + user).put("role_system", user == 44 ? "super_admin" : "user")));
                } else if (expireNext) {
                    expireNext = false; code = 401; payload = new JSONObject().put("ok", false);
                } else if(path.equals("/api/mobile/terminal/replies/capabilities")) {
                    boolean allowed=url.getQuery()==null||!java.net.URLDecoder.decode(url.getQuery(),"UTF-8").contains("readonly");
                    payload=new JSONObject().put("ok",true).put("data",new JSONObject().put("reply_enabled",allowed).put("target_label","fixture").put("reason","此会话暂不能回复"));
                } else if(path.equals("/api/mobile/terminal/replies/send")) {
                    replyBody=new JSONObject(posted.toString("UTF-8"));replyWrites++;payload=new JSONObject().put("ok",true).put("data",new JSONObject().put("status",replyUncertain?"uncertain":"confirmed"));
                } else if(path.startsWith("/api/mobile/terminal/replies/")&&path.endsWith("/status")) {
                    payload=new JSONObject().put("ok",true).put("data",new JSONObject().put("status","confirmed"));
                } else if(path.equals("/api/mobile/terminal/desktop/messages")) {
                    payload=new JSONObject().put("ok",true).put("data",new JSONObject().put("items",new JSONArray()).put("more",false));
                } else if(path.startsWith("/api/mobile/terminal/schedules/")) {
                    if(forceOffline){code=503;payload=new JSONObject().put("ok",false).put("error",new JSONObject().put("message","Offline fixture"));}
                    else{forced=new JSONObject(posted.toString("UTF-8")).getBoolean("forced_completed");forceWrites++;payload=new JSONObject().put("ok",true).put("data",new JSONObject().put("schedule",schedule(getRequestProperty("Authorization").endsWith("44")?44:11)));}
                } else if(path.equals("/api/mobile/terminal/schedules")) {
                    boolean admin=getRequestProperty("Authorization").endsWith("44");payload=new JSONObject().put("ok",true).put("data",new JSONObject().put("netdisk_user_id",admin?44:11).put("schedules",new JSONArray().put(schedule(admin?44:11))));
                } else if(path.equals("/api/projects")) {
                    payload=new JSONObject().put("ok",true).put("data",new JSONObject().put("items",new JSONArray()).put("total",0));
                } else if (path.equals("/api/mobile/terminal/snapshot")) {
                    boolean admin = getRequestProperty("Authorization").endsWith("44");
                    JSONArray schedules = new JSONArray().put(schedule(admin?44:11));
                    JSONArray messages = new JSONArray();
                    if (admin) messages.put(new JSONObject().put("id", 880).put("source", "wechat").put("title", "Admin fixture").put("body", "fixture").put("occurred_at", 0));
                    payload = new JSONObject().put("ok", true).put("data", new JSONObject().put("netdisk_user_id",wrongClaimNext?999:(admin?44:11)).put("terminal_access", admin).put("schedules", schedules)
                        .put("messages", messages).put("cursor", 880).put("llm", new JSONObject()));
                    wrongClaimNext=false;
                } else if (path.equals("/api/mobile/terminal/attention")) {
                    payload = new JSONObject().put("ok", true).put("data", new JSONObject());
                } else if (path.equals("/api/mobile/terminal/timetable")) {
                    payload = new JSONObject().put("ok", true).put("data", new JSONObject().put("data", timetableData==null?JSONObject.NULL:timetableData).put("revision", timetableData==null?0:17));
                } else if(path.equals("/api/mobile/terminal/calendar")) {
                    calendar="BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:late-administrator-calendar\nSUMMARY:Administrator only calendar\nDTEND:20261201T120000Z\nEND:VEVENT\nEND:VCALENDAR\n";
                } else {
                    forbiddenRequests++; code = 403; payload = new JSONObject().put("ok", false).put("error", new JSONObject().put("message", "Denied fixture"));
                }
            } catch (Exception error) { throw new IllegalStateException(error); }
        }
        @Override public int getResponseCode() { prepare(); return code; }
        @Override public InputStream getInputStream() { prepare(); return new ByteArrayInputStream((calendar==null?payload.toString():calendar).getBytes(StandardCharsets.UTF_8)); }
        @Override public InputStream getErrorStream() { return getInputStream(); }
    }
    static JSONObject schedule(long user)throws Exception{return new JSONObject().put("id","netdisk:task:"+user).put("title","My assigned fixture").put("source","netdisk").put("netdisk_kind","task").put("start_at",1790000000000L).put("end_at",1790003600000L).put("forced_completed",forced).put("source_completed",sourceCompleted).put("completed",forced||sourceCompleted).put("status",forced||sourceCompleted?"completed":"active");}

    static void run(TerminalIntegrationInstrumentation instrumentation, Context context) throws Exception {
        install();
        NetDiskSession.clear(context); NetDiskSession.observeWebLogin(context, false);
        instrumentation.runOnMainSync(() -> CookieManager.getInstance().setCookie("https://127.0.0.1:1/api/auth/refresh",
            "dcp_netdisk_session=ordinary-cookie; Path=/api/auth; Secure; HttpOnly"));
        CookieManager.getInstance().flush(); Thread.sleep(100);
        TerminalClient.sync(context, false);
        instrumentation.check(NetDiskSession.prefs(context).getLong("user_id", 0) == 11
            && TerminalDb.get(context).schedules().get(0).optString("id").equals("netdisk:task:11"), "native cookie refresh imports only the current user's assigned task");
        TimetableCloud.sync(context); AttentionCards.opened(context);
        TerminalClient.IO.submit(() -> {}).get();
        instrumentation.check(!NetDiskSession.canTerminal(context) && forbiddenRequests == 0, "ordinary sync and screen actions never query global attention, messages or timetable");
        int before = refreshes; expireNext = true; TerminalClient.sync(context, false);
        instrumentation.check(refreshes == before + 1, "expired native access token refreshes once and retries the request");
        instrumentation.runOnMainSync(() -> CookieManager.getInstance().setCookie("https://127.0.0.1:1/api/auth/refresh",
            "dcp_netdisk_session=administrator-cookie; Path=/api/auth; Secure; HttpOnly"));
        CookieManager.getInstance().flush(); Thread.sleep(100);
        TerminalClient.sync(context, false);
        instrumentation.check(NetDiskSession.prefs(context).getLong("user_id", 0) == 44 && NetDiskSession.canTerminal(context)
            && TerminalDb.get(context).messages("").size() == 1, "server-authorized admin identity can import existing Terminal data");
        instrumentation.check(TerminalDb.get(context).schedules().size() == 1
            && TerminalDb.get(context).schedules().get(0).optString("id").equals("netdisk:task:44"), "verified account switch removes the preceding user's assigned task");
        NetDiskRaceRegression.run(instrumentation,context);
        NetDiskSession.observeWebLogin(context, true);
    }
}
