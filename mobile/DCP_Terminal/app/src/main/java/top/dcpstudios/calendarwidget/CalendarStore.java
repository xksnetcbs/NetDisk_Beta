package top.dcpstudios.calendarwidget;
import android.content.*;
import java.io.*;
import java.net.URLEncoder;
import java.util.*;
/** Server snapshot is the one calendar authority for all three clients. */
public final class CalendarStore {
 public static SharedPreferences prefs(Context c){return c.getSharedPreferences("calendar",0);}
 static void clearCache(Context c){new File(c.getFilesDir(),"calendar.ics").delete();}
 public static List<CalendarData.Event> read(Context c){List<CalendarData.Event> events=TerminalDb.get(c).calendarEvents();TaskOverrides.apply(c,events);return events;}
 public static List<CalendarData.Event> sync(Context c)throws IOException {
  try{TerminalClient.sync(c,false);return read(c);}catch(IOException e){throw e;}catch(Exception e){throw new IOException(e.getMessage(),e);}
 }
 public static void delete(Context c,String uid)throws IOException {
  try{NetDiskSession.Account account=NetDiskSession.account(c);NetDiskSession.requestMethod(c,"/api/mobile/terminal/schedules/"+URLEncoder.encode(uid,"UTF-8"),"DELETE",null,account);TerminalClient.sync(c,false);}catch(IOException e){throw e;}catch(Exception e){throw new IOException(e.getMessage(),e);}
 }
 public static String status(Context c){long t=prefs(c).getLong("lastSync",0);String e=prefs(c).getString("error","");String time=new java.text.SimpleDateFormat("M/d HH:mm",Locale.CHINA).format(new Date(t));return !e.isEmpty()?(t==0?"同步失败 · 点击重试":"离线缓存 · "+time):(t==0?"尚未同步":"更新于 "+time);}
}
