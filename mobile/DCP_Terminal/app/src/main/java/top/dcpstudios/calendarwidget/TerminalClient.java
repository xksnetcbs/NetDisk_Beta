package top.dcpstudios.calendarwidget;

import android.content.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;

final class TerminalClient {
    static final ExecutorService IO=Executors.newSingleThreadExecutor();
    static SharedPreferences prefs(Context c){return c.getSharedPreferences("terminal",0);}
    static String base(Context c){return NetDiskSession.base(c)+"/api/mobile/terminal";}
    static HttpURLConnection open(Context c,String path,String method)throws Exception{
        return NetDiskSession.open(c,"/api/mobile/terminal"+path,method);
    }
    static JSONObject request(Context c,String path,JSONObject body)throws Exception{
        return NetDiskSession.request(c,"/api/mobile/terminal"+path,body);
    }
    static NetDiskSession.Reply requestBound(Context c,String path,JSONObject body,NetDiskSession.Account account)throws Exception{
        return NetDiskSession.requestBound(c,"/api/mobile/terminal"+path,body,account);
    }
    static synchronized void receive(Context c,JSONObject m,boolean notify)throws Exception{
        receive(c,m,notify,NetDiskSession.account(c));
    }
    static synchronized void receive(Context c,JSONObject m,boolean notify,NetDiskSession.Account account)throws Exception{
        NetDiskSession.guard(c,account,()->{
        if(!NetDiskSession.canTerminal(c))return;
        boolean added=TerminalDb.get(c).put(m);long id=m.getLong("id");long cursor=prefs(c).getLong("cursor",0);
        if(id>cursor)prefs(c).edit().putLong("cursor",id).commit();
        if(added&&notify&&m.optBoolean("notify",true)&&!m.optBoolean("is_read")&&prefs(c).getBoolean("notifications",false))TerminalNotifications.show(c,m);
        prefs(c).edit().putLong("revision",System.currentTimeMillis()).apply();CalendarWidget.renderAll(c);
        });
    }
    static synchronized void sync(Context c,boolean notify)throws Exception{
        NetDiskSession.Reply first=requestBound(c,"/snapshot",null,null);JSONObject initial=first.data;
        if(initial.getLong("netdisk_user_id")!=first.account.userId)throw new NetDiskSession.AccountChanged();
        NetDiskSession.Account[] current={first.account};
        NetDiskSession.guard(c,first.account,()->{
            NetDiskSession.applyCapabilities(c,initial);
            TerminalDb.get(c).schedules(initial.optJSONArray("schedules")==null?new JSONArray():initial.getJSONArray("schedules"));
            current[0]=NetDiskSession.account(c);
        });
        final NetDiskSession.Account account=current[0];
        if(TaskOverrides.flush(c,account)){
            NetDiskSession.Reply calendar=requestBound(c,"/schedules",null,account);
            if(calendar.data.getLong("netdisk_user_id")!=account.userId)throw new NetDiskSession.AccountChanged();
            NetDiskSession.guard(c,account,()->{initial.put("schedules",calendar.data.getJSONArray("schedules"));TerminalDb.get(c).schedules(calendar.data.getJSONArray("schedules"));});
        }
        if(!NetDiskSession.canTerminal(c)||initial.optBoolean("upstream_unavailable")){
            NetDiskSession.guard(c,account,()->{
            prefs(c).edit().putLong("lastSync",System.currentTimeMillis()).remove("error").putLong("revision",System.currentTimeMillis()).apply();
            CalendarStore.prefs(c).edit().putLong("lastSync",System.currentTimeMillis()).remove("error").apply();
            CalendarWidget.renderAll(c);});return;
        }
        AttentionSettings.cache(c,requestBound(c,"/attention",null,account));
        try{TimetableCloud.sync(c,account);}catch(NetDiskSession.AccountChanged e){throw e;}catch(Exception e){NetDiskSession.guard(c,account,()->CalendarStore.prefs(c).edit().putString("timetable_sync_status","课表云端同步失败 · 本地已保留").apply());}
        flushReads(c,account);
        if(!prefs(c).getBoolean("initialized",false)){
            NetDiskSession.guard(c,account,()->{
            JSONObject snapshot=initial;JSONArray messages=snapshot.getJSONArray("messages");
            exclude(c,snapshot);
            // A new installation imports history silently, then starts receiving from its durable cursor.
            TerminalDb.get(c).putAll(messages);
            TerminalDb.get(c).schedules(snapshot.getJSONArray("schedules"));
            prefs(c).edit().putLong("cursor",snapshot.getLong("cursor")).putBoolean("initialized",true).putString("llm",snapshot.getJSONObject("llm").toString()).commit();
            });
        }else{
            boolean more;do{NetDiskSession.Reply pageReply=requestBound(c,"/messages?after="+prefs(c).getLong("cursor",0),null,account);JSONObject page=pageReply.data;JSONArray messages=page.getJSONArray("messages");for(int i=0;i<messages.length();i++)receive(c,messages.getJSONObject(i),notify,pageReply.account);more=page.optBoolean("more");}while(more);
            NetDiskSession.guard(c,account,()->{
            JSONObject snapshot=initial;
            exclude(c,snapshot);
            JSONArray history=snapshot.getJSONArray("messages");long cursor=prefs(c).getLong("cursor",0);
            // Refresh read/LLM status only for messages already received; newer IDs still need notifications.
            JSONArray known=new JSONArray();for(int i=0;i<history.length();i++){JSONObject row=history.getJSONObject(i);if(row.getLong("id")<=cursor)known.put(row);}TerminalDb.get(c).putAll(known);
            TerminalDb.get(c).schedules(snapshot.getJSONArray("schedules"));
            });
        }
        NetDiskSession.guard(c,account,()->{prefs(c).edit().putLong("lastSync",System.currentTimeMillis()).remove("error").remove("error_since").putLong("revision",System.currentTimeMillis()).apply();CalendarStore.prefs(c).edit().putLong("lastSync",System.currentTimeMillis()).remove("error").apply();CalendarWidget.renderAll(c);});
    }
    static void refresh(Context c,Runnable done){Context app=c.getApplicationContext();IO.execute(()->{try{sync(app,true);}catch(NetDiskSession.AccountChanged ignored){}catch(Exception e){prefs(app).edit().putString("error",e.getMessage()==null?"消息服务连接失败":e.getMessage()).apply();}new android.os.Handler(app.getMainLooper()).post(done);});}
    static void flushReads(Context c)throws Exception{flushReads(c,NetDiskSession.account(c));}
    static void flushReads(Context c,NetDiskSession.Account account)throws Exception{for(long[] r:TerminalDb.get(c).dirty()){NetDiskSession.Reply reply=requestBound(c,"/messages/"+r[0]+"/read",new JSONObject().put("is_read",r[1]!=0),account);NetDiskSession.guard(c,reply.account,()->TerminalDb.get(c).acknowledged(r[0],r[1]));}}
    static void exclude(Context c,JSONObject snapshot){JSONArray ids=snapshot.optJSONArray("excluded_message_ids");TerminalDb.get(c).exclude(ids);if(ids!=null){android.app.NotificationManager manager=(android.app.NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);for(int i=0;i<ids.length();i++)manager.cancel((int)ids.optLong(i)+1000);}}
    static void markRead(Context c,long id,boolean value){try{NetDiskSession.Account account=NetDiskSession.account(c);NetDiskSession.guard(c,account,()->{if(!NetDiskSession.canTerminal(c))throw new NetDiskSession.AccountChanged();TerminalDb.get(c).read(id,value);if(value)((android.app.NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE)).cancel((int)id+1000);prefs(c).edit().putLong("revision",System.currentTimeMillis()).apply();});IO.execute(()->{try{flushReads(c,account);}catch(Exception ignored){}});}catch(Exception ignored){}}
    static void markAllRead(Context c,Runnable done){try{NetDiskSession.Account account=NetDiskSession.account(c);long through=TerminalDb.get(c).maxId();IO.execute(()->{try{NetDiskSession.Reply reply=requestBound(c,"/messages/read-all",new JSONObject().put("through_id",through),account);NetDiskSession.guard(c,reply.account,()->{java.util.List<Long> ids=TerminalDb.get(c).readThrough(through);android.app.NotificationManager manager=(android.app.NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);for(long id:ids)manager.cancel((int)id+1000);prefs(c).edit().putLong("revision",System.currentTimeMillis()).apply();CalendarWidget.renderAll(c);});}catch(NetDiskSession.AccountChanged ignored){}catch(Exception e){new android.os.Handler(c.getMainLooper()).post(()->android.widget.Toast.makeText(c,"一键已读失败，请重试",android.widget.Toast.LENGTH_LONG).show());}new android.os.Handler(c.getMainLooper()).post(done);});}catch(NetDiskSession.AccountChanged ignored){done.run();}}
}
