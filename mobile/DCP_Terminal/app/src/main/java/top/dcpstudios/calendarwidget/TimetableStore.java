package top.dcpstudios.calendarwidget;

import android.content.Context;
import org.json.*;
import java.util.*;

final class TimetableStore {
    static JSONObject empty(){try{
        JSONObject root=new JSONObject().put("schema_version",1).put("term",new JSONObject().put("name","我的课表").put("week1_monday","2026-09-07").put("start_week",1).put("end_week",20));
        JSONArray periods=new JSONArray();String[] starts={"08:00","08:55","10:00","10:55","13:30","14:25","15:30","16:25","18:30","19:25","20:20"};
        for(int i=0;i<11;i++){int end=TimetableData.minutes(starts[i])+45;periods.put(new JSONObject().put("number",i+1).put("start",starts[i]).put("end",String.format(Locale.US,"%02d:%02d",end/60,end%60)));}
        return root.put("periods",periods).put("courses",new JSONArray());
    }catch(JSONException e){throw new IllegalStateException(e);}}
    static JSONObject load(Context c){if(!NetDiskSession.isLoggedIn(c))return empty();try{return validate(new JSONObject(CalendarStore.prefs(c).getString("timetable",empty().toString())));}catch(Exception e){return empty();}}
    static synchronized void save(Context c,JSONObject data)throws Exception{validate(data);CalendarStore.prefs(c).edit().putString("timetable_previous",load(c).toString()).putString("timetable",data.toString()).putBoolean("timetable_dirty",true).putString("timetable_sync_status","等待上传 · 本地编辑已保存").commit();TimetableCloud.refresh(c,()->{});}
    static void undo(Context c)throws Exception{String previous=CalendarStore.prefs(c).getString("timetable_previous","");if(previous.isEmpty())throw new IllegalArgumentException("没有可恢复的编辑");save(c,new JSONObject(previous));}
    static JSONObject validate(JSONObject data)throws Exception{
        if(data.getInt("schema_version")!=1)throw new IllegalArgumentException("不支持的课表格式版本");JSONObject term=data.getJSONObject("term");TimetableData.monday(term.getString("week1_monday"));int first=term.getInt("start_week"),last=term.getInt("end_week");if(first<1||last>60||first>last)throw new IllegalArgumentException("学期周数应在 1—60 之间");
        JSONArray times=data.getJSONArray("periods");if(times.length()!=11)throw new IllegalArgumentException("必须定义 1—11 节的起止时间");int previous=-1;
        for(int i=0;i<11;i++){JSONObject p=times.getJSONObject(i);if(p.getInt("number")!=i+1)throw new IllegalArgumentException("节次必须按 1—11 排列");int start=TimetableData.minutes(p.getString("start")),end=TimetableData.minutes(p.getString("end"));if(start>=end||start<previous)throw new IllegalArgumentException("节次时间不能倒置或重叠");previous=end;}
        JSONArray courses=data.getJSONArray("courses");if(courses.length()>500)throw new IllegalArgumentException("课表最多支持 500 条课程安排");Set<String> ids=new HashSet<>();
        for(int i=0;i<courses.length();i++){JSONObject course=courses.getJSONObject(i);if(course.getString("id").isEmpty()||!ids.add(course.getString("id")))throw new IllegalArgumentException("课程 id 不能为空或重复");if(course.getString("name").trim().isEmpty())throw new IllegalArgumentException("课程名称不能为空");int day=course.getInt("day");if(day<1||day>7)throw new IllegalArgumentException("星期范围为 1—7");numbers(course.getJSONArray("weeks"),first,last);numbers(course.getJSONArray("periods"),1,11);}
        return data;
    }
    static SortedSet<Integer> numbers(JSONArray data,int min,int max)throws Exception{SortedSet<Integer> result=new TreeSet<>();if(data.length()==0)throw new IllegalArgumentException("周次、节次不能为空");for(int i=0;i<data.length();i++){Object raw=data.get(i);if(!(raw instanceof Number)||((Number)raw).doubleValue()!=((Number)raw).intValue())throw new IllegalArgumentException("周次与节次必须为整数");int n=data.getInt(i);if(n<min||n>max)throw new IllegalArgumentException("周次或节次超出设置范围");result.add(n);}return result;}
    static JSONArray array(Collection<Integer> values){JSONArray out=new JSONArray();for(int n:values)out.put(n);return out;}
    static String numbersText(JSONArray a){List<Integer> values=new ArrayList<>();for(int i=0;i<a.length();i++)values.add(a.optInt(i));return TimetableData.join(values);}
}
