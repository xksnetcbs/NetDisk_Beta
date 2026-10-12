package top.dcpstudios.calendarwidget;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONObject;
import java.net.URLEncoder;
import java.util.List;

/** Personal overrides never change Canvas submission records. */
final class TaskOverrides {
    static void apply(Context c,List<CalendarData.Event> events){
        for(CalendarData.Event e:events){
            e.manuallyArchived=CalendarStore.prefs(c).getBoolean("archive:"+e.uid,false);
            SharedPreferences p=CalendarStore.prefs(c);
            // A pending local intent wins until the server acknowledges it. Once
            // acknowledged, the account's server state is the only authority.
            if(p.contains("force:"+e.uid))e.forcedCompleted=p.getBoolean("force:"+e.uid,false);
            e.completed=e.sourceCompleted||e.forcedCompleted;
        }
    }
    static void archive(Context c,String uid,boolean value){CalendarStore.prefs(c).edit().putBoolean("archive:"+uid,value).commit();CalendarWidget.renderAll(c);}
    static void complete(Context c,String uid,boolean value){
        try{NetDiskSession.Account account=NetDiskSession.account(c);NetDiskSession.guard(c,account,()->{
            CalendarStore.prefs(c).edit().putBoolean("force:"+uid,value).putLong("force_pending:"+uid,System.nanoTime()).commit();CalendarWidget.renderAll(c);
        });TerminalClient.IO.execute(()->{try{flush(c,account);TerminalClient.sync(c,false);}catch(NetDiskSession.AccountChanged ignored){}catch(Exception e){try{NetDiskSession.guard(c,account,()->CalendarStore.prefs(c).edit().putString("error","完成状态待同步 · "+e.getMessage()).commit());}catch(Exception ignored){}}});}catch(Exception ignored){}
    }
    static boolean flush(Context c,NetDiskSession.Account account)throws Exception {
        // The foreground stream and system job have their own worker threads.
        // Share sync's reentrant lock so an older request cannot finish after a
        // newer completion intent has already been acknowledged and cleared.
        synchronized(TerminalClient.class){
        boolean changed=false;SharedPreferences prefs=CalendarStore.prefs(c);
        java.util.Set<String> visible=new java.util.HashSet<>();for(JSONObject row:TerminalDb.get(c).schedules())visible.add(row.optString("id"));
        for(String key:prefs.getAll().keySet())if(key.startsWith("force:")){
            String uid=key.substring(6);final boolean value=prefs.getBoolean(key,false);final long version=prefs.getLong("force_pending:"+uid,0);
            if(!visible.contains(uid))continue;
            NetDiskSession.Reply response=NetDiskSession.requestMethod(c,"/api/mobile/terminal/schedules/"+URLEncoder.encode(uid,"UTF-8"),"POST",new JSONObject().put("forced_completed",value),account);
            NetDiskSession.guard(c,account,()->{JSONObject saved=response.data.optJSONObject("schedule");if(saved!=null)TerminalDb.get(c).schedule(saved);if(prefs.contains(key)&&prefs.getBoolean(key,false)==value&&prefs.getLong("force_pending:"+uid,0)==version)prefs.edit().remove(key).remove("force_pending:"+uid).commit();});changed=true;
        }
        return changed;
        }
    }
    static boolean pending(Context c,String uid){return CalendarStore.prefs(c).contains("force:"+uid);}
}
