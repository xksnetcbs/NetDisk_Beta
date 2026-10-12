package top.dcpstudios.calendarwidget;

import android.content.Context;
import android.content.SharedPreferences;
import android.webkit.CookieManager;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Native login persists its HttpOnly device cookie; access JWTs stay in memory. */
final class NetDiskSession {
    private static String accessToken = "", cookieDigest = "";
    private static long refreshedAt;
    private static long generation;
    private static final Object REFRESH_LOCK=new Object();
    interface AccountAction { void run() throws Exception; }
    static final class Account {
        final long generation, userId; final String cookieDigest, origin;
        Account(long generation, long userId, String cookieDigest, String origin) { this.generation=generation;this.userId=userId;this.cookieDigest=cookieDigest;this.origin=origin; }
    }
    static final class AuthorizedConnection {
        final HttpURLConnection connection; final Account account;
        AuthorizedConnection(HttpURLConnection connection, Account account) { this.connection=connection;this.account=account; }
    }
    static final class Reply {
        final JSONObject data; final Account account;
        Reply(JSONObject data, Account account) { this.data=data;this.account=account; }
    }
    static final class AccountChanged extends IOException { AccountChanged() { super("账号已切换，已忽略旧账号响应"); } }

    private static boolean current(Context c, Account account) {
        try { String cookies=cookie(c);return account!=null && account.generation==generation && account.userId==prefs(c).getLong("user_id",0)
            && account.origin.equals(base(c)) && !prefs(c).getBoolean("signed_out",false)
            && account.cookieDigest.equals(prefs(c).getString("session_cookie_digest",""))
            && account.cookieDigest.equals(digest(cookies)) && !cookies.isEmpty(); }
        catch(Exception ignored) { return false; }
    }
    static synchronized Account account(Context c) throws AccountChanged {
        if(!isLoggedIn(c))throw new AccountChanged();
        return new Account(generation,prefs(c).getLong("user_id",0),prefs(c).getString("session_cookie_digest",""),base(c));
    }
    static synchronized void guard(Context c, Account account, AccountAction action) throws Exception {
        if(!current(c,account))throw new AccountChanged();
        action.run();
    }
    static void ui(MainActivity activity, Account account, AccountAction action) {
        activity.runOnUiThread(()->{try{guard(activity,account,action);}catch(AccountChanged ignored){}catch(Exception error){activity.error(error);}});
    }
    static SharedPreferences prefs(Context c) { return c.getSharedPreferences("netdisk", 0); }

    static String base(Context c) {
        return prefs(c).getString("origin", TerminalDefaults.URL).replaceAll("/+$", "");
    }

    static String validateOrigin(String value) throws Exception {
        URL url = new URL(value.trim());
        if (!"https".equalsIgnoreCase(url.getProtocol()) || url.getHost().isEmpty()
            || url.getUserInfo() != null || url.getQuery() != null || url.getRef() != null
            || (!url.getPath().isEmpty() && !"/".equals(url.getPath()))) {
            throw new IOException("请输入 HTTPS 网盘站点地址，不带路径或账号信息");
        }
        return url.getProtocol() + "://" + url.getAuthority();
    }

    static String cookie(Context c) {
        String value = CookieManager.getInstance().getCookie(base(c) + "/api/auth/refresh");
        if (value == null) return "";
        for (String part : value.split(";")) {
            if (part.trim().startsWith("dcp_netdisk_session=")) return value;
        }
        return "";
    }

    static boolean isLoggedIn(Context c) {
        try {
            String cookies = cookie(c);
            return !prefs(c).getBoolean("signed_out", false) && prefs(c).getLong("user_id", 0) > 0
                && !cookies.isEmpty() && digest(cookies).equals(prefs(c).getString("session_cookie_digest", ""));
        } catch (Exception ignored) { return false; }
    }

    static boolean canTerminal(Context c) {
        return isLoggedIn(c) && prefs(c).getBoolean("terminal_access", false);
    }

    static String userName(Context c) { return prefs(c).getString("username", ""); }

    static String digest(String value) throws Exception {
        byte[] bytes = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
        StringBuilder result = new StringBuilder();
        for (byte b : bytes) result.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return result.toString();
    }

    static synchronized void clear(Context c) {
        generation++;
        accessToken = ""; cookieDigest = ""; refreshedAt = 0;
        prefs(c).edit().remove("user_id").remove("username").remove("session_cookie_digest").putBoolean("terminal_access", false).commit();
        clearAccountData(c);
        c.stopService(new android.content.Intent(c, TerminalService.class));
    }

    static void clearAccountData(Context c) {
        FileCache.clear(c);
        MessageReply.clearAccountData(c);
        NetDiskPreview.clearAccountData();
        TerminalDb.get(c).clearAccountData();
        CalendarStore.clearCache(c);
        TerminalClient.prefs(c).edit().remove("initialized").remove("cursor").remove("attention")
            .remove("llm").remove("arrived").remove("cards_seen").remove("error")
            .putLong("revision", System.currentTimeMillis()).commit();
        SharedPreferences.Editor calendar = CalendarStore.prefs(c).edit().remove("user").remove("password").remove("url").remove("lastSync").remove("error");
        for (String key : new String[]{"timetable", "timetable_previous", "timetable_revision", "timetable_dirty",
            "timetable_cloud_initialized", "timetable_conflict", "timetable_sync_status"}) calendar.remove(key);
        for (String key : CalendarStore.prefs(c).getAll().keySet()) {
            if (key.startsWith("archive:") || key.startsWith("force:") || key.startsWith("force_pending:") || key.startsWith("event_category_")) calendar.remove(key);
        }
        calendar.commit();
        android.app.NotificationManager notifications = (android.app.NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);
        if (notifications != null) notifications.cancelAll();
    }

    static synchronized void observeWebLogin(Context c, boolean signedOut) {
        boolean before = prefs(c).getBoolean("signed_out", false);
        prefs(c).edit().putBoolean("signed_out", signedOut).commit();
        if (signedOut && (!before || prefs(c).getLong("user_id", 0) > 0)) clear(c);
    }

    static void login(Context c, String username, String password) throws Exception {
        final long epoch; final String origin;
        synchronized(NetDiskSession.class) {
            clear(c); prefs(c).edit().putBoolean("signed_out",false).commit();
            epoch=generation; origin=base(c);
            CookieManager.getInstance().setCookie(origin+"/api/auth/refresh","dcp_netdisk_session=; Path=/api/auth; Secure; HttpOnly; Max-Age=0");
            CookieManager.getInstance().flush();
        }
        HttpURLConnection connection=connection(origin,"/api/auth/login","POST");
        connection.setDoOutput(true);connection.setRequestProperty("Content-Type","application/json");
        try {
            try(OutputStream output=connection.getOutputStream()) { output.write(new JSONObject().put("username",username.trim()).put("password",password).toString().getBytes(StandardCharsets.UTF_8)); }
            JSONObject data=read(connection);
            synchronized(NetDiskSession.class) {
                if(epoch!=generation||!origin.equals(base(c))||prefs(c).getBoolean("signed_out",false))throw new AccountChanged();
                saveCookies(origin,connection);
                String cookies=cookie(c);if(cookies.isEmpty())throw new IOException("服务未返回设备登录会话");
                JSONObject user=data.getJSONObject("user");cookieDigest=digest(cookies);
                accessToken=data.getString("access_token");refreshedAt=System.currentTimeMillis();
                prefs(c).edit().putLong("user_id",user.getLong("id")).putString("username",user.optString("username"))
                    .putString("session_cookie_digest",cookieDigest).putBoolean("terminal_access",false).commit();
            }
        } finally { connection.disconnect(); }
    }

    static void logout(Context c) throws Exception {
        final String cookies,origin;
        synchronized(NetDiskSession.class) {
            cookies=cookie(c);origin=base(c);
            observeWebLogin(c,true);
            CookieManager.getInstance().setCookie(origin+"/api/auth/refresh","dcp_netdisk_session=; Path=/api/auth; Secure; HttpOnly; Max-Age=0");
            CookieManager.getInstance().flush();
        }
        revoke(origin,cookies);
    }
    static void revoke(String origin,String cookies)throws Exception {
        if(cookies.isEmpty())return;
        HttpURLConnection connection=connection(origin,"/api/auth/logout","POST");
        connection.setRequestProperty("Cookie",cookies);connection.setRequestProperty("X-DCP-Session","1");
        try { read(connection); } finally { connection.disconnect(); }
    }

    private static void saveCookies(String origin,HttpURLConnection connection) {
        for(java.util.Map.Entry<String,java.util.List<String>> header:connection.getHeaderFields().entrySet()) {
            if(header.getKey()!=null&&"Set-Cookie".equalsIgnoreCase(header.getKey()))for(String value:header.getValue()) {
                if(value.startsWith("dcp_netdisk_session="))CookieManager.getInstance().setCookie(origin+"/api/auth/refresh",value);
            }
        }
        CookieManager.getInstance().flush();
    }

    private static boolean refreshCurrent(Context c,long epoch,String origin,String digest)throws Exception{
        return epoch==generation&&origin.equals(base(c))&&!prefs(c).getBoolean("signed_out",false)&&digest.equals(digest(cookie(c)));
    }
    static void ensure(Context c, boolean force) throws Exception {
        synchronized(REFRESH_LOCK){
            final String cookies,currentDigest,origin;final long epoch;
            synchronized(NetDiskSession.class){
                cookies=cookie(c);
                if(cookies.isEmpty()||prefs(c).getBoolean("signed_out",false)){
                    if(!accessToken.isEmpty()||prefs(c).getLong("user_id",0)>0)clear(c);
                    throw new IOException("请在网盘选项卡登录账号");
                }
                currentDigest=digest(cookies);origin=base(c);epoch=generation;
                if(!force&&!accessToken.isEmpty()&&currentDigest.equals(cookieDigest)&&isLoggedIn(c)
                    &&System.currentTimeMillis()-refreshedAt<5*60*1000)return;
            }
            // Network I/O uses a separate single-flight lock. Logout and UI cache
            // access never wait for this connection to return.
            HttpURLConnection connection=connection(origin,"/api/auth/refresh","POST");
            connection.setRequestProperty("Cookie",cookies);connection.setRequestProperty("X-DCP-Session","1");
            JSONObject data;
            try{data=read(connection);}
            catch(Unauthorized e){synchronized(NetDiskSession.class){if(!refreshCurrent(c,epoch,origin,currentDigest))throw new AccountChanged();clear(c);}throw e;}
            finally{connection.disconnect();}
            synchronized(NetDiskSession.class){
                // Old refreshes cannot replace a newer native login or commit
                // tokens after logout/site changes.
                if(!refreshCurrent(c,epoch,origin,currentDigest))throw new AccountChanged();
                JSONObject user=data.getJSONObject("user");
                long nextUser=user.getLong("id"),oldUser=prefs(c).getLong("user_id",0);
                if(oldUser!=nextUser||!currentDigest.equals(cookieDigest)&&!cookieDigest.isEmpty()){generation++;clearAccountData(c);}
                boolean administrator="super_admin".equals(user.optString("role_system"));
                if(!administrator&&prefs(c).getBoolean("terminal_access",false)){generation++;clearAccountData(c);}
                accessToken=data.getString("access_token");cookieDigest=currentDigest;refreshedAt=System.currentTimeMillis();
                prefs(c).edit().putLong("user_id",nextUser).putString("username",user.optString("username")).putString("session_cookie_digest",cookieDigest)
                    .putBoolean("terminal_access",administrator&&oldUser==nextUser&&prefs(c).getBoolean("terminal_access",false)).commit();
            }
        }
    }

    static HttpURLConnection connection(Context c, String path, String method) throws IOException {
        return connection(base(c),path,method);
    }
    private static HttpURLConnection connection(String origin,String path,String method)throws IOException{
        URL url = new URL(origin + path);
        if (!"https".equals(url.getProtocol())) throw new IOException("网盘服务需要 HTTPS");
        HttpURLConnection connection = (HttpURLConnection)url.openConnection();
        connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(10000);
        connection.setReadTimeout(20000); connection.setRequestMethod(method);
        return connection;
    }

    static HttpURLConnection open(Context c, String path, String method) throws Exception {
        return openBound(c,path,method,null).connection;
    }
    static AuthorizedConnection openBound(Context c, String path, String method, Account expected) throws Exception {
        if(expected!=null)guard(c,expected,()->{});
        ensure(c, false);
        synchronized(NetDiskSession.class){
        if(expected!=null && !current(c,expected))throw new AccountChanged();
        Account account=account(c);
        HttpURLConnection connection = connection(c, path, method);
        connection.setRequestProperty("Authorization", "Bearer " + accessToken);
        return new AuthorizedConnection(connection,account);
        }
    }

    static String authorization(Context c) throws Exception {
        ensure(c, false);synchronized(NetDiskSession.class){account(c);return "Bearer " + accessToken;}
    }

    static JSONObject request(Context c, String path, JSONObject body) throws Exception {
        return requestBound(c,path,body,null).data;
    }
    static Reply requestBound(Context c, String path, JSONObject body, Account expected) throws Exception {
        return requestMethod(c,path,body==null?"GET":"POST",body,expected);
    }
    static Reply requestMethod(Context c,String path,String method,JSONObject body,Account expected)throws Exception {
        Account requestAccount=expected;
        for (int attempt = 0; attempt < 2; attempt++) {
            AuthorizedConnection opened=openBound(c,path,method,requestAccount);
            Account bound=opened.account;
            if(requestAccount==null)requestAccount=bound;
            HttpURLConnection connection = opened.connection;
            if (path.endsWith("/conversations/summary")) connection.setReadTimeout(60000);
            try {
                if (body != null) {
                    connection.setDoOutput(true); connection.setRequestProperty("Content-Type", "application/json");
                    try (OutputStream output = connection.getOutputStream()) { output.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
                }
                JSONObject value=read(connection);
                guard(c,bound,()->{});
                return new Reply(value,bound);
            } catch (Unauthorized e) {
                synchronized(NetDiskSession.class){
                    if(!current(c,bound))throw new AccountChanged();
                    if(attempt==1){clear(c);throw e;}
                }
                ensure(c,true);
                guard(c,bound,()->{});
            } finally { connection.disconnect(); }
        }
        throw new IOException("请重新登录网盘账号");
    }

    static JSONObject read(HttpURLConnection connection) throws Exception {
        int code = connection.getResponseCode();
        InputStream stream = code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream();
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        if (stream != null) try (InputStream input = stream) {
            byte[] buffer = new byte[8192]; int n;
            while ((n = input.read(buffer)) != -1) {
                bytes.write(buffer, 0, n);
                if (bytes.size() > 24 * 1024 * 1024) throw new IOException("服务返回数据过大");
            }
        }
        if (code == 401) throw new Unauthorized();
        JSONObject value;
        try{value=new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));}
        catch(org.json.JSONException invalid){throw new IOException("服务返回 HTTP "+code+"，请稍后重试");}
        if (code < 200 || code >= 300 || value.has("ok") && !value.optBoolean("ok")) {
            JSONObject error = value.optJSONObject("error");
            throw new IOException(error == null ? value.optString("error", "HTTP " + code) : error.optString("message", "操作失败"));
        }
        return value.has("ok") && value.optJSONObject("data")!=null ? value.getJSONObject("data") : value;
    }

    static synchronized void applyCapabilities(Context c, JSONObject snapshot) {
        boolean allowed = snapshot.optBoolean("terminal_access", false);
        if (prefs(c).getBoolean("terminal_access", false) && !allowed) { generation++;clearAccountData(c); }
        prefs(c).edit().putBoolean("terminal_access", allowed).commit();
    }

    private static class Unauthorized extends IOException { Unauthorized() { super("登录已失效，请在网盘重新登录"); } }
}
