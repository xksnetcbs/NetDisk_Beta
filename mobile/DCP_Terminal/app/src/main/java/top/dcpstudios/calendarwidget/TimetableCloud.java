package top.dcpstudios.calendarwidget;

import android.content.*;import org.json.*;

final class TimetableCloud {
 static synchronized void sync(Context c)throws Exception{
  sync(c,null);
 }
 static synchronized void sync(Context c,NetDiskSession.Account expected)throws Exception{
  if(!NetDiskSession.canTerminal(c)){CalendarStore.prefs(c).edit().putString("timetable_sync_status",NetDiskSession.isLoggedIn(c)?"当前账号的课表保存在本设备":"请先在网盘登录账号").apply();return;}
  SharedPreferences p=CalendarStore.prefs(c);NetDiskSession.Reply response=TerminalClient.requestBound(c,"/timetable",null,expected);JSONObject remote=response.data;String[] snapshot={null};long[] uploadRevision={0};
  NetDiskSession.guard(c,response.account,()->{
  synchronized(TimetableStore.class){
   long revision=p.getLong("timetable_revision",0);boolean dirty=p.getBoolean("timetable_dirty",false);
   if(!p.getBoolean("timetable_cloud_initialized",false)&&p.contains("timetable")&&remote.isNull("data")){dirty=true;p.edit().putBoolean("timetable_dirty",true).commit();}
   if(dirty){
    if(remote.optLong("revision")!=revision){p.edit().putString("timetable_conflict",remote.toString()).putString("timetable_sync_status","云端有新版本 · 点击处理冲突").commit();return;}
    snapshot[0]=TimetableStore.load(c).toString();uploadRevision[0]=revision;
   }else{
    SharedPreferences.Editor edit=p.edit();
    if(!remote.isNull("data")){JSONObject validated=TimetableStore.validate(remote.getJSONObject("data"));
     if(!p.getBoolean("timetable_cloud_initialized",false)&&p.contains("timetable")&&!TimetableStore.load(c).toString().equals(validated.toString())){edit.putString("timetable_conflict",remote.toString()).putString("timetable_sync_status","检测到本地与云端课表 · 点击选择").commit();return;}
     edit.putString("timetable",validated.toString());
    }
    edit.putLong("timetable_revision",remote.optLong("revision")).putBoolean("timetable_cloud_initialized",true).putString("timetable_sync_status",remote.isNull("data")?"云端暂无课表，编辑后自动上传":"已同步到云端").commit();
   }
  }
  });
  if(snapshot[0]!=null){
   NetDiskSession.Reply uploaded=TerminalClient.requestBound(c,"/timetable",new JSONObject().put("revision",uploadRevision[0]).put("data",new JSONObject(snapshot[0])),response.account);JSONObject result=uploaded.data;
   NetDiskSession.guard(c,uploaded.account,()->{
   synchronized(TimetableStore.class){
    boolean changed=!TimetableStore.load(c).toString().equals(snapshot[0]);
    p.edit().putLong("timetable_revision",result.getLong("revision")).putBoolean("timetable_dirty",changed).putBoolean("timetable_cloud_initialized",true).remove("timetable_conflict").putString("timetable_sync_status",changed?"新编辑等待上传":"已同步到云端").commit();
   }
   });
  }
 }
 static void refresh(Context c,Runnable done){Context app=c.getApplicationContext();TerminalClient.IO.execute(()->{try{sync(app);}catch(NetDiskSession.AccountChanged ignored){}catch(Exception e){CalendarStore.prefs(app).edit().putString("timetable_sync_status","同步失败，本地已保留 · 点击重试").apply();}new android.os.Handler(app.getMainLooper()).post(done);});}
 static void resolve(MainActivity a,Runnable done){SharedPreferences p=CalendarStore.prefs(a);String conflict=p.getString("timetable_conflict","");if(conflict.isEmpty()){refresh(a,done);return;}
  final NetDiskSession.Account account;try{account=NetDiskSession.account(a);}catch(NetDiskSession.AccountChanged ignored){return;}
  new android.app.AlertDialog.Builder(a).setTitle("选择课表版本").setMessage("本地编辑与云端版本不同。未选择前不会覆盖任何一方。旧本地课表将保留在恢复记录中。")
   .setPositiveButton("使用云端",(d,w)->{try{NetDiskSession.guard(a,account,()->{synchronized(TimetableStore.class){JSONObject r=new JSONObject(conflict);JSONObject data=TimetableStore.validate(r.getJSONObject("data"));p.edit().putString("timetable_previous",TimetableStore.load(a).toString()).putString("timetable",data.toString()).putLong("timetable_revision",r.getLong("revision")).putBoolean("timetable_dirty",false).putBoolean("timetable_cloud_initialized",true).remove("timetable_conflict").commit();}});refresh(a,done);}catch(NetDiskSession.AccountChanged ignored){}catch(Exception e){a.error(e);}})
   .setNeutralButton("用本地覆盖",(d,w)->{try{NetDiskSession.guard(a,account,()->{synchronized(TimetableStore.class){JSONObject r=new JSONObject(conflict);p.edit().putLong("timetable_revision",r.getLong("revision")).putBoolean("timetable_dirty",true).putBoolean("timetable_cloud_initialized",true).remove("timetable_conflict").commit();}});refresh(a,done);}catch(NetDiskSession.AccountChanged ignored){}catch(Exception e){a.error(e);}}).setNegativeButton("稍后",null).show();
 }
}
