package top.dcpstudios.calendarwidget;

import android.content.Context;
import android.webkit.CookieManager;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Real delayed native response and cache-commit races, using isolated HTTPS fixtures. */
final class NetDiskRaceRegression {
    interface Work { void run() throws Exception; }
    static void identity(TerminalIntegrationInstrumentation test,Context c,boolean admin)throws Exception{
        NetDiskSession.observeWebLogin(c,true);
        test.runOnMainSync(()->CookieManager.getInstance().setCookie("https://127.0.0.1:1/api/auth/refresh","dcp_netdisk_session="+(admin?"administrator-cookie":"ordinary-cookie")+"; Path=/api/auth; Secure; HttpOnly"));
        CookieManager.getInstance().flush();Thread.sleep(100);
        NetDiskSession.observeWebLogin(c,false);NetDiskSession.ensure(c,true);
        if(admin)TerminalClient.sync(c,false);
        else NetDiskSession.guard(c,NetDiskSession.account(c),()->TerminalDb.get(c).schedules(new JSONArray().put(new JSONObject().put("id","netdisk:task:11").put("title","Ordinary current task").put("source","netdisk").put("netdisk_kind","task").put("end_at",1790003600000L))));
    }
    static void delayed(TerminalIntegrationInstrumentation test,Context c,String path,Work work,String label)throws Exception{
        identity(test,c,true);NetDiskTransportRegression.delay(path);AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread old=new Thread(()->{try{work.run();}catch(Throwable error){failure.set(error);}},"delayed-administrator-fixture");old.start();
        if(!NetDiskTransportRegression.entered.await(5,TimeUnit.SECONDS))throw new AssertionError("Old response did not enter delay");
        try{identity(test,c,false);}finally{NetDiskTransportRegression.release.countDown();}
        old.join(5000);test.check(!old.isAlive()&&failure.get() instanceof NetDiskSession.AccountChanged,label);
    }
    static void run(TerminalIntegrationInstrumentation test,Context c)throws Exception{
        delayed(test,c,"/api/mobile/terminal/snapshot",()->TerminalClient.sync(c,false),"late administrator snapshot is rejected after logout and ordinary login");
        try(android.database.Cursor rows=TerminalDb.get(c).getReadableDatabase().rawQuery("SELECT count(*) FROM messages",null)){rows.moveToFirst();test.check(rows.getInt(0)==0&&TerminalDb.get(c).schedules().size()==1&&"netdisk:task:11".equals(TerminalDb.get(c).schedules().get(0).optString("id")),"late snapshot cannot repopulate administrator messages or overwrite ordinary schedules");}
        identity(test,c,true);NetDiskSession.Reply old=TerminalClient.requestBound(c,"/snapshot",null,null);
        identity(test,c,false);boolean rejected=false;
        try{NetDiskSession.guard(c,old.account,()->TerminalDb.get(c).schedules(old.data.getJSONArray("schedules")));}catch(NetDiskSession.AccountChanged expected){rejected=true;}
        test.check(rejected&&"netdisk:task:11".equals(TerminalDb.get(c).schedules().get(0).optString("id")),"account lock rejects logout between response return and cache commit");
        delayed(test,c,"/api/mobile/terminal/snapshot",()->CalendarStore.sync(c),"late unified calendar response is rejected before cache write");
        test.check(!new File(c.getFilesDir(),"calendar.ics").exists()&&CalendarStore.read(c).size()==1,"unified calendar cannot recreate a second ICS authority for ordinary account");
        identity(test,c,true);NetDiskSession.Account stream=NetDiskSession.account(c);NetDiskSession.Reply attention=TerminalClient.requestBound(c,"/attention",null,stream);
        identity(test,c,false);boolean streamRejected=false,attentionRejected=false;
        try{TerminalClient.receive(c,new JSONObject().put("id",991).put("source","wechat").put("title","Late private message"),true,stream);}catch(NetDiskSession.AccountChanged expected){streamRejected=true;}
        try{AttentionSettings.cache(c,attention);}catch(NetDiskSession.AccountChanged expected){attentionRejected=true;}
        test.check(streamRejected&&attentionRejected&&!TerminalClient.prefs(c).contains("attention"),"old SSE and attention responses cannot repopulate the new account's cache");
        delayed(test,c,"/api/mobile/terminal/timetable",()->TimetableCloud.sync(c),"late administrator timetable response is rejected before preference write");
        test.check(!CalendarStore.prefs(c).contains("timetable")&&!CalendarStore.prefs(c).getBoolean("timetable_cloud_initialized",false),"late timetable cannot restore another account's course cache");
        identity(test,c,true);NetDiskTransportRegression.delay("/api/auth/refresh");AtomicReference<Throwable> failedRefresh=new AtomicReference<>();
        Thread refresh=new Thread(()->{try{NetDiskSession.ensure(c,true);}catch(Throwable error){failedRefresh.set(error);}},"delayed-refresh-fixture");refresh.start();
        if(!NetDiskTransportRegression.entered.await(5,TimeUnit.SECONDS))throw new AssertionError("Refresh did not enter delay");
        long started=android.os.SystemClock.elapsedRealtime();test.runOnMainSync(()->NetDiskSession.observeWebLogin(c,true));
        test.check(android.os.SystemClock.elapsedRealtime()-started<1000&&refresh.isAlive(),"UI logout completes without waiting for an in-flight refresh network request");
        test.runOnMainSync(()->CookieManager.getInstance().setCookie("https://127.0.0.1:1/api/auth/refresh","dcp_netdisk_session=ordinary-cookie; Path=/api/auth; Secure; HttpOnly"));CookieManager.getInstance().flush();Thread.sleep(100);NetDiskSession.observeWebLogin(c,false);
        NetDiskTransportRegression.release.countDown();refresh.join(5000);
        test.check(!refresh.isAlive()&&failedRefresh.get() instanceof NetDiskSession.AccountChanged&&NetDiskSession.prefs(c).getLong("user_id",0)==0&&NetDiskSession.cookie(c).contains("ordinary-cookie"),"late refresh cannot restore administrator identity or overwrite the new browser cookie");
        NetDiskSession.ensure(c,true);
        test.check(NetDiskSession.prefs(c).getLong("user_id",0)==11&&!NetDiskSession.canTerminal(c),"ordinary login succeeds after rejecting the old refresh");
        TerminalClient.sync(c,false);NetDiskTransportRegression.wrongClaimNext=true;boolean wrongClaim=false;
        try{TerminalClient.sync(c,false);}catch(NetDiskSession.AccountChanged expected){wrongClaim=true;}
        test.check(wrongClaim&&TerminalDb.get(c).schedules().size()==1&&"netdisk:task:11".equals(TerminalDb.get(c).schedules().get(0).optString("id")),"snapshot with another netdisk_user_id cannot enter current user's cache");
    }
}
