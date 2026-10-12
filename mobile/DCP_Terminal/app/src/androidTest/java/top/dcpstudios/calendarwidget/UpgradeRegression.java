package top.dcpstudios.calendarwidget;
import android.app.Activity;
import android.os.Bundle;
import android.content.Context;
import android.webkit.CookieManager;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
/** Two phases run across adb install -r, including the actual 1.5.0 override method. */
final class UpgradeRegression {
    private static JSONObject file(Context c,String name)throws Exception{ByteArrayOutputStream bytes=new ByteArrayOutputStream();try(InputStream input=new FileInputStream(new File(c.getFilesDir(),name))){byte[] block=new byte[4096];int n;while((n=input.read(block))!=-1)bytes.write(block,0,n);}return new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8));}
    private static JSONObject read(HttpURLConnection h)throws Exception{int code=h.getResponseCode();if(code<200||code>=300)throw new IOException("Private upgrade fixture request failed");ByteArrayOutputStream bytes=new ByteArrayOutputStream();try(InputStream input=h.getInputStream()){byte[] block=new byte[8192];int n;while((n=input.read(block))!=-1)bytes.write(block,0,n);}JSONObject value=new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8));return value.optJSONObject("data")==null?value:value.getJSONObject("data");}
    private static void seed(TerminalIntegrationInstrumentation test,Context c)throws Exception{
        JSONObject fixture=file(c,"netdisk-merge-qa.json"),account=fixture.getJSONObject("accounts").getJSONObject("ordinary");String origin=fixture.getString("url");NetDiskSession.clear(c);NetDiskSession.prefs(c).edit().putString("origin",origin).putBoolean("signed_out",false).commit();
        HttpURLConnection login=(HttpURLConnection)new URL(origin+"/api/auth/login").openConnection();login.setConnectTimeout(10000);login.setReadTimeout(20000);login.setRequestMethod("POST");login.setDoOutput(true);login.setRequestProperty("Content-Type","application/json");JSONObject identity;
        try{try(OutputStream out=login.getOutputStream()){out.write(new JSONObject().put("username",account.getString("username")).put("password",account.getString("password")).toString().getBytes(StandardCharsets.UTF_8));}identity=read(login);
            for(Map.Entry<String,List<String>> field:login.getHeaderFields().entrySet())if(field.getKey()!=null&&field.getKey().equalsIgnoreCase("Set-Cookie"))for(String value:field.getValue())if(value.startsWith("dcp_netdisk_session="))test.runOnMainSync(()->CookieManager.getInstance().setCookie(origin+"/api/auth/refresh",value));
        }finally{login.disconnect();}CookieManager.getInstance().flush();Thread.sleep(200);long user=identity.getJSONObject("user").getLong("id");
        NetDiskSession.prefs(c).edit().putLong("user_id",user).putString("username",identity.getJSONObject("user").optString("username")).putBoolean("terminal_access",false).putString("session_cookie_digest",NetDiskSession.digest(NetDiskSession.cookie(c))).commit();
        HttpURLConnection schedules=(HttpURLConnection)new URL(origin+"/api/mobile/terminal/schedules").openConnection();schedules.setRequestProperty("Authorization","Bearer "+identity.getString("access_token"));JSONArray rows;try{rows=read(schedules).getJSONArray("schedules");}finally{schedules.disconnect();}
        String uid=null;for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if("netdisk".equals(row.optString("source"))&&row.optBoolean("editable")&&!row.optBoolean("forced_completed")){uid=row.getString("id");break;}}
        if(uid==null)throw new AssertionError("An unfinished personal QA event is required for upgrade migration");
        TaskOverrides.complete(c,uid,true);test.check(CalendarStore.prefs(c).getBoolean("force:"+uid,false),"actual installed 1.5.0 override writes its original persistent force marker");
        try(OutputStream output=new FileOutputStream(new File(c.getFilesDir(),"native-upgrade-check.json"))){output.write(new JSONObject().put("user_id",user).put("uid",uid).toString().getBytes(StandardCharsets.UTF_8));}
    }
    private static void verify(TerminalIntegrationInstrumentation test,Context c)throws Exception{
        JSONObject expected=file(c,"native-upgrade-check.json");String uid=expected.getString("uid");test.check(NetDiskSession.prefs(c).getLong("user_id",0)==expected.getLong("user_id")&&CalendarStore.prefs(c).getBoolean("force:"+uid,false),"APK install -r preserves the existing device session and force preferences");
        NetDiskSession.ensure(c,true);TerminalClient.sync(c,false);boolean completed=false;for(JSONObject row:TerminalDb.get(c).schedules())if(uid.equals(row.optString("id")))completed=row.optBoolean("forced_completed")&&row.optBoolean("completed");
        test.check(completed&&!CalendarStore.prefs(c).contains("force:"+uid),"1.6.0 automatically migrates the installed 1.5.0 marker to its original account on the server");
        TerminalDb.get(c).clearAccountData();TerminalClient.sync(c,false);completed=false;for(CalendarData.Event e:CalendarStore.read(c))if(uid.equals(e.uid))completed=e.forcedCompleted&&e.completed;test.check(completed,"migrated completion is recovered from server after deleting native cache");
        NetDiskSession.requestMethod(c,"/api/mobile/terminal/schedules/"+URLEncoder.encode(uid,"UTF-8"),"POST",new JSONObject().put("forced_completed",false),NetDiskSession.account(c));NetDiskSession.logout(c);new File(c.getFilesDir(),"native-upgrade-check.json").delete();new File(c.getFilesDir(),"netdisk-merge-qa.json").delete();
    }
    static void run(TerminalIntegrationInstrumentation test,String phase){Bundle result=new Bundle();int outcome=Activity.RESULT_OK;
        try{if("upgrade-seed".equals(phase))seed(test,test.getTargetContext());else verify(test,test.getTargetContext());result.putString("stream","PASS: real "+phase+" installed force completion migration\n");}
        catch(Throwable error){outcome=Activity.RESULT_CANCELED;result.putString("stream","FAIL: "+phase+" ("+error.getClass().getSimpleName()+")\n");}test.finish(outcome,result);
    }
}
