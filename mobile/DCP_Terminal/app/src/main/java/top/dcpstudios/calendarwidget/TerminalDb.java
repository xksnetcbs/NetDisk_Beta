package top.dcpstudios.calendarwidget;

import android.content.*;
import android.database.Cursor;
import android.database.sqlite.*;
import org.json.*;
import java.util.*;

final class TerminalDb extends SQLiteOpenHelper {
    private static TerminalDb instance;
    private final Context context;
    static synchronized TerminalDb get(Context c){if(instance==null)instance=new TerminalDb(c.getApplicationContext());return instance;}
    private TerminalDb(Context c){super(c,"terminal.sqlite",null,1);context=c;}
    public void onCreate(SQLiteDatabase db){db.execSQL("CREATE TABLE messages(id INTEGER PRIMARY KEY, source TEXT, title TEXT, body TEXT, occurred INTEGER, is_read INTEGER, dirty INTEGER DEFAULT 0, data TEXT)");db.execSQL("CREATE TABLE schedules(id TEXT PRIMARY KEY,data TEXT)");}
    public void onUpgrade(SQLiteDatabase db,int old,int next){}
    synchronized boolean put(JSONObject message)throws JSONException{
        SQLiteDatabase db=getWritableDatabase();long id=message.getLong("id");boolean existed=false;int read=message.optBoolean("is_read")?1:0,dirty=0;
        try(Cursor old=db.rawQuery("SELECT is_read,dirty FROM messages WHERE id=?",new String[]{""+id})){if(old.moveToFirst()){existed=true;dirty=old.getInt(1);if(dirty!=0)read=old.getInt(0);}}
        ContentValues v=new ContentValues();v.put("id",id);v.put("source",message.optString("source"));v.put("title",message.optString("title"));v.put("body",message.optString("body"));v.put("occurred",message.optLong("occurred_at"));v.put("is_read",read);v.put("dirty",dirty);v.put("data",message.toString());db.insertWithOnConflict("messages",null,v,SQLiteDatabase.CONFLICT_REPLACE);return !existed;
    }
    synchronized void putAll(JSONArray messages)throws JSONException{
        SQLiteDatabase db=getWritableDatabase();db.beginTransaction();try{for(int i=0;i<messages.length();i++)put(messages.getJSONObject(i));db.setTransactionSuccessful();}finally{db.endTransaction();}
    }
    synchronized List<JSONObject> messages(String search){
        if(!NetDiskSession.canTerminal(context))return new ArrayList<>();
        List<JSONObject> all=new ArrayList<>();String filter="%"+search+"%";
        try(Cursor rows=getReadableDatabase().rawQuery("SELECT data,is_read FROM messages WHERE title LIKE ? OR body LIKE ? ORDER BY occurred DESC,id DESC LIMIT 1000",new String[]{filter,filter})){
            while(rows.moveToNext())try{JSONObject m=new JSONObject(rows.getString(0));m.put("is_read",rows.getInt(1)!=0);all.add(m);}catch(JSONException ignored){}
        }return all;
    }
    synchronized JSONObject message(long id){if(!NetDiskSession.canTerminal(context))return null;try(Cursor row=getReadableDatabase().rawQuery("SELECT data,is_read FROM messages WHERE id=?",new String[]{""+id})){if(row.moveToFirst()){JSONObject m=new JSONObject(row.getString(0));m.put("is_read",row.getInt(1)!=0);return m;}}catch(JSONException ignored){}return null;}
    synchronized void exclude(JSONArray ids){if(ids==null)return;SQLiteDatabase db=getWritableDatabase();db.beginTransaction();try{for(int i=0;i<ids.length();i++)db.delete("messages","id=?",new String[]{String.valueOf(ids.optLong(i))});db.setTransactionSuccessful();}finally{db.endTransaction();}}
    synchronized int unread(){if(!NetDiskSession.canTerminal(context))return 0;try(Cursor c=getReadableDatabase().rawQuery("SELECT count(*) FROM messages WHERE is_read=0",null)){c.moveToFirst();return c.getInt(0);}}
    synchronized long maxId(){try(Cursor c=getReadableDatabase().rawQuery("SELECT COALESCE(MAX(id),0) FROM messages",null)){c.moveToFirst();return c.getLong(0);}}
    synchronized List<Long> readThrough(long through){List<Long> ids=new ArrayList<>();SQLiteDatabase db=getWritableDatabase();try(Cursor c=db.rawQuery("SELECT id FROM messages WHERE id<=?",new String[]{""+through})){while(c.moveToNext())ids.add(c.getLong(0));}db.execSQL("UPDATE messages SET is_read=1,dirty=0 WHERE id<=?",new Object[]{through});return ids;}
    synchronized void read(long id,boolean value){ContentValues v=new ContentValues();v.put("is_read",value?1:0);v.put("dirty",1);getWritableDatabase().update("messages",v,"id=?",new String[]{""+id});}
    synchronized List<long[]> dirty(){List<long[]> all=new ArrayList<>();try(Cursor c=getReadableDatabase().rawQuery("SELECT id,is_read FROM messages WHERE dirty=1",null)){while(c.moveToNext())all.add(new long[]{c.getLong(0),c.getInt(1)});}return all;}
    synchronized void acknowledged(long id,long value){getWritableDatabase().execSQL("UPDATE messages SET dirty=0 WHERE id=? AND is_read=?",new Object[]{id,value});}
    private static boolean calendarSchedule(JSONObject s){return !"timetable".equals(s.optString("source"))&&!s.optString("id").startsWith("timetable:");}
    synchronized void schedule(JSONObject s)throws JSONException{if(!calendarSchedule(s))return;ContentValues v=new ContentValues();v.put("id",s.getString("id"));v.put("data",s.toString());getWritableDatabase().insertWithOnConflict("schedules",null,v,SQLiteDatabase.CONFLICT_REPLACE);}
    synchronized void schedules(JSONArray values)throws JSONException{
        SQLiteDatabase db=getWritableDatabase();db.beginTransaction();try{db.delete("schedules",null,null);for(int i=0;i<values.length();i++){JSONObject s=values.getJSONObject(i);if(!calendarSchedule(s))continue;ContentValues v=new ContentValues();v.put("id",s.getString("id"));v.put("data",s.toString());db.insertOrThrow("schedules",null,v);}db.setTransactionSuccessful();}finally{db.endTransaction();}
    }
    synchronized List<JSONObject> schedules(){List<JSONObject> all=new ArrayList<>();if(!NetDiskSession.isLoggedIn(context))return all;try(Cursor c=getReadableDatabase().rawQuery("SELECT data FROM schedules",null)){while(c.moveToNext())try{JSONObject row=new JSONObject(c.getString(0));if(calendarSchedule(row))all.add(row);}catch(JSONException ignored){}}return all;}
    synchronized void clearAccountData(){SQLiteDatabase db=getWritableDatabase();db.beginTransaction();try{db.delete("messages",null,null);db.delete("schedules",null,null);db.setTransactionSuccessful();}finally{db.endTransaction();}}
    synchronized List<CalendarData.Event> calendarEvents(){List<CalendarData.Event> all=new ArrayList<>();for(JSONObject s:schedules()){
        if("cancelled".equals(s.optString("status")))continue;CalendarData.Event e=new CalendarData.Event();e.uid=s.optString("id");e.title=s.optString("title");e.due=s.optLong("end_at");e.sourceCompleted=s.optBoolean("source_completed",s.optBoolean("completed","completed".equals(s.optString("status")))&&!s.optBoolean("forced_completed"));e.forcedCompleted=s.optBoolean("forced_completed");e.completed=e.sourceCompleted||e.forcedCompleted;e.course=s.optString("course","微信识别日程");e.url=s.optString("url");
        if("netdisk".equals(s.optString("source"))){e.course=s.optString("netdisk_kind",s.optString("kind")).equals("task")?"网盘任务":"网盘日程";e.url=NetDiskSession.base(context)+"/calendar";}
        e.description="<p>开始："+CalendarData.format(s.optLong("start_at"))+"</p><p>地点："+android.text.TextUtils.htmlEncode(s.optString("location"))+"</p><p>来源："+android.text.TextUtils.htmlEncode(s.optString("description"))+"</p>";all.add(e);
    }return all;}
}
