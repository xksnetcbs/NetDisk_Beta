package top.dcpstudios.calendarwidget;
import android.content.*;
import org.json.*;
/** Old schedule caches cannot mix independent courses into agendas or widgets. */
final class TimetableCalendarRegression {
    static void raw(TerminalDb db,JSONObject row)throws Exception{ContentValues value=new ContentValues();value.put("id",row.getString("id"));value.put("data",row.toString());db.getWritableDatabase().insertOrThrow("schedules",null,value);}
    static void run(TerminalIntegrationInstrumentation test,Context c)throws Exception{
        NetDiskRaceRegression.identity(test,c,true);TerminalDb db=TerminalDb.get(c);
        JSONObject event=new JSONObject().put("id","netdisk:event:110").put("source","netdisk").put("title","真实日程验收").put("end_at",System.currentTimeMillis()+3600000).put("status","active");
        JSONObject course=new JSONObject().put("id","legacy-source-course").put("source","timetable").put("title","旧缓存课表来源").put("end_at",System.currentTimeMillis()+3600000).put("status","active");
        JSONObject legacy=new JSONObject().put("id","timetable:legacy-course:1").put("source","calendar").put("title","旧缓存课表UID").put("end_at",System.currentTimeMillis()+3600000).put("status","active");
        db.schedules(new JSONArray().put(event));raw(db,course);raw(db,legacy);
        test.check(db.schedules().size()==1&&"netdisk:event:110".equals(db.schedules().get(0).optString("id")),"legacy SQLite timetable source and timetable UID rows are excluded from schedules");
        test.check(CalendarStore.read(c).size()==1&&"netdisk:event:110".equals(CalendarStore.read(c).get(0).uid),"agenda retains the real event while hiding all cached timetable rows");
        WidgetListService.Rows widget=new WidgetListService.Rows(c);widget.onCreate();test.check(widget.getCount()==1,"widget calendar factory excludes old timetable caches");
        db.schedules(new JSONArray().put(event).put(course).put(legacy));db.schedule(course);
        try(android.database.Cursor rows=db.getReadableDatabase().rawQuery("SELECT count(*) FROM schedules",null)){rows.moveToFirst();test.check(rows.getInt(0)==1,"bulk snapshot and single ACK saves never persist timetable schedules");}
        CalendarStore.prefs(c).edit().putBoolean("force:timetable:legacy-course:1",true).commit();int writes=NetDiskTransportRegression.forceWrites;
        test.check(!TaskOverrides.flush(c,NetDiskSession.account(c))&&NetDiskTransportRegression.forceWrites==writes,"obsolete timetable force markers do not produce schedule mutations");
        JSONArray weeks=new JSONArray();for(int i=1;i<=20;i++)weeks.put(i);
        JSONObject independent=TimetableStore.empty().put("courses",new JSONArray().put(new JSONObject().put("id","independent-course").put("name","独立课表课程").put("location","验收教室").put("day",1).put("weeks",weeks).put("periods",new JSONArray().put(1).put(2))));
        NetDiskTransportRegression.timetableData=independent;TimetableCloud.sync(c,NetDiskSession.account(c));
        test.check(TimetableStore.load(c).getJSONArray("courses").length()==1&&CalendarStore.prefs(c).getLong("timetable_revision",0)==17,"independent timetable cloud sync still retains its course and revision");
        test.activity=test.startActivitySync(new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        test.runOnMainSync(()->{MainActivity a=(MainActivity)test.activity;a.timetable();test.check(TerminalIntegrationInstrumentation.textPresent(a.root,"独立课表课程\n验收教室"),"independent native timetable page still renders cloud courses");a.finish();});test.activity=null;
        NetDiskTransportRegression.timetableData=null;NetDiskSession.observeWebLogin(c,true);
    }
}
