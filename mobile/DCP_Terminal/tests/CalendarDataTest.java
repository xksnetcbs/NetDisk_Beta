import top.dcpstudios.calendarwidget.CalendarData;
import java.util.*;
public class CalendarDataTest {
 static int passed=0;
 static void check(boolean condition,String name){if(!condition)throw new AssertionError(name);System.out.println("PASS "+name);passed++;}
 static CalendarData.Event event(String uid,boolean done,long due){CalendarData.Event e=new CalendarData.Event();e.uid=uid;e.title=uid;e.completed=done;e.due=due;return e;}
 public static void main(String[] args)throws Exception{
  TimeZone.setDefault(TimeZone.getTimeZone("Asia/Shanghai"));
  String ics="BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a\r\nSUMMARY:[已完成] 长标题\r\n 继续标题\r\nDESCRIPTION:正文\\n下一行\\,逗号\r\nDTEND:20260901T010000Z\r\nX-CANVAS-DUE:20260920T120000Z\r\nX-CANVAS-COURSE:工程课\r\nBEGIN:VALARM\r\nDESCRIPTION:不要覆盖正文\r\nEND:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
  CalendarData.Event e=CalendarData.parse(ics).get(0);
  check(e.title.equals("长标题继续标题"),"unfold SUMMARY before parsing");
  check(e.description.equals("正文\n下一行,逗号"),"ignore VALARM description and decode escapes");
  check(e.completed&&e.course.equals("工程课"),"completion and course metadata");
  check(CalendarData.format(e.due).equals("2026年9月20日 20:00"),"UTC conversion and original deadline over completion time");
  check(CalendarData.date("20260920T200000","DTEND;TZID=Asia/Shanghai")==e.due,"TZID parsing");
  long now=CalendarData.date("20260915T120000Z","DTEND");
  List<CalendarData.Event> all=Arrays.asList(event("old-done",true,now-CalendarData.WEEK-1),event("pending-old",false,now-CalendarData.WEEK*3),event("recent-done",true,now-1000),event("pending-next",false,now+1000),event("boundary",true,now-CalendarData.WEEK));
  List<CalendarData.Event> home=CalendarData.visible(all,now,true,false);
  check(home.size()==4&&home.get(0).uid.equals("pending-old")&&home.get(1).uid.equals("pending-next"),"pending first, overdue pending retained, old completed hidden");
  check(CalendarData.visible(all,now,true,true).size()==1,"archive boundary and preservation");
  check(CalendarData.visible(all,now,false,false).size()==2,"hide completed preference");
  try{CalendarData.parse("<html>login</html>");throw new AssertionError("HTML accepted");}catch(java.io.IOException expected){check(true,"non-calendar response rejected");}
  try{CalendarData.date("20261399T250000Z","DTEND");throw new AssertionError("invalid date accepted");}catch(java.io.IOException expected){check(true,"invalid date rejected");}
  CalendarData.Event archived=event("manual",false,now-1000);archived.manuallyArchived=true;
  check(CalendarData.visible(Arrays.asList(archived),now,true,false).isEmpty(),"manual archive excluded from home");
  check(CalendarData.visible(Arrays.asList(archived),now,true,true).size()==1,"manual archive retained in archive");
  archived.manuallyArchived=false;check(CalendarData.visible(Arrays.asList(archived),now,true,false).size()==1,"unarchive restores pending");
  CalendarData.Event forced=event("forced",true,now-CalendarData.WEEK-1);forced.forcedCompleted=true;
  check(CalendarData.visible(Arrays.asList(forced),now,true,false).isEmpty(),"forced completion follows old-completed hiding");
  List<CalendarData.Event> many=new ArrayList<>();for(int n=0;n<80;n++)many.add(event("pending-"+n,false,now+n));many.add(event("completed",true,now));many.add(event("no-date",false,0));
  List<CalendarData.Event> pending=CalendarData.visible(many,now,false,false);
  check(pending.size()==81&&pending.get(80).uid.equals("no-date"),"all pending retained without row cap, completed excluded, undated last");
  if(args.length>0){List<CalendarData.Event> actual=CalendarData.parse(new String(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(args[0])),java.nio.charset.StandardCharsets.UTF_8));check(actual.size()==90,"live server 90 events");long courses=actual.stream().filter(x->!x.course.isEmpty()).count();check(courses==90,"live server course metadata");System.out.println("LIVE main="+CalendarData.visible(actual,now,true,false).size()+" archive="+CalendarData.visible(actual,now,true,true).size());}
  System.out.println("Passed "+passed+" checks");
 }
}
