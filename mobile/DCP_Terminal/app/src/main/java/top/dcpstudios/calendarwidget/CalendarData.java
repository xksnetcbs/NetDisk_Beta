package top.dcpstudios.calendarwidget;

import java.io.*;
import java.text.*;
import java.util.*;

/** Shared, Android-independent calendar parsing and display policy. */
public final class CalendarData {
    public static final long WEEK = 7L * 24 * 60 * 60 * 1000;
    public static final class Event {
        public String uid="", title="", description="", course="", url="";
        public long due;
        public boolean completed, sourceCompleted, manuallyArchived, forcedCompleted;
    }
    public static List<Event> parse(String ics) throws IOException {
        if (!ics.contains("BEGIN:VCALENDAR") || !ics.contains("END:VCALENDAR"))
            throw new IOException("服务器未返回有效日历");
        List<String> lines=new ArrayList<>();
        for(String line:ics.replace("\r\n","\n").split("\n")) {
            if((line.startsWith(" ")||line.startsWith("\t"))&&!lines.isEmpty()) {
                int i=lines.size()-1;lines.set(i,lines.get(i)+line.substring(1));
            } else lines.add(line);
        }
        LinkedHashMap<String,Event> result=new LinkedHashMap<>();
        Event e=null; int nested=0; long end=0, explicitDue=0;
        for(String line:lines) {
            if(line.equals("BEGIN:VEVENT")){e=new Event();nested=0;end=explicitDue=0;continue;}
            if(e==null)continue;
            if(line.equals("END:VEVENT")) {
                e.due=explicitDue!=0?explicitDue:end;
                e.completed|=e.title.startsWith("[已完成]");
                e.sourceCompleted=e.completed;
                e.title=e.title.replaceFirst("^\\[(已完成|!!!)\\]\\s*", "");
                if(!e.uid.isEmpty()&&!e.title.isEmpty())result.put(e.uid,e);
                e=null;continue;
            }
            if(line.startsWith("BEGIN:")){nested++;continue;}
            if(line.startsWith("END:")){nested--;continue;}
            if(nested>0)continue;
            int colon=line.indexOf(':');if(colon<0)continue;
            String head=line.substring(0,colon),name=head.split(";",2)[0].toUpperCase(Locale.ROOT),value=line.substring(colon+1);
            switch(name) {
                case "UID": e.uid=decode(value);break;
                case "SUMMARY": e.title=decode(value);break;
                case "DESCRIPTION": e.description=decode(value);break;
                case "URL": e.url=decode(value);break;
                case "X-CANVAS-COURSE": e.course=decode(value);break;
                case "X-CANVAS-COMPLETED": e.completed="TRUE".equalsIgnoreCase(value);break;
                case "STATUS": e.completed|="COMPLETED".equalsIgnoreCase(value);break;
                case "DTEND": end=date(value,head);break;
                case "X-CANVAS-DUE": explicitDue=date(value,head);break;
            }
        }
        if(e!=null)throw new IOException("日历内容不完整");
        return new ArrayList<>(result.values());
    }
    public static String decode(String value) {
        StringBuilder b=new StringBuilder();
        for(int i=0;i<value.length();i++){
            char ch=value.charAt(i);
            if(ch=='\\'&&i+1<value.length()) {ch=value.charAt(++i);b.append(ch=='n'||ch=='N'?'\n':ch);}
            else b.append(ch);
        }
        return b.toString();
    }
    public static long date(String value,String head) throws IOException {
        String pattern=value.length()==8?"yyyyMMdd":value.endsWith("Z")?"yyyyMMdd'T'HHmmss'Z'":"yyyyMMdd'T'HHmmss";
        SimpleDateFormat f=new SimpleDateFormat(pattern,Locale.US);f.setLenient(false);
        if(value.endsWith("Z"))f.setTimeZone(TimeZone.getTimeZone("UTC"));
        else if(head.contains("TZID="))f.setTimeZone(TimeZone.getTimeZone(head.substring(head.indexOf("TZID=")+5).split(";",2)[0].replace("\"","")));
        ParsePosition p=new ParsePosition(0);Date date=f.parse(value,p);
        if(date==null||p.getIndex()!=value.length())throw new IOException("日历时间格式错误");
        return date.getTime();
    }
    public static boolean archived(Event e,long now) {return e.manuallyArchived||(e.completed&&e.due>0&&e.due<now-WEEK);}
    public static List<Event> visible(List<Event> all,long now,boolean showDone,boolean archive) {
        List<Event> result=new ArrayList<>();
        for(Event e:all)if(archive?archived(e,now):(!archived(e,now)&&(showDone||!e.completed)))result.add(e);
        Collections.sort(result,(a,b)->{
            int done=Boolean.compare(a.completed,b.completed);if(done!=0)return done;
            long x=a.due==0?Long.MAX_VALUE:a.due,y=b.due==0?Long.MAX_VALUE:b.due;
            int order=a.completed?Long.compare(y,x):Long.compare(x,y);
            return order!=0?order:a.uid.compareTo(b.uid);
        });return result;
    }
    public static String format(long time) {return time==0?"未设置截止时间":new SimpleDateFormat("yyyy年M月d日 HH:mm",Locale.CHINA).format(new Date(time));}
    public static String timing(Event e,long now) {
        if(e.forcedCompleted)return "已强制完成";
        if(e.completed)return "已完成";
        if(e.due==0)return "待安排";
        long delta=e.due-now;
        if(delta<0)return "已逾期";
        if(delta<3600000)return "不足 1 小时";
        if(delta<86400000)return (long)Math.ceil(delta/3600000d)+" 小时内截止";
        return (long)Math.ceil(delta/86400000d)+" 天后截止";
    }
}
